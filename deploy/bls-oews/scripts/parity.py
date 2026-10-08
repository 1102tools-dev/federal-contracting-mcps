"""Parity check: the D1 Worker against the Python bls-oews-mcp server.

Sends every case in test/parity-cases.json to both servers and compares the
HTTP status and the raw response body byte for byte (tool results carry
content[0].text, structuredContent and isError, so this covers all three).

- Python: bls_oews_mcp.http.create_app() in hosted mode (BLS_HOSTED=1, data
  checked at start as the container does), through Starlette's TestClient.
- Worker: src/worker.ts over a SQLite copy of D1 that
  scripts/load_bls_oews.py --local builds from the same bundled release.

Run from the repository root with the container's Python (3.12; 3.13+
strips docstring indentation, which changes tool descriptions):

    UV_PROJECT_ENVIRONMENT=/tmp/bls-py312 uv run --frozen --python 3.12 \\
        --project servers/bls-oews-mcp python deploy/bls-oews/scripts/parity.py [--db d1.sqlite] [--show]

(In an iCloud checkout add PYTHONPATH=servers/bls-oews-mcp/src.)

Exits 1 on any difference not listed in DOCUMENTED.
"""
import argparse, difflib, importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_DIR = ROOT / "deploy/bls-oews"
CASES = WORKER_DIR / "test/parity-cases.json"
HEADERS = {"host": "localhost:8080", "accept": "application/json, text/event-stream",
           "content-type": "application/json"}

# Cases whose answers differ on purpose: the reason, and a check (given both
# {status, body} answers) that the difference is only that. Keep this short.
TOOLS_LIST = (
    "The Worker returns tools-contract.json verbatim (tools sorted by name, keys sorted, "
    "as scripts/check_hosted_contract.py writes it); Python lists them in registration order. "
    "Same tools, same definitions.",
    lambda py, ts: py["status"] == ts["status"] and tools_by_name(py) == tools_by_name(ts),
)
INVALID_MESSAGE = (
    "Invalid JSON-RPC messages get the SDK's HTTP 400 and error code, but a short message "
    "instead of its parser or pydantic error dump.",
    lambda py, ts: py["status"] == ts["status"] == 400 and error_code(py) == error_code(ts),
)
DOCUMENTED = {
    "tools/list": TOOLS_LIST,
    "tools/list with cursor": TOOLS_LIST,
    "invalid: malformed JSON": INVALID_MESSAGE,
    "invalid: batch": INVALID_MESSAGE,
    "invalid: jsonrpc 1.0": INVALID_MESSAGE,
    "invalid: params is a list": INVALID_MESSAGE,
    "invalid: NaN literal": (
        "NaN and Infinity are not JSON (RFC 8259). The SDK's parser accepts them; the Worker "
        "answers with a parse error (HTTP 400, -32700).",
        lambda py, ts: ts["status"] == 400 and error_code(ts) == -32700,
    ),
    "numeric-looking extra argument names": (
        "JavaScript objects list integer-like keys first, so pydantic's extra-argument errors "
        "for keys such as \"10\" come in a different order. Same errors otherwise.",
        lambda py, ts: py["status"] == ts["status"] and error_blocks(py) == error_blocks(ts),
    ),
}


def error_code(answer):
    return json.loads(answer["body"])["error"]["code"]


def error_blocks(answer):
    """A tool's validation error text as its header plus the set of per-field errors."""
    head, *lines = json.loads(answer["body"])["result"]["content"][0]["text"].split("\n")
    return head, sorted("\n".join(lines[i:i + 3]) for i in range(0, len(lines), 3))


def tools_by_name(answer):
    return sorted(json.loads(answer["body"])["result"]["tools"], key=lambda tool: tool["name"])


def request_body(case):
    if "raw" in case:
        return case["raw"]
    message = {"jsonrpc": "2.0"}
    if not case.get("notification"):
        message["id"] = 1
    if "tool" in case:
        message.update(method="tools/call", params={"name": case["tool"], "arguments": case["arguments"]})
    else:
        message["method"] = case["method"]
        if "params" in case:
            message["params"] = case["params"]
    return json.dumps(message, ensure_ascii=False)


def build_database(path):
    spec = importlib.util.spec_from_file_location("load_bls_oews", ROOT / "scripts/load_bls_oews.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    loader.load(loader.LocalD1(path), log=lambda message: None)


def run_python(requests, data_dir):
    os.environ["BLS_HOSTED"] = "1"
    os.environ["BLS_OEWS_DATA_DIR"] = str(data_dir)
    from starlette.testclient import TestClient
    from bls_oews_mcp import http

    http.require_bundled_data()
    out = {}
    with TestClient(http.create_app()) as client:
        for item in requests:
            response = client.post("/mcp", headers=HEADERS, content=item["body"].encode())
            out[item["name"]] = {"status": response.status_code, "body": response.text}
    return out


def run_worker(requests, database, scratch):
    path = Path(scratch) / "requests.json"
    path.write_text(json.dumps(requests, ensure_ascii=False))
    proc = subprocess.run(["node", "scripts/parity-run.ts", str(database), str(path)],
                          cwd=WORKER_DIR, capture_output=True, text=True, check=True)
    lines = [json.loads(line) for line in proc.stdout.split("\n") if line.startswith("{")]
    return {line["name"]: line for line in lines}


def pretty(body):
    """A readable form for diffs: the body, plus content[0].text unescaped."""
    try:
        message = json.loads(body)
    except ValueError:
        return body.splitlines()
    lines = json.dumps(message, indent=2, ensure_ascii=False).splitlines()
    content = (message.get("result") or {}).get("content") if isinstance(message, dict) else None
    if content:
        lines += ["--- content[0].text ---", *content[0]["text"].splitlines()]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, help="an existing local D1 copy (default: build one)")
    parser.add_argument("--show", action="store_true", help="print every case's statements and round trips")
    args = parser.parse_args(argv)

    cases = json.loads(CASES.read_text())
    names = [case["name"] for case in cases]
    if len(set(names)) != len(names):
        raise SystemExit("Case names must be unique.")
    requests = [{"name": case["name"], "body": request_body(case)} for case in cases]

    with tempfile.TemporaryDirectory(prefix="bls-parity-") as scratch:
        database = args.db
        if database is None:
            database = Path(scratch) / "d1.sqlite"
            build_database(database)
        worker = run_worker(requests, database, scratch)
        python = run_python(requests, Path(scratch) / "python-data")

    unexpected = documented = 0
    for name in names:
        py, ts = python[name], worker[name]
        if args.show:
            print(f"{name}: {ts['statements']} statements, {ts['round_trips']} round trips")
        if (py["status"], py["body"]) == (ts["status"], ts["body"]):
            continue
        if name in DOCUMENTED and DOCUMENTED[name][1](py, ts):
            documented += 1
            print(f"DOCUMENTED {name}: {DOCUMENTED[name][0]}")
            continue
        unexpected += 1
        print(f"DIFF {name}: status python={py['status']} worker={ts['status']}")
        sys.stdout.writelines(line + "\n" for line in difflib.unified_diff(
            pretty(py["body"]), pretty(ts["body"]), "python", "worker", lineterm="", n=2))
    print(f"{len(names)} cases: {len(names) - unexpected - documented} identical, "
          f"{documented} documented differences, {unexpected} unexpected differences.")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
