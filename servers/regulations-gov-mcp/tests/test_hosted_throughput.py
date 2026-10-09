"""Registered-key spacing, the hourly upstream cap, and the opt-in response cache."""
import asyncio

import httpx
import pytest

from regulationsgov_mcp import server
from mcp.server.mcpserver.exceptions import ToolError
from regulationsgov_mcp._response_cache import HOUR, MINUTE, ResponseCache


def test_registered_key_bursts():
    assert server._pacer("registered-key").default_interval == server.REGISTERED_KEY_INTERVAL == 0.6


def test_hourly_cap_stops_before_the_provider_limit(monkeypatch):
    monkeypatch.setattr(server, "HOURLY_UPSTREAM_CAP", 3)
    monkeypatch.setattr(server, "_upstream_starts", server.collections.deque())
    for _ in range(3):
        server._reserve_hourly_upstream()
    with pytest.raises(ToolError, match="hourly .* request budget"):
        server._reserve_hourly_upstream()


def test_cache_is_off_unless_the_deployment_opts_in():
    assert server._cache.enabled is False


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    """Registered key, cache on, recorded Regulations.gov answers."""
    monkeypatch.setenv("REGULATIONS_GOV_API_KEY", "registered-key")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_cache", ResponseCache(
        enabled=True, max_bytes=1024 * 1024, max_entry_bytes=256 * 1024))
    monkeypatch.setattr(server, "_upstream_starts", server.collections.deque())
    calls, responses = [], []

    def handler(request):
        calls.append(str(request.url))
        if responses:
            return responses.pop(0)
        # The provider echoing the key must never reach the cache.
        return httpx.Response(200, json={"data": [{"id": "FAR-2023-0008", "note": "registered-key"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "_get_client", lambda: client)
    return calls, responses


def test_cache_serves_fresh_copies(hosted):
    async def calls():
        first = await server._get("dockets")
        first["data"].append("changed by a tool")
        return await server._get("dockets")

    asyncio.run(calls())
    second = asyncio.run(server._get("dockets"))
    assert "changed by a tool" not in repr(second)


def test_cached_response_skips_the_upstream_call_and_budget(hosted):
    calls, _ = hosted
    first = asyncio.run(server._get("dockets"))
    second = asyncio.run(server._get("dockets"))
    assert first == second and len(calls) == 1
    # A hit uses none of the hourly budget.
    assert len(server._upstream_starts) == 1
    stored = b"".join(content for _, content in server._cache._entries.values())
    assert b"registered-key" not in stored


def test_errors_null_bodies_and_refusals_are_not_cached(hosted):
    calls, responses = hosted
    responses += [
        httpx.Response(500, text="boom"),
        httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"),
        httpx.Response(200, text="null"),
    ]
    for _ in range(2):
        with pytest.raises(ToolError):
            asyncio.run(server._get("dockets/FAR-2023-0008"))
    assert asyncio.run(server._get("dockets/FAR-2023-0008")) == {}
    asyncio.run(server._get("dockets/FAR-2023-0008"))
    asyncio.run(server._get("dockets/FAR-2023-0008"))
    assert len(calls) == 4
    assert server._cache.stats()["entries"] == 1


def test_cache_times():
    assert server._cache_seconds("documents") == 15 * MINUTE
    assert server._cache_seconds("comments") == 15 * MINUTE
    assert server._cache_seconds("dockets") == 15 * MINUTE
    assert server._cache_seconds("documents/FAR-2023-0008-0001") == 6 * HOUR
    assert server._cache_seconds("comments/FAR-2023-0008-0002") == 6 * HOUR
    assert server._cache_seconds("dockets/FAR-2023-0008") == 6 * HOUR


def test_health_reports_cache_counts():
    from starlette.testclient import TestClient
    from regulationsgov_mcp.http import create_app

    with TestClient(create_app()) as client:
        cache = client.get("/health").json()["cache"]
    assert set(cache) == {"hits", "misses", "entries", "bytes"}
    assert all(isinstance(value, int) for value in cache.values())
