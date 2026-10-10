"""Hosted response cache: hits skip pacing and budget, errors are never stored."""
import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from usaspending_gov_mcp import server
from usaspending_gov_mcp._response_cache import DAY, HOUR, MINUTE, ResponseCache
from usaspending_gov_mcp._throughput import USASpendingPacer
from usaspending_gov_mcp.constants import BASE_URL
from usaspending_gov_mcp.http import create_app

AWARDS = {"results": [{"Award ID": "W91QUZ06D0010", "Recipient Name": "ACME", "Award Amount": 1250000.5,
                       "generated_internal_id": "CONT_IDV_W91QUZ06D0010_9700"}],
          "page_metadata": {"page": 1, "hasNext": False}}


LOAD_DATE = ["10/08/2026"]  # USAspending's last load date, changed by the nightly-load test


def answer(request):
    path = request.url.path
    if path == "/api/v2/recipient/state/":
        return httpx.Response(200, json=[{"fips": "51", "code": "VA", "name": "Virginia"}])
    if path.startswith("/api/v2/recipient/children/"):
        return httpx.Response(200, json=[{"recipient_id": "abc-C", "name": "ACME CHILD"}])
    if path == "/api/v2/awards/last_updated/":
        return httpx.Response(200, json={"last_updated": LOAD_DATE[0]})
    if path.startswith("/api/v2/references/"):
        return httpx.Response(200, json={"results": [{"code": "A", "name": "BPA Call"}]})
    return httpx.Response(200, json=AWARDS)


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    """Real pacer and budget file, fake clock, recorded USAspending answers."""
    clock = FakeClock()
    monkeypatch.setattr(server, "_pacer", USASpendingPacer(
        environment={"FEDERAL_API_MIN_INTERVAL_SECONDS": "0.6"},
        pacing_dir=tmp_path, clock=clock, sleep=clock.sleep))
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=True, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024, clock=clock))
    monkeypatch.setattr(server.time, "monotonic", clock)
    monkeypatch.setattr(server, "_version", (None, float("-inf")))
    monkeypatch.setattr(server, "_version_lock", None)
    LOAD_DATE[0] = "10/08/2026"
    state = {"requests": [], "responses": [], "clock": clock}

    def handler(request):
        state["requests"].append((request.method, str(request.url), request.content))
        if state["responses"]:
            return state["responses"].pop(0)
        return answer(request)

    async def run(coro_factory):
        server._client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
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
    assert server._cache_seconds("/api/v2/references/award_types/") == DAY
    assert server._cache_seconds("/api/v2/references/filter_tree/psc/Product/") == DAY
    assert server._cache_seconds("/api/v2/autocomplete/naics/") == DAY
    assert server._cache_seconds("/api/v2/recipient/state/") == DAY
    assert server._cache_seconds("/api/v2/awards/last_updated/") == 15 * MINUTE
    assert server._cache_seconds("/api/v2/search/spending_by_award/") == HOUR
    assert server._cache_seconds("/api/v2/search/spending_by_award_count/") == HOUR
    assert server._cache_seconds("/api/v2/awards/count/transaction/CONT_AWD_X/") == HOUR
    assert server._cache_seconds("/api/v2/subawards/") == HOUR
    assert server._cache_seconds("/api/v2/recipient/") == HOUR
    assert server._cache_seconds("/api/v2/federal_accounts/") == HOUR
    assert server._cache_seconds("/api/v2/awards/CONT_AWD_X/") == 6 * HOUR
    assert server._cache_seconds("/api/v2/recipient/state/51/") == 6 * HOUR
    assert server._cache_seconds("/api/v2/recipient/abc-C/") == 6 * HOUR
    assert server._cache_seconds("/api/v2/federal_accounts/012-3456/") == 6 * HOUR
    assert server._cache_seconds("/api/v2/agency/097/") == 6 * HOUR
    # Filed under USAspending's load date, answers last a full day.
    assert server._cache_seconds("/api/v2/search/spending_by_award/", versioned=True) == DAY
    assert server._cache_seconds("/api/v2/awards/CONT_AWD_X/", versioned=True) == DAY
    assert server._cache_seconds("/api/v2/awards/last_updated/", versioned=True) == 15 * MINUTE


def test_a_hit_uses_no_pacing_and_no_budget(upstream):
    async def calls():
        first = await server.search_awards(keywords=["cybersecurity"])
        second = await server.search_awards(keywords=["cybersecurity"])
        third = await server.search_awards(keywords=["janitorial"])
        return first, second, third

    first, second, _ = asyncio.run(upstream["run"](calls))
    assert first == second
    # The load date (read once, outside the cache) plus the two different searches.
    assert len(upstream["requests"]) == 3
    assert upstream["budget_starts"]() == 3
    assert server._cache.stats()["hits"] == 1 and server._cache.stats()["misses"] == 2


def test_post_bodies_are_part_of_the_key(upstream):
    async def calls():
        await server._post("/api/v2/search/spending_by_award/", {"filters": {"keywords": ["a"]}, "limit": 5})
        await server._post("/api/v2/search/spending_by_award/", {"limit": 5, "filters": {"keywords": ["a"]}})
        await server._post("/api/v2/search/spending_by_award/", {"filters": {"keywords": ["b"]}, "limit": 5})

    asyncio.run(upstream["run"](calls))
    assert len(upstream["requests"]) == 3  # the load date plus two different bodies


def test_cached_answers_match_uncached_answers(upstream, monkeypatch):
    cases = [
        ("search_awards", {"keywords": ["cybersecurity"]}),
        ("get_award_count", {"keywords": ["cybersecurity"]}),
        ("get_award_detail", {"generated_award_id": "CONT_IDV_W91QUZ06D0010_9700"}),
        ("list_states", {}),
        ("get_recipient_children", {"uei_or_duns": "CWM4UN76ZQW8"}),
        ("awards_last_updated", {}),
        ("get_award_types_reference", {}),
    ]

    async def every_tool():
        out = []
        for name, args in cases:
            try:
                out.append(await getattr(server, name)(**args))
            except Exception as e:  # errors must match too
                out.append(f"{type(e).__name__}: {e}")
        return out

    cached_miss = asyncio.run(upstream["run"](every_tool))
    after_first = len(upstream["requests"])
    cached_hit = asyncio.run(upstream["run"](every_tool))
    assert len(upstream["requests"]) == after_first
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=False, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    uncached = asyncio.run(upstream["run"](every_tool))
    assert cached_miss == cached_hit == uncached


def test_errors_and_rate_limits_are_not_cached(upstream):
    upstream["responses"] += [
        httpx.Response(500, text="boom"),
        httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"),
        httpx.Response(200, text="null"),
    ]

    async def calls():
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await server._get("/api/v2/awards/last_updated/")
        return await server._get("/api/v2/awards/last_updated/")

    assert asyncio.run(upstream["run"](calls)) == {"last_updated": "10/08/2026"}
    assert len(upstream["requests"]) == 4
    assert server._cache.stats()["entries"] == 1


def test_health_reports_cache_counts():
    with TestClient(create_app()) as client:
        cache = client.get("/health").json()["cache"]
    assert set(cache) == {"hits", "misses", "entries", "bytes"}
    assert all(isinstance(value, int) for value in cache.values())


def test_the_nightly_load_retires_cached_answers(upstream):
    async def search():
        return await server.search_awards(keywords=["cybersecurity"])

    asyncio.run(upstream["run"](search))
    asyncio.run(upstream["run"](search))
    assert len(upstream["requests"]) == 2  # load date + search, then a hit
    LOAD_DATE[0] = "10/09/2026"
    upstream["clock"].now += 16 * MINUTE  # past the 15-minute recheck of the load date
    asyncio.run(upstream["run"](search))
    assert len(upstream["requests"]) == 4  # new load date read, and the search asked again
    assert server._cache.stats()["hits"] == 1 and server._cache.stats()["misses"] == 2


def test_answers_under_one_load_date_last_a_full_day(upstream):
    async def detail():
        return await server.get_award_detail(generated_award_id="CONT_IDV_W91QUZ06D0010_9700")

    asyncio.run(upstream["run"](detail))
    upstream["clock"].now += 23 * HOUR
    asyncio.run(upstream["run"](detail))
    assert server._cache.stats()["hits"] == 1  # was 6 hours before the load date was used
    upstream["clock"].now += 2 * HOUR
    asyncio.run(upstream["run"](detail))
    assert server._cache.stats()["misses"] == 2


def test_an_unreadable_load_date_falls_back_to_the_shorter_times(upstream):
    upstream["responses"].append(httpx.Response(500, text="boom"))  # the load-date read fails

    async def search():
        return await server.search_awards(keywords=["cybersecurity"])

    first = asyncio.run(upstream["run"](search))
    assert first == asyncio.run(upstream["run"](search))
    assert len(upstream["requests"]) == 2  # failed date read + search; the retry waits a minute
    upstream["clock"].now += 2 * HOUR  # past the 1-hour search time, so asked again
    asyncio.run(upstream["run"](search))
    assert server._cache.stats()["misses"] == 2

