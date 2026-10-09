"""Hosted response cache: hits skip pacing and budget, errors are never stored."""
import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from federal_register_mcp import server
from federal_register_mcp._response_cache import DAY, HOUR, MINUTE, ResponseCache
from federal_register_mcp._throughput import FederalRegisterPacer
from federal_register_mcp.constants import BASE_URL
from federal_register_mcp.http import create_app

DOC = {"document_number": "2026-03065", "title": "Federal Acquisition Regulation", "type": "Rule",
       "comments_close_on": "2026-12-01", "agencies": [{"slug": "defense-department", "name": "DoD"}]}


def answer(request):
    path = request.url.path
    if path.endswith("/agencies.json"):
        return [{"id": 1, "name": "Defense Department", "slug": "defense-department"}]
    if path.endswith("/public-inspection-documents/current.json"):
        return {"count": 1, "results": [DOC]}
    if "/facets/" in path:
        return {"RULE": {"count": 3, "name": "Rule"}}
    if path.endswith("/documents.json"):
        return {"count": 1, "results": [DOC]}
    return DOC


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    """Real pacer and budget file, fake clock, recorded Federal Register answers."""
    clock = FakeClock()
    pacer = FederalRegisterPacer(
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
        return httpx.Response(200, json=answer(request))

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


def test_cache_times_by_endpoint():
    assert server._cache_seconds(f"{BASE_URL}/documents/2026-03065.json") == DAY
    assert server._cache_seconds(f"{BASE_URL}/documents/2026-03065,2026-03066.json") == DAY
    assert server._cache_seconds(f"{BASE_URL}/agencies.json") == DAY
    assert server._cache_seconds(f"{BASE_URL}/documents.json?conditions[term]=x") == HOUR
    assert server._cache_seconds(f"{BASE_URL}/documents/facets/agency?conditions[term]=x") == HOUR
    assert server._cache_seconds(f"{BASE_URL}/public-inspection-documents/current.json") == 10 * MINUTE


def test_a_hit_uses_no_pacing_and_no_budget(upstream):
    async def calls():
        first = await server.get_document("2026-03065")
        second = await server.get_document("2026-03065")
        third = await server.search_documents(term="acquisition")
        return first, second, third

    first, second, _ = asyncio.run(upstream["run"](calls))
    assert first == second
    assert len(upstream["requests"]) == 2
    assert upstream["budget_starts"]() == 2
    assert server._cache.stats()["hits"] == 1 and server._cache.stats()["misses"] == 2


def test_cached_answers_match_uncached_answers(upstream, monkeypatch):
    cases = [
        ("search_documents", {"term": "acquisition"}),
        ("get_document", {"document_number": "2026-03065"}),
        ("get_documents_batch", {"document_numbers": ["2026-03065", "2026-03066"]}),
        ("get_facet_counts", {"facet": "type", "term": "acquisition"}),
        ("get_public_inspection", {"keyword_filter": "acquisition"}),
        ("list_agencies", {"query": "defense"}),
        ("open_comment_periods", {"agencies": ["defense-department"]}),
        ("far_case_history", {"docket_id": "FAR Case 2023-008"}),
    ]

    async def every_tool():
        return [await getattr(server, name)(**args) for name, args in cases]

    cached_miss = asyncio.run(upstream["run"](every_tool))
    distinct = len(set(upstream["requests"]))
    assert len(upstream["requests"]) == distinct
    cached_hit = asyncio.run(upstream["run"](every_tool))
    assert len(upstream["requests"]) == distinct
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=False, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    uncached = asyncio.run(upstream["run"](every_tool))
    assert cached_miss == cached_hit == uncached
    assert len(upstream["requests"]) == 2 * distinct


def test_errors_and_rate_limits_are_not_cached(upstream):
    upstream["responses"] += [
        httpx.Response(500, text="boom"),
        httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"),
        httpx.Response(200, text="null"),
    ]
    url = f"{BASE_URL}/documents/2026-03065.json"

    async def calls():
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await server._get(url)
        return await server._get(url)

    assert asyncio.run(upstream["run"](calls)) == DOC
    assert len(upstream["requests"]) == 4
    assert server._cache.stats()["entries"] == 1


def test_health_reports_cache_counts():
    with TestClient(create_app()) as client:
        cache = client.get("/health").json()["cache"]
    assert set(cache) == {"hits", "misses", "entries", "bytes"}
    assert all(isinstance(value, int) for value in cache.values())
