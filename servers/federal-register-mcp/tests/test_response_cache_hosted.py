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


PUBLISHED = ["2026-10-09"]  # the newest issue date, changed by the daily-issue test


def answer(request):
    path = request.url.path
    if path.endswith("/documents.json") and request.url.params.get("order") == "newest" \
            and request.url.params.get("per_page") == "1":
        return {"count": 10000, "results": [{"publication_date": PUBLISHED[0]}]}
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
        enabled=True, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024, clock=clock))
    monkeypatch.setattr(server.time, "monotonic", clock)
    monkeypatch.setattr(server, "_version", (None, float("-inf")))
    monkeypatch.setattr(server, "_version_lock", None)
    PUBLISHED[0] = "2026-10-09"
    state = {"requests": [], "responses": [], "clock": clock}

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
    # Filed under the newest issue date, searches last until the next issue (at most a day).
    assert server._cache_seconds(f"{BASE_URL}/documents.json?conditions[term]=x", versioned=True) == DAY
    assert server._cache_seconds(f"{BASE_URL}/documents/facets/agency?conditions[term]=x", versioned=True) == DAY
    assert server._cache_seconds(f"{BASE_URL}/public-inspection-documents/current.json", versioned=True) == 10 * MINUTE


def test_a_hit_uses_no_pacing_and_no_budget(upstream):
    async def calls():
        first = await server.get_document("2026-03065")
        second = await server.get_document("2026-03065")
        third = await server.search_documents(term="acquisition")
        return first, second, third

    first, second, _ = asyncio.run(upstream["run"](calls))
    assert first == second
    # The newest issue date (read once, outside the cache), the document and the search.
    assert len(upstream["requests"]) == 3
    assert upstream["budget_starts"]() == 3
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
    # Uncached runs skip the issue-date read, so they repeat every request but that one.
    assert len(upstream["requests"]) == 2 * distinct - 1


def test_errors_and_rate_limits_are_not_cached(upstream):
    upstream["responses"] += [
        httpx.Response(500, text="boom"),
        httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"),
        httpx.Response(200, text="null"),
    ]
    url = f"{BASE_URL}/documents/2026-03065.json"
    server._version = ("2026-10-09", upstream["clock"].now)  # already read, so the queue feeds the document

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


def test_the_next_daily_issue_retires_cached_searches(upstream):
    async def search():
        return await server.search_documents(term="acquisition")

    asyncio.run(upstream["run"](search))
    asyncio.run(upstream["run"](search))
    assert len(upstream["requests"]) == 2  # issue date + search, then a hit
    PUBLISHED[0] = "2026-10-10"
    upstream["clock"].now += 16 * MINUTE  # past the 15-minute recheck of the issue date
    asyncio.run(upstream["run"](search))
    assert len(upstream["requests"]) == 4  # new issue date read, and the search asked again
    assert server._cache.stats()["hits"] == 1 and server._cache.stats()["misses"] == 2


def test_searches_under_one_issue_last_a_full_day(upstream):
    async def search():
        return await server.search_documents(term="acquisition")

    asyncio.run(upstream["run"](search))
    upstream["clock"].now += 23 * HOUR
    asyncio.run(upstream["run"](search))
    assert server._cache.stats()["hits"] == 1  # was 1 hour before the issue date was used
    upstream["clock"].now += 2 * HOUR
    asyncio.run(upstream["run"](search))
    assert server._cache.stats()["misses"] == 2


def test_an_unreadable_issue_date_falls_back_to_the_shorter_times(upstream):
    upstream["responses"].append(httpx.Response(500, text="boom"))  # the issue-date read fails

    async def search():
        return await server.search_documents(term="acquisition")

    first = asyncio.run(upstream["run"](search))
    assert first == asyncio.run(upstream["run"](search))
    assert len(upstream["requests"]) == 2  # failed date read + search; the retry waits a minute
    upstream["clock"].now += 2 * HOUR  # past the 1-hour search time, so asked again
    asyncio.run(upstream["run"](search))
    assert server._cache.stats()["misses"] == 2

