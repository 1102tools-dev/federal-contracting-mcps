"""Run parity/corpus.json against the gsa-perdiem-mcp Python server in hosted mode.

The package's real HTTP app (gsa_perdiem_mcp.http.create_app, as the
container ran it) is driven in process. The GSA Per Diem API is replaced by
the corpus fixtures through httpx.MockTransport, and today's date by the
scenario's date. Prints JSON: per scenario, each HTTP response and the
upstream requests made.

    cd servers/gsa-perdiem-mcp
    PYTHONPATH=src .venv/bin/python ../../deploy/gsa-perdiem/parity/python_side.py ../../deploy/gsa-perdiem/parity/corpus.json
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys

os.environ.update({
    "PERDIEM_HOSTED": "1",
    "MCP_RESPONSE_CACHE_SECONDS": "86400",
    "FEDERAL_API_MIN_INTERVAL_SECONDS": "0",
    "PERDIEM_API_KEY": "placeholder",
})

import httpx  # noqa: E402

from gsa_perdiem_mcp import http, server  # noqa: E402
from gsa_perdiem_mcp.constants import BASE_URL, DEFAULT_TIMEOUT, USER_AGENT  # noqa: E402

PREFIX = httpx.URL(BASE_URL).raw_path.decode() + "/"


async def run(corpus):
    app = http.create_app()
    starlette = app.app
    results = []
    async with starlette.router.lifespan_context(starlette):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
            for scenario in corpus["scenarios"]:
                results.append(await run_scenario(client, corpus, scenario))
    return results


async def run_scenario(client, corpus, scenario):
    key = scenario.get("key", corpus["key"])
    os.environ["PERDIEM_API_KEY"] = key
    today = datetime.date.fromisoformat(scenario["today"])

    class FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return today

    server._date = FixedDate
    server.HOURLY_UPSTREAM_CAP = scenario.get("hourly_cap", 950)
    server._response_cache.clear()
    server._upstream_starts.clear()
    fixtures = scenario.get("fixtures", {})
    upstream = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        assert path.startswith(PREFIX), path
        path = path[len(PREFIX):]
        upstream.append({"path": path, "key_header": request.headers.get("x-api-key") == key.strip(),
                         "user_agent": request.headers.get("user-agent")})
        fixture = fixtures.get(path)
        if fixture is None:
            return httpx.Response(404, text="no fixture for this path", headers={"content-type": "text/plain"})
        if fixture.get("error") == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if fixture.get("error") == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(fixture["status"], headers=fixture["headers"], content=fixture["body"].encode())

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=DEFAULT_TIMEOUT,
                             headers={"User-Agent": USER_AGENT})
    server._get_client = lambda: mock
    responses = []
    for body in scenario["requests"]:
        r = await client.post("/mcp", content=body.encode(), headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        responses.append({"status": r.status_code, "body": r.text})
    await mock.aclose()
    return {"name": scenario["name"], "responses": responses, "upstream": upstream}


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        corpus = json.load(f)
    print(json.dumps(asyncio.run(run(corpus)), ensure_ascii=False))


if __name__ == "__main__":
    main()
