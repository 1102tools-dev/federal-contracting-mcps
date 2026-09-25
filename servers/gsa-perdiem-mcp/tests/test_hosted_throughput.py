"""Registered-key spacing, the hourly upstream cap, and the opt-in response cache."""
import asyncio

import httpx
import pytest

from gsa_perdiem_mcp import server
from mcp.server.mcpserver.exceptions import ToolError


def test_registered_key_bursts_and_demo_key_stays_conservative():
    assert server._pacer("registered-key").default_interval == server.REGISTERED_KEY_INTERVAL == 0.6
    assert server._pacer("DEMO_KEY").default_interval == 4.0


def test_hourly_cap_stops_before_the_provider_limit(monkeypatch):
    monkeypatch.setattr(server, "HOURLY_UPSTREAM_CAP", 3)
    monkeypatch.setattr(server, "_upstream_starts", server.collections.deque())
    for _ in range(3):
        server._reserve_hourly_upstream()
    with pytest.raises(ToolError, match="hourly .* request budget"):
        server._reserve_hourly_upstream()


def test_cache_is_off_unless_the_deployment_opts_in(monkeypatch):
    monkeypatch.setattr(server, "RESPONSE_CACHE_SECONDS", 0)
    server._cache_put("k", {"v": 1})
    assert server._cache_get("k") is None


def test_cache_serves_copies_and_expires(monkeypatch):
    monkeypatch.setattr(server, "RESPONSE_CACHE_SECONDS", 60)
    monkeypatch.setattr(server, "_response_cache", {})
    server._cache_put("k", {"v": [1]})
    first = server._cache_get("k")
    first["v"].append(2)
    assert server._cache_get("k") == {"v": [1]}
    clock = server.time.monotonic() + 61
    monkeypatch.setattr(server.time, "monotonic", lambda: clock)
    assert server._cache_get("k") is None


def test_cached_response_skips_the_upstream_call(monkeypatch, tmp_path):
    monkeypatch.setenv("PERDIEM_API_KEY", "registered-key")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))
    monkeypatch.setattr(server, "RESPONSE_CACHE_SECONDS", 60)
    monkeypatch.setattr(server, "_response_cache", {})
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "_upstream_starts", server.collections.deque())
    first = asyncio.run(server._get("rates/zip/22201/year/2027"))
    second = asyncio.run(server._get("rates/zip/22201/year/2027"))
    assert first == second and len(calls) == 1
    assert "registered-key" not in repr(server._response_cache)
