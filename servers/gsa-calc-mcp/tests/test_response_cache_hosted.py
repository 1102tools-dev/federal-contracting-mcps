"""Hosted response cache: hits skip pacing and budget, errors are never stored."""
import asyncio
import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from gsa_calc_mcp import server
from gsa_calc_mcp._response_cache import ResponseCache
from gsa_calc_mcp._throughput import GsaCalcPacer
from gsa_calc_mcp.http import create_app

BODY = {
    "hits": {"total": {"value": 1, "relation": "eq"}, "hits": [{"_source": {
        "labor_category": "Engineer II", "vendor_name": "Acme", "current_price": 101.5,
    }}]},
    "aggregations": {"wage_stats": {"count": 1, "min": 101.5, "max": 101.5, "avg": 101.5}},
}


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    """Real pacer and budget file, fake clock, recorded GSA answers."""
    clock = FakeClock()
    pacer = GsaCalcPacer(
        environment={"FEDERAL_API_MIN_INTERVAL_SECONDS": "0.6"},
        pacing_dir=tmp_path, clock=clock, sleep=clock.sleep,
    )
    monkeypatch.setattr(server, "_pacer", pacer)
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=True, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    state = {"requests": [], "responses": []}

    def handler(request):
        state["requests"].append(str(request.url))
        if state["responses"]:
            return state["responses"].pop(0)
        return httpx.Response(200, json=BODY)

    async def run(coro_factory):
        server._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await coro_factory()
        finally:
            await server._client.aclose()
            server._client = None

    def budget_starts():
        files = list(tmp_path.glob("*.json"))
        return len(json.loads(files[0].read_text())["starts"]) if files else 0

    state["run"] = run
    state["budget_starts"] = budget_starts
    return state


def test_cache_is_off_unless_hosted_turns_it_on():
    assert server._cache.enabled is False


def test_a_hit_uses_no_pacing_and_no_budget(upstream):
    async def calls():
        first = await server.keyword_search(keyword="engineer")
        second = await server.keyword_search(keyword="engineer")
        third = await server.keyword_search(keyword="analyst")
        return first, second, third

    first, second, third = asyncio.run(upstream["run"](calls))
    assert first == second
    assert len(upstream["requests"]) == 2
    assert upstream["budget_starts"]() == 2
    assert server._cache.stats()["hits"] == 1 and server._cache.stats()["misses"] == 2


def test_cached_answers_match_uncached_answers(upstream, monkeypatch):
    cases = [
        ("keyword_search", {"keyword": "engineer"}),
        ("exact_search", {"field": "labor_category", "value": "Engineer II"}),
        ("suggest_contains", {"field": "labor_category", "term": "engineer"}),
        ("filtered_browse", {"education_level": "BA"}),
        ("igce_benchmark", {"labor_category": "engineer"}),
        ("price_reasonableness_check", {"labor_category": "engineer", "proposed_rate": 120}),
        ("vendor_rate_card", {"vendor_name": "Acme"}),
        ("sin_analysis", {"sin_code": "541330ENG"}),
    ]

    async def every_tool():
        return [await getattr(server, name)(**args) for name, args in cases]

    cached_miss = asyncio.run(upstream["run"](every_tool))
    # Some tools ask GSA the same question, so even the first pass shares calls.
    distinct = len(set(upstream["requests"]))
    assert len(upstream["requests"]) == distinct
    cached_hit = asyncio.run(upstream["run"](every_tool))
    assert len(upstream["requests"]) == distinct
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=False, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    uncached = asyncio.run(upstream["run"](every_tool))
    assert cached_miss == cached_hit == uncached
    assert len(upstream["requests"]) == distinct + len(cases)


def test_errors_and_rate_limits_are_not_cached(upstream):
    upstream["responses"] += [
        httpx.Response(500, text="boom"),
        httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"),
        httpx.Response(200, text="<html>maintenance</html>"),
    ]

    async def calls():
        with pytest.raises(RuntimeError):
            await server._get("keyword=engineer")
        with pytest.raises(ToolError):
            await server._get("keyword=engineer")
        with pytest.raises(RuntimeError, match="non-JSON"):
            await server._get("keyword=engineer")
        return await server._get("keyword=engineer")

    assert asyncio.run(upstream["run"](calls)) == BODY
    assert len(upstream["requests"]) == 4
    assert server._cache.stats()["entries"] == 1


def test_health_reports_cache_counts():
    with TestClient(create_app()) as client:
        cache = client.get("/health").json()["cache"]
    assert set(cache) == {"hits", "misses", "entries", "bytes"}
    assert all(isinstance(value, int) for value in cache.values())
