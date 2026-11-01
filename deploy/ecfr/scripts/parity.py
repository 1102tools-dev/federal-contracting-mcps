"""Parity check: the hybrid eCFR Worker against the Python ecfr-mcp server.

Sends every case in test/parity-cases.json to both and compares the HTTP
status and the raw response body byte for byte (tool results carry
content[0].text, structuredContent and isError, so this covers all three).

- Python: ecfr_mcp.http.create_app() (the app the container runs), served on
  localhost, with its eCFR client answered by a recording and its pacers off.
  titles.json and agencies.json come from the loader's recording (--base,
  whose date is the copy's date); every other eCFR request a case makes is
  recorded once from www.ecfr.gov into --rec (with --record: one XML request
  at a time, 3 s after the previous one ends; JSON 0.6 s apart) and replayed.
- Worker: src/worker.ts over a SQLite copy of D1 that scripts/load_ecfr.py
  builds (--db). What it forwards goes to the same Python server, so a
  forwarded case matches by construction; each case reports whether D1
  answered it or it was forwarded.

Run from the repository root with the package's Python (3.12):

    servers/ecfr-mcp/.venv/bin/python deploy/ecfr/scripts/parity.py \\
        --db deploy/ecfr/.snapshot.nosync/ecfr-48.sqlite [--record] [--show]

--random N adds N get_cfr_content calls for random sections of the copy
(--seed picks them), recorded like any other case.

Exits 1 on any difference not listed in DOCUMENTED.
"""
import argparse, asyncio, difflib, hashlib, json, os, random, socket, sqlite3, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_DIR = ROOT / "deploy/ecfr"
SRC = ROOT / "servers/ecfr-mcp/src"
CASES = WORKER_DIR / "test/parity-cases.json"
SNAPSHOT = WORKER_DIR / ".snapshot.nosync"
HEADERS = {"host": "localhost:8080", "accept": "application/json, text/event-stream",
           "content-type": "application/json"}
LIVE = "https://www.ecfr.gov"
XML_GAP, JSON_GAP = 3.0, 0.6

# Cases whose answers differ on purpose: the reason, and a check (given both
# {status, body} answers) that the difference is only that. Keep this short.
TOOLS_LIST = (
    "The Worker returns tools-contract.json sorted by name (keys sorted, as "
    "scripts/check_hosted_contract.py writes it); Python lists tools in registration order. "
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


def random_cases(database, count, seed):
    """get_cfr_content for `count` random sections of the copy, across its titles."""
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    rows = db.execute("SELECT title, identifier FROM nodes WHERE type = 'section' AND identifier IS NOT NULL "
                      "AND (content IS NOT NULL OR chunks > 0) ORDER BY title, key").fetchall()
    picked = random.Random(seed).sample(rows, min(count, len(rows)))
    return [{"name": f"random: {title} CFR {ident}", "tool": "get_cfr_content",
             "arguments": {"title_number": title, "section": ident}} for title, ident in picked]


class Recording:
    """eCFR answers by request path + query: the base recording's titles and
    agencies, then everything else in `rec` (recorded live on a miss with --record)."""

    def __init__(self, base, rec, record):
        self.base, self.rec, self.record = Path(base), Path(rec), record
        self.rec.mkdir(parents=True, exist_ok=True)
        (self.rec / "bodies").mkdir(exist_ok=True)
        self.manifest = self.rec / "manifest.jsonl"
        self.entries = {}
        if self.manifest.exists():
            for line in self.manifest.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.entries[entry["key"]] = entry
        self.missing = []
        self.fetched = 0
        self.last_xml_end = 0.0
        self.last_json_start = 0.0
        self.lock = threading.Lock()

    def answer(self, key, user_agent):
        """(status, content type, body) for one eCFR GET."""
        path = key.split("?", 1)[0]
        if path == "/api/versioner/v1/titles.json":
            return 200, "application/json; charset=utf-8", (self.base / "titles.json").read_bytes()
        if path == "/api/admin/v1/agencies.json":
            return 200, "application/json; charset=utf-8", (self.base / "agencies.json").read_bytes()
        entry = self.entries.get(key)
        if entry is None:
            if not self.record:
                self.missing.append(key)
                return 599, "text/plain", b"not in the parity recording"
            entry = self.fetch(key, user_agent)
        return entry["status"], entry["content_type"], (self.rec / "bodies" / entry["sha256"]).read_bytes()

    def fetch(self, key, user_agent):
        import httpx
        xml = "/full/" in key.split("?", 1)[0]
        with self.lock:
            for attempt in range(1, 6):
                wait = (self.last_xml_end + XML_GAP if xml else self.last_json_start + JSON_GAP) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last_json_start = time.monotonic()
                try:
                    r = httpx.get(LIVE + key, headers={"User-Agent": user_agent}, timeout=120)
                except httpx.HTTPError as exc:
                    status, error = None, exc
                else:
                    status, error = r.status_code, None
                finally:
                    if xml:
                        self.last_xml_end = time.monotonic()
                if status == 403:
                    raise SystemExit(f"403 from eCFR on {key}; stopping")
                if status is not None and status < 500 and status != 429:
                    break
                print(f"  {key}: {status or error}; retry {attempt}", file=sys.stderr, flush=True)
                time.sleep(60 * attempt if status == 429 else 10 * attempt)
            else:
                raise SystemExit(f"{key} kept failing")
            sha = hashlib.sha256(r.content).hexdigest()
            (self.rec / "bodies" / sha).write_bytes(r.content)
            entry = {"key": key, "status": r.status_code, "content_type": r.headers.get("content-type", ""),
                     "sha256": sha, "bytes": len(r.content), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            with self.manifest.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
            self.entries[key] = entry
            self.fetched += 1
            print(f"  recorded {r.status_code} {len(r.content):,} B {key[:140]}", file=sys.stderr, flush=True)
            return entry


def start_python(recording, record):
    """The Python server on a free localhost port, answered by the recording; returns its base URL."""
    sys.path.insert(0, str(SRC))
    import logging
    import httpx
    import uvicorn
    logging.disable(logging.CRITICAL)  # the SDK and httpx log every request
    from ecfr_mcp import http, server

    class Replay(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            key = req.url.raw_path.decode()
            status, content_type, body = await asyncio.to_thread(recording.answer, key, req.headers.get("user-agent", ""))
            return httpx.Response(status, headers={"content-type": content_type}, content=body, request=req)

    server._client = httpx.AsyncClient(base_url=server.BASE_URL, headers={"User-Agent": server.USER_AGENT}, transport=Replay())
    server._pacer.configured_interval = lambda: 0
    server._xml_pacer.configured_interval = lambda: 0
    app = http.create_app()
    if record:
        app.request_timeout = 3600  # recording waits on eCFR's pace
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", access_log=False)
    uv = uvicorn.Server(config)
    threading.Thread(target=uv.run, daemon=True).start()
    while not uv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


def run_python(requests, base):
    import httpx
    out = {}
    with httpx.Client(timeout=3600) as client:
        for item in requests:
            response = client.post(base + "/mcp", headers=item["headers"], content=item["body"].encode())
            out[item["name"]] = {"status": response.status_code, "body": response.text}
    return out


def run_worker(requests, database, scratch, forward, cache=False):
    path = Path(scratch) / "requests.json"
    path.write_text(json.dumps(requests, ensure_ascii=False))
    proc = subprocess.run(["node", "scripts/parity-run.ts", str(database), str(path), forward],
                          cwd=WORKER_DIR, capture_output=True, text=True, env={**os.environ, "PARITY_CACHE": "1" if cache else "0"})
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
    parser.add_argument("--db", type=Path, default=SNAPSHOT / "ecfr-48.sqlite", help="the local D1 copy the Worker reads")
    parser.add_argument("--base", type=Path, default=SNAPSHOT / "rec-2026-10-29", help="the loader's recording (titles.json, agencies.json)")
    parser.add_argument("--rec", type=Path, default=SNAPSHOT / "parity-rec", help="every other eCFR answer the cases need")
    parser.add_argument("--record", action="store_true", help="fetch what --rec lacks from www.ecfr.gov (paced)")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--random", type=int, default=0, help="add N random sections of the copy")
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--only", help="run only cases whose name contains this text")
    parser.add_argument("--python-only", action="store_true", help="just run (and record) the Python side")
    parser.add_argument("--cache", action="store_true", help="give the Worker an answer cache: send each case twice and "
                        "compare the second (cached) answer; any change between the two is unexpected")
    parser.add_argument("--show", action="store_true", help="print every case's backend, statements and round trips")
    args = parser.parse_args(argv)

    cases = json.loads(args.cases.read_text())
    if args.random:
        cases += random_cases(args.db, args.random, args.seed)
    if args.only:
        cases = [case for case in cases if args.only in case["name"]]
    names = [case["name"] for case in cases]
    if len(set(names)) != len(names):
        raise SystemExit("Case names must be unique.")
    requests = [request(case) for case in cases]

    recording = Recording(args.base, args.rec, args.record)
    base = start_python(recording, args.record)
    python = run_python(requests, base)
    if args.python_only:
        print(f"{len(names)} cases sent to Python; {recording.fetched} answers recorded; {len(recording.missing)} missing.")
        return 0
    with tempfile.TemporaryDirectory(prefix="ecfr-parity-") as scratch:
        worker = run_worker(requests, args.db, scratch, base, args.cache)
    if recording.missing:
        print(f"The recording lacks {len(set(recording.missing))} answers (run with --record):")
        for key in sorted(set(recording.missing))[:20]:
            print(f"  {key}")

    unexpected = documented = 0
    counts = {"d1": 0, "forwarded": 0, "hits": 0}
    for name in names:
        py, ts = python[name], worker[name]
        backend = "d1" if ts["backend"] == "d1" else "forwarded"
        counts[backend] += 1
        counts["hits"] += ts.get("cache") == "hit"
        if ts.get("changed"):
            unexpected += 1
            print(f"CACHE CHANGED THE ANSWER {name}")
        if args.show:
            print(f"{backend:9} {ts['statements']:2} statements {ts['round_trips']} trips  {name}")
        if (py["status"], py["body"]) == (ts["status"], ts["body"]):
            continue
        if name in DOCUMENTED and DOCUMENTED[name][1](py, ts):
            documented += 1
            print(f"DOCUMENTED {name}: {DOCUMENTED[name][0]}")
            continue
        unexpected += 1
        print(f"DIFF {name} ({backend}): status python={py['status']} worker={ts['status']}")
        sys.stdout.writelines(line + "\n" for line in difflib.unified_diff(
            pretty(py["body"]), pretty(ts["body"]), "python", "worker", lineterm="", n=2))
    print(f"{len(names)} cases: {len(names) - unexpected - documented} identical, "
          f"{documented} documented differences, {unexpected} unexpected differences; "
          f"{counts['d1']} answered from D1, {counts['forwarded']} forwarded"
          + (f"; {counts['hits']} second answers came from the cache." if args.cache else "."))
    return 1 if unexpected or recording.missing else 0


if __name__ == "__main__":
    sys.exit(main())
