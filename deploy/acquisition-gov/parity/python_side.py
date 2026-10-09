"""Answer parity cases with the published Python server, offline, from a recording.

Runs the package's hosted HTTP app (acquisition_gov_mcp.http.create_app, the
code the container served) in-process. Its upstream fetch is replaced by the
recording that scripts/load_acquisition_gov.py --record made, so it sees the
same responses the D1 snapshot was built from, and _now() reports the fetch
time of the last response it read (what retrieved_at reports in a live call
made right after that fetch).

    python deploy/acquisition-gov/parity/python_side.py REC_DIR cases.json > python.jsonl
"""
from __future__ import annotations

import asyncio, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "servers/acquisition-gov-mcp/src"
sys.path.insert(0, str(SRC))
# The package parses in child processes; they must import the same source.
os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), os.environ.get("PYTHONPATH")]))

import httpx  # noqa: E402
from acquisition_gov_mcp import http, server  # noqa: E402


class Replay:
    def __init__(self, path: Path):
        self.path = path
        self.entries = json.loads((path / "manifest.json").read_text())
        self.now = "1970-01-01T00:00:00+00:00"
        self.fetches: list[str] = []

    async def fetch_bytes(self, url, *, allowed_types, max_bytes):
        entry = self.entries.get(f"{url} {allowed_types[0]}")
        if entry is None:
            raise RuntimeError(f"PARITY: {url} is not in the recording")
        self.fetches.append(url)
        self.now = entry["fetched_at"]
        if "error" in entry:
            raise RuntimeError(entry["error"])
        return (self.path / "bodies" / entry["sha256"]).read_bytes(), entry["content_type"], entry["final_url"]


async def run(cases: list[dict], replay: Replay):
    server._fetch_bytes = replay.fetch_bytes
    server._now = lambda: replay.now
    app = http.create_app()
    transport = httpx.ASGITransport(app=app)
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-11-25"}
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8080", timeout=120) as client:
        for i, case in enumerate(cases):
            message = {"jsonrpc": "2.0", "id": i + 1, "method": case["method"]}
            if "params" in case:
                message["params"] = case["params"]
            if case.get("notification"):
                del message["id"]
            replay.fetches = []
            response = await client.post("/mcp", content=json.dumps(message), headers=headers)
            yield {"case": i, "status": response.status_code, "body": response.text, "fetches": replay.fetches}


async def main():
    replay = Replay(Path(sys.argv[1]))
    cases = json.loads(Path(sys.argv[2]).read_text())
    async for row in run(cases, replay):
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
