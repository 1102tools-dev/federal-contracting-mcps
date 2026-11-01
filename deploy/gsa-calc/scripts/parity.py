"""Parity checks for the hosted GSA CALC+ Worker, all local and offline.

Two of the plan's three comparisons run here (the third, the emulator against
GSA's recorded answers, is scripts/compare-emulator.ts):

- tools (default): every case in test/parity-cases.json sent to the Worker
  (src/worker.ts over a local SQLite copy, --db) and to the Python server
  (gsa_calc_mcp.http.create_app(), the app the container runs), whose calls to
  GSA are answered by the same emulator (scripts/emulator-serve.ts over --db).
  Status and body must be byte-identical; `took` is fixed on both sides.
- verdicts (--verdicts): the Python server twice, once over a recording of
  GSA's real answers (--rec) and once over the emulator, counting changed
  price_reasonableness_check status / iqr_position / vs_median and changed
  igce_benchmark population_scope flags. The recording should be from the
  night the copy holds (checked against meta 'version').

Recording (--record, GitHub runners only: the Mac shares the home IP with the
production server): the Python server's GSA calls for every case go to GSA
live on a miss, one at a time 7.5 s apart, saved into --rec in
scripts/load_gsa_calc.py's format (manifest.jsonl + bodies/NNNNN.json.gz).
Add --python-only to record without a copy.

The Python server runs with FEDERAL_API_MIN_INTERVAL_SECONDS=0 and no response
cache; its pacer is bypassed (the recorder paces live calls itself). Run from
the repository root with the package's Python (3.12):

    uv run --frozen --python 3.12 --project servers/gsa-calc-mcp python \\
        deploy/gsa-calc/scripts/parity.py --db COPY.sqlite [--cache] [--only TEXT] [--show]
    ... parity.py --db COPY.sqlite --rec REC_DIR --verdicts [--json report.json]
    ... parity.py --rec REC_DIR --record --python-only        # on GitHub

Exits 1 on any tools difference not listed in DOCUMENTED, or on recording gaps.
"""
import argparse, asyncio, difflib, gzip, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_DIR = ROOT / "deploy/gsa-calc"
SRC = ROOT / "servers/gsa-calc-mcp/src"
CASES = WORKER_DIR / "test/parity-cases.json"
HEADERS = {"host": "localhost:8080", "accept": "application/json, text/event-stream",
           "content-type": "application/json"}
TOOK = 3  # the fixed `took` both sides' emulators write
GAP = 7.5  # seconds between live GSA calls when recording

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
    "invalid: lone surrogate in an argument": INVALID_MESSAGE,
    "invalid: lone low surrogate in an argument": INVALID_MESSAGE,
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
        try:
            body.encode()
        except UnicodeEncodeError:  # a lone surrogate stays a JSON escape
            body = json.dumps(message)
    for name, value in case.get("headers", {}).items():
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
    return {"name": case["name"], "body": body, "headers": headers}


# ---------- where the Python server's GSA calls go ----------

class Emulator:
    """scripts/emulator-serve.ts over the copy, with `took` fixed."""

    def __init__(self, database):
        self.proc = subprocess.Popen(["node", "scripts/emulator-serve.ts", str(database), "--took", str(TOOK)],
                                     cwd=WORKER_DIR, stdout=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline()
        if not line.startswith("listening "):
            raise SystemExit(f"emulator-serve did not start: {line!r}")
        self.base = f"http://127.0.0.1:{line.split()[1]}/"

    def answer(self, query):
        try:
            with urllib.request.urlopen(self.base + "?" + query, timeout=300) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def close(self):
        self.proc.terminate()


class Recording:
    """GSA's answers by query string, from a recording in load_gsa_calc.py's
    format; with record=True a miss is fetched from GSA live (paced) and saved."""

    def __init__(self, directory, record, gap=GAP):
        self.dir = Path(directory)
        self.record = record
        self.gap = gap
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "manifest.jsonl").touch()
        self.entries = {}
        for line in (self.dir / "manifest.jsonl").read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                self.entries[entry["query"]] = entry
        self.missing = []
        self.recorder = None
        self.lock = threading.Lock()
        self.indexes = set()

    def body(self, entry):
        return gzip.decompress((self.dir / "bodies" / f"{entry['n']:05d}.json.gz").read_bytes())

    def answer(self, query):
        with self.lock:
            entry = self.entries.get(query)
            if entry is None and self.record:
                entry = self.fetch(query)
            if entry is None:
                self.missing.append(query)
                return 599, b"not in the recording"
            if entry.get("index"):
                self.indexes.add(entry["index"])
            return entry["status"], self.body(entry)

    def fetch(self, query):
        sys.path.insert(0, str(ROOT / "scripts"))
        from load_gsa_calc import IndexChanged, Recorder
        if self.recorder is None:
            self.recorder = Recorder(self.dir, self.gap, 100_000)
        try:
            self.recorder.get(query, strict=False)
        except IndexChanged as error:
            print(f"WARNING: {error}; the recording now spans two nights", file=sys.stderr, flush=True)
            self.recorder.index = None
        lines = (self.dir / "manifest.jsonl").read_text().splitlines()
        entry = json.loads(lines[-1])
        self.entries[query] = entry
        print(f"  recorded {entry['status']} {query[:120]}", file=sys.stderr, flush=True)
        return entry


def start_python():
    """The Python server on a free localhost port; returns (base URL, a setter for where its GSA calls go)."""
    os.environ["FEDERAL_API_MIN_INTERVAL_SECONDS"] = "0"
    os.environ.pop("MCP_RESPONSE_CACHE", None)
    sys.path.insert(0, str(SRC))
    import logging
    import httpx
    import uvicorn
    logging.disable(logging.CRITICAL)  # the SDK and httpx log every request
    from gsa_calc_mcp import http, server

    source = {"current": None}
    server._cache.enabled = False

    async def fetch(url):
        # server._fetch without the pacer: the source answers (status, body bytes).
        query = url.split("?", 1)[1]
        status, content = await asyncio.to_thread(source["current"].answer, query)
        response = httpx.Response(status, content=content, request=httpx.Request("GET", url))
        response.raise_for_status()
        return response.content

    server._fetch = fetch
    app = http.create_app()
    app.request_timeout = 7200  # recording waits on GSA's pace
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", access_log=False))
    threading.Thread(target=uv.run, daemon=True).start()
    while not uv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", lambda s: source.__setitem__("current", s)


def run_python(requests, base):
    import httpx
    out = {}
    with httpx.Client(timeout=7200) as client:
        for item in requests:
            response = client.post(base + "/mcp", headers=item["headers"], content=item["body"].encode())
            out[item["name"]] = {"status": response.status_code, "body": response.text}
    return out


def run_worker(requests, database, scratch, forward, cache=False):
    path = Path(scratch) / "requests.json"
    path.write_text(json.dumps(requests, ensure_ascii=False))
    proc = subprocess.run(["node", "scripts/parity-run.ts", str(database), str(path), forward],
                          cwd=WORKER_DIR, capture_output=True, text=True,
                          env={**os.environ, "PARITY_CACHE": "1" if cache else "0", "PARITY_TOOK": str(TOOK)})
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


def compare_tools(names, python, worker, show, cache=False):
    unexpected = documented = 0
    counts = {"d1": 0, "forwarded": 0, "hits": 0}
    slow = []
    for name in names:
        py, ts = python[name], worker[name]
        backend = "d1" if ts["backend"] == "d1" else "forwarded"
        counts[backend] += 1
        counts["hits"] += ts.get("cache") == "hit"
        slow.append((ts.get("ms", 0), name))
        if ts.get("changed"):
            unexpected += 1
            print(f"CACHE CHANGED THE ANSWER {name}")
        if show:
            print(f"{backend:9} {ts['statements']:2} statements {ts['round_trips']} trips {ts.get('ms', 0):5} ms  {name}")
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
    slowest = ", ".join(f"{n} {ms} ms" for ms, n in sorted(slow, reverse=True)[:3])
    print(f"{len(names)} cases: {len(names) - unexpected - documented} identical, "
          f"{documented} documented differences, {unexpected} unexpected differences; "
          f"{counts['d1']} answered from D1, {counts['forwarded']} forwarded; slowest: {slowest}"
          + (f"; {counts['hits']} second answers came from the cache." if cache else "."))
    return unexpected


def structured(answer):
    try:
        return json.loads(answer["body"])["result"].get("structuredContent") or {}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {}


SCOPE_FLAGS = ["off_title_matches_detected", "title_list_complete", "title_only_population_verified",
               "exact_title_population_verified", "exact_title_rate_count"]


def compare_verdicts(cases, gsa, copy, report_path=None):
    """Changed verdicts between the Python server over GSA's answers and over the emulator."""
    rows = []
    totals = {"price checks": 0, "status": 0, "iqr_position": 0, "vs_median": 0, "igce": 0, "population_scope": 0}
    for case in cases:
        tool = case.get("tool")
        if tool not in ("price_reasonableness_check", "igce_benchmark"):
            continue
        a, b = structured(gsa[case["name"]]), structured(copy[case["name"]])
        changes = {}
        if tool == "price_reasonableness_check":
            totals["price checks"] += 1
            for key, get in [("status", lambda d: d.get("status", "VERDICT")),
                             ("iqr_position", lambda d: (d.get("analysis") or {}).get("iqr_position")),
                             ("vs_median", lambda d: (d.get("analysis") or {}).get("vs_median"))]:
                if get(a) != get(b):
                    changes[key] = [get(a), get(b)]
                    totals[key] += 1
        else:
            totals["igce"] += 1
        sa, sb = a.get("population_scope") or {}, b.get("population_scope") or {}
        flags = {f: [sa.get(f), sb.get(f)] for f in SCOPE_FLAGS if sa.get(f) != sb.get(f)}
        if flags:
            changes["population_scope"] = flags
            totals["population_scope"] += 1
        for key in ("total_rates", "avg_rate", "percentiles"):
            if a.get(key) != b.get(key):
                changes.setdefault("numbers", {})[key] = [a.get(key), b.get(key)]
        if changes:
            rows.append({"name": case["name"], "tool": tool, "changes": changes})
    for row in rows:
        verdict = {k: v for k, v in row["changes"].items() if k != "numbers"}
        if verdict:
            print(f"VERDICT CHANGED {row['name']}: {json.dumps(verdict)}")
    print("Verdicts (Python over GSA's recorded answers vs over the copy): "
          f"{totals['price checks']} price checks, {totals['status']} status, {totals['iqr_position']} iqr_position, "
          f"{totals['vs_median']} vs_median changed; {totals['igce']} igce_benchmark cases, "
          f"{totals['population_scope']} population_scope changes (both tools).")
    if report_path:
        Path(report_path).write_text(json.dumps({"totals": totals, "rows": rows}, indent=1) + "\n")
    return totals


def copy_version(database):
    import sqlite3
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    row = db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    return row[0] if row else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, help="the local D1 copy (SQLite) the Worker and the emulator read")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--rec", type=Path, help="a recording of GSA's answers (load_gsa_calc.py format)")
    parser.add_argument("--record", action="store_true", help="fetch what --rec lacks from GSA live, --gap apart (GitHub only)")
    parser.add_argument("--gap", type=float, default=GAP, help="seconds between live GSA calls when recording (default 7.5)")
    parser.add_argument("--python-only", action="store_true", help="only run (and record) the Python side over --rec")
    parser.add_argument("--verdicts", action="store_true", help="Python over --rec vs Python over the emulator")
    parser.add_argument("--json", help="write the verdict report here")
    parser.add_argument("--only", help="run only cases whose name contains this text")
    parser.add_argument("--cache", action="store_true", help="give the Worker an answer cache: send each case twice and "
                        "compare the second (cached) answer; any change between the two is unexpected")
    parser.add_argument("--show", action="store_true", help="print every case's backend, statements, round trips and time")
    args = parser.parse_args(argv)
    # The node helpers run in deploy/gsa-calc; paths given from anywhere must still resolve.
    args.db = args.db.resolve() if args.db else None
    args.rec = args.rec.resolve() if args.rec else None
    if args.record and os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("--record calls GSA live: run it on GitHub (gsa-calc-load.yml), never from the Mac.")
    if (args.python_only or args.verdicts) and not args.rec:
        raise SystemExit("--python-only and --verdicts need --rec.")
    if not args.python_only and not args.db:
        raise SystemExit("--db is required (the copy the Worker and the emulator read).")

    cases = json.loads(args.cases.read_text())
    if args.only:
        cases = [case for case in cases if args.only in case["name"]]
    names = [case["name"] for case in cases]
    if len(set(names)) != len(names):
        raise SystemExit("Case names must be unique.")
    requests = [request(case) for case in cases]
    base, use = start_python()

    recording = Recording(args.rec, args.record, args.gap) if args.rec else None
    if args.python_only:
        use(recording)
        run_python(requests, base)
        fetched = recording.recorder.calls if recording.recorder else 0
        print(f"{len(names)} cases sent to Python; {fetched} GSA calls recorded; {len(set(recording.missing))} missing; "
              f"indexes seen: {sorted(recording.indexes)}.")
        return 1 if recording.missing else 0

    emulator = Emulator(args.db)
    try:
        if args.verdicts:
            version = copy_version(args.db)
            use(recording)
            gsa = run_python(requests, base)
            if recording.indexes and recording.indexes != {version}:
                print(f"WARNING: the recording is from {sorted(recording.indexes)}, the copy is {version}")
            use(emulator)
            copy = run_python(requests, base)
            compare_verdicts(cases, gsa, copy, args.json)
            if recording.missing:
                print(f"The recording lacks {len(set(recording.missing))} answers (record them on GitHub).")
            return 1 if recording.missing else 0
        use(emulator)
        python = run_python(requests, base)
        with tempfile.TemporaryDirectory(prefix="gsa-calc-parity-") as scratch:
            worker = run_worker(requests, args.db, scratch, base, args.cache)
        return 1 if compare_tools(names, python, worker, args.show, args.cache) else 0
    finally:
        emulator.close()


if __name__ == "__main__":
    sys.exit(main())
