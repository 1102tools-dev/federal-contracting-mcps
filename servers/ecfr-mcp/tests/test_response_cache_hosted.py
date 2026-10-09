"""Hosted response cache: hits skip pacing and budget, errors are never stored."""
import asyncio
import json
from datetime import date, timedelta

import httpx
import pytest
from starlette.testclient import TestClient

from ecfr_mcp import server
from ecfr_mcp._response_cache import DAY, HOUR, MINUTE, ResponseCache
from ecfr_mcp._throughput import EcfrPacer, EcfrXmlPacer
from ecfr_mcp._xml_cache import XmlCache
from ecfr_mcp.http import create_app

LATEST = "2026-10-06"
XML = ('<DIV8 N="15.305" TYPE="SECTION"><HEAD>15.305 Proposal evaluation.</HEAD>'
       '<P>(a) Proposal evaluation is an assessment of the proposal.</P></DIV8>')


def answer(request):
    path = request.url.path
    if path.endswith("/titles.json"):
        return httpx.Response(200, json={"titles": [{"number": 48, "name": "FAR", "up_to_date_as_of": LATEST,
                                                     "latest_amended_on": LATEST, "reserved": False}]})
    if path.endswith(".xml"):
        return httpx.Response(200, text=XML)
    if "/structure/" in path:
        return httpx.Response(200, json={"type": "part", "identifier": "15", "children": [
            {"type": "section", "identifier": "15.305", "label": "15.305 Proposal evaluation.", "children": []}]})
    return httpx.Response(200, json={"results": [], "meta": {"total_count": 0}})


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    """Real pacers and budget file, fake clock, recorded eCFR answers."""
    clock = FakeClock()
    env = {"FEDERAL_API_MIN_INTERVAL_SECONDS": "0.6"}
    monkeypatch.setattr(server, "_pacer", EcfrPacer(
        environment=env, pacing_dir=tmp_path / "json", clock=clock, sleep=clock.sleep))
    monkeypatch.setattr(server, "_xml_pacer", EcfrXmlPacer(
        environment=env, pacing_dir=tmp_path / "xml", clock=clock, sleep=clock.sleep))
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=True, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    monkeypatch.setattr(server, "_xml_cache", XmlCache(max_entries=64))
    state = {"requests": [], "responses": []}

    def handler(request):
        state["requests"].append(str(request.url))
        if state["responses"]:
            return state["responses"].pop(0)
        return answer(request)

    async def run(coro_factory):
        server._client = httpx.AsyncClient(base_url=server.BASE_URL, transport=httpx.MockTransport(handler))
        try:
            return await coro_factory()
        finally:
            await server._client.aclose()
            server._client = None

    def budget_starts():
        files = list((tmp_path / "json").glob("*.json"))
        return len(json.loads(files[0].read_text())["starts"]) if files else 0

    state["run"] = run
    state["budget_starts"] = budget_starts
    return state


def test_cache_is_off_unless_hosted_turns_it_on():
    assert server._cache.enabled is False
    assert XmlCache().ttl == 300  # local default unchanged


def test_cache_times_by_endpoint():
    old = "2020-01-01"
    recent = (date.today() - timedelta(days=2)).isoformat()
    assert server._cache_seconds(f"/api/versioner/v1/full/{old}/title-48.xml") == DAY
    assert server._cache_seconds(f"/api/versioner/v1/structure/{old}/title-48.json") == DAY
    assert server._cache_seconds(f"/api/versioner/v1/ancestry/{old}/title-48.json") == DAY
    assert server._cache_seconds(f"/api/versioner/v1/full/{recent}/title-48.xml") == 6 * HOUR
    assert server._cache_seconds("/api/versioner/v1/titles.json") == 15 * MINUTE
    assert server._cache_seconds("/api/admin/v1/agencies.json") == DAY
    assert server._cache_seconds("/api/search/v1/results") == HOUR
    assert server._cache_seconds("/api/versioner/v1/versions/title-48") == HOUR
    assert server._cache_seconds("/api/admin/v1/corrections.json") == HOUR


def test_a_hit_uses_no_pacing_and_no_budget(upstream):
    async def calls():
        first = await server.get_cfr_content(section="15.305")
        second = await server.get_cfr_content(section="15.305")
        return first, second

    first, second = asyncio.run(upstream["run"](calls))
    assert first == second
    # One titles.json (latest date) and one XML call; the repeat made none.
    assert len(upstream["requests"]) == 2
    assert upstream["budget_starts"]() == 2  # the XML call also takes a JSON-lane start
    assert server._cache_stats()["hits"] == 2 and server._cache_stats()["misses"] == 2


def test_cached_answers_match_uncached_answers(upstream, monkeypatch):
    cases = [
        ("get_latest_date", {}),
        ("get_cfr_content", {"section": "15.305"}),
        ("get_cfr_content", {"section": "15.305", "date": "2020-01-01"}),
        ("get_cfr_structure", {"part": "15"}),
        ("list_sections_in_part", {"part_number": "15"}),
        ("search_cfr", {"query": "proposal evaluation"}),
        ("lookup_far_clause", {"section_id": "15.305"}),
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
    distinct = len(set(upstream["requests"]))
    assert len(upstream["requests"]) == distinct
    cached_hit = asyncio.run(upstream["run"](every_tool))
    assert len(upstream["requests"]) == distinct
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=False, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    monkeypatch.setattr(server, "_xml_cache", XmlCache(max_entries=0))
    uncached = asyncio.run(upstream["run"](every_tool))
    assert cached_miss == cached_hit == uncached


def test_errors_and_rate_limits_are_not_cached(upstream):
    upstream["responses"] += [
        httpx.Response(500, text="boom"),
        httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"),
        httpx.Response(200, text="<html>maintenance</html>"),
    ]

    async def calls():
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await server._get_json("/api/versioner/v1/titles.json")
        return await server._get_json("/api/versioner/v1/titles.json")

    assert asyncio.run(upstream["run"](calls))["titles"][0]["up_to_date_as_of"] == LATEST
    assert len(upstream["requests"]) == 4
    assert server._cache.stats()["entries"] == 1


def test_health_reports_cache_counts():
    with TestClient(create_app()) as client:
        cache = client.get("/health").json()["cache"]
    assert set(cache) == {"hits", "misses", "entries", "bytes"}
    assert all(isinstance(value, int) for value in cache.values())
