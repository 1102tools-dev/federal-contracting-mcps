"""Parity check: the D1 Worker against the Python acquisition-gov-mcp server.

Sends every case in test/parity-cases.json to both servers and compares the
HTTP status and the raw response body byte for byte (tool results carry
content[0].text, structuredContent and isError, so this covers all three).

- Python: acquisition_gov_mcp.http.create_app() (the app the container ran),
  through Starlette's TestClient, with its upstream fetch replaced by a
  recording made by scripts/load_acquisition_gov.py --record. _now() reports
  the fetch time of the last response read, which is what retrieved_at says
  in a live call made right after that fetch.
- Worker: src/worker.ts over a SQLite copy of D1 that
  scripts/load_acquisition_gov.py --local --replay builds from the same recording.

Run from the repository root with the container's Python (3.12):

    uv run --frozen --python 3.12 --project servers/acquisition-gov-mcp \\
        python deploy/acquisition-gov/scripts/parity.py --rec REC_DIR [--db d1.sqlite] [--show]

(In an iCloud checkout add PYTHONPATH=servers/acquisition-gov-mcp/src.)
REC_DIR defaults to deploy/acquisition-gov/.snapshot.nosync/rec (the full
recording, not in git). Cases must only name PDFs the recording holds. CI runs
test/fixture-cases.json against the small recording test/fixture_recording.py
writes (--rec DIR --cases deploy/acquisition-gov/test/fixture-cases.json).

Exits 1 on any difference not listed in DOCUMENTED.
"""
import argparse, difflib, importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_DIR = ROOT / "deploy/acquisition-gov"
SRC = ROOT / "servers/acquisition-gov-mcp/src"
CASES = WORKER_DIR / "test/parity-cases.json"
HEADERS = {"host": "localhost:8080", "accept": "application/json, text/event-stream",
           "content-type": "application/json"}

# Cases whose answers differ on purpose: the reason, and a check (given both
# {status, body} answers) that the difference is only that. Keep this short.
TOOLS_LIST = (
    "The Worker returns tools-contract.json verbatim (tools sorted by name, keys sorted, "
    "as scripts/check_hosted_contract.py writes it); Python lists them in registration order. "
    "Same tools, same definitions.",
    lambda py, ts: py["status"] == ts["status"] and same_except_tool_order(py, ts),
)
INVALID_MESSAGE = (
    "Invalid JSON-RPC messages get the SDK's HTTP 400 and error code, but a short message "
    "instead of its parser or pydantic error dump.",
    lambda py, ts: py["status"] == ts["status"] == 400 and error_code(py) == error_code(ts),
)
DOCUMENTED = {
    "tools/list": TOOLS_LIST,
    "tools/list with cursor": TOOLS_LIST,
    "modern: tools/list": TOOLS_LIST,
    "modern: tools/list with cursor": TOOLS_LIST,
    "modern: capabilities with unknown keys": TOOLS_LIST,
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


def same_except_tool_order(py, ts):
    """The same tool definitions (compared as data), and the rest of the body byte for byte."""
    def split(answer):
        message = json.loads(answer["body"])
        tools = sorted(message["result"].pop("tools"), key=lambda tool: tool["name"])
        return json.dumps(message), tools
    return split(py) == split(ts)


MODERN = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "parity", "version": "1"}}
NAME_PARAM = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}


def request(case):
    """The exact body and headers both servers receive for one case.

    "modern": true sends it as MCP 2026-07-28 does: params._meta carries the
    envelope and the routing headers mirror the body. "headers" adds to or
    (with null) removes headers.
    """
    headers = dict(HEADERS)
    if "raw" in case:
        body = case["raw"]
    else:
        message = {"jsonrpc": "2.0"}
        if not case.get("notification"):
            message["id"] = case.get("id", 1)
        if "tool" in case:
            message.update(method="tools/call", params={"name": case["tool"], "arguments": case["arguments"]})
        else:
            message["method"] = case["method"]
            if "params" in case:
                message["params"] = case["params"]
        if case.get("modern"):
            params = message.setdefault("params", {})
            params.setdefault("_meta", case.get("meta", META))
            headers["mcp-protocol-version"] = MODERN
            headers["mcp-method"] = message["method"]
            if isinstance(params.get(NAME_PARAM.get(message["method"])), str):
                headers["mcp-name"] = params[NAME_PARAM[message["method"]]]
        body = json.dumps(message, ensure_ascii=False)
    for name, value in case.get("headers", {}).items():
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
    return {"name": case["name"], "body": body, "headers": headers}


def build_database(path, rec):
    subprocess.run([sys.executable, str(ROOT / "scripts/load_acquisition_gov.py"), "--local", str(path),
                    "--replay", str(rec), "--allow-missing"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Replay:
    """The package's _fetch_bytes, answered from the recording."""

    def __init__(self, path):
        self.path = Path(path)
        self.entries = json.loads((self.path / "manifest.json").read_text())
        self.now = "1970-01-01T00:00:00+00:00"

    async def fetch_bytes(self, url, *, allowed_types, max_bytes):
        entry = self.entries.get(f"{url} {allowed_types[0]}")
        if entry is None:
            raise SystemExit(f"Parity case needs {url}, which the recording does not hold.")
        self.now = entry["fetched_at"]
        if "error" in entry:
            raise RuntimeError(entry["error"])
        return (self.path / "bodies" / entry["sha256"]).read_bytes(), entry["content_type"], entry["final_url"]


def run_python(requests, rec):
    # The package parses in child processes; they must import the same source.
    sys.path.insert(0, str(SRC))
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), os.environ.get("PYTHONPATH")]))
    from starlette.testclient import TestClient
    from acquisition_gov_mcp import http, server

    replay = Replay(rec)
    server._fetch_bytes = replay.fetch_bytes
    server._now = lambda: replay.now
    out = {}
    with TestClient(http.create_app()) as client:
        for item in requests:
            response = client.post("/mcp", headers=item["headers"], content=item["body"].encode())
            out[item["name"]] = {"status": response.status_code, "body": response.text}
    return out


def run_worker(requests, database, scratch):
    path = Path(scratch) / "requests.json"
    path.write_text(json.dumps(requests, ensure_ascii=False))
    proc = subprocess.run(["node", "scripts/parity-run.ts", str(database), str(path)],
                          cwd=WORKER_DIR, capture_output=True, text=True)
    if proc.returncode:
        raise SystemExit(f"The Worker run failed:\n{proc.stderr[-3000:]}")
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
    parser.add_argument("--rec", type=Path, default=WORKER_DIR / ".snapshot.nosync/rec", help="the recording both sides read")
    parser.add_argument("--db", type=Path, help="a local D1 copy built from --rec (default: build one)")
    parser.add_argument("--cases", type=Path, default=CASES, help="the cases to send (default: test/parity-cases.json; "
                        "CI uses test/fixture-cases.json with the recording test/fixture_recording.py writes)")
    parser.add_argument("--show", action="store_true", help="print every case's statements and round trips")
    args = parser.parse_args(argv)

    cases = json.loads(args.cases.read_text())
    names = [case["name"] for case in cases]
    if len(set(names)) != len(names):
        raise SystemExit("Case names must be unique.")
    requests = [request(case) for case in cases]

    with tempfile.TemporaryDirectory(prefix="acquisition-gov-parity-") as scratch:
        database = args.db
        if database is None:
            database = Path(scratch) / "d1.sqlite"
            build_database(database, args.rec)
        worker = run_worker(requests, database, scratch)
        python = run_python(requests, args.rec)

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
