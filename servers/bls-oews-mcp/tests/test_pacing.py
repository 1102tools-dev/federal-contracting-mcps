# SPDX-License-Identifier: MIT
"""Offline regression tests for opt-in credentialed-request pacing."""

from __future__ import annotations

import asyncio
import time

import pytest

import bls_oews_mcp.server as srv


class _Response:
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"status": "REQUEST_SUCCEEDED", "Results": {"series": []}}


class _Client:
    def __init__(self) -> None:
        self.starts: list[float] = []
        self.ends: list[float] = []

    async def post(self, _url: str, *, content: str) -> _Response:
        assert content
        self.starts.append(time.monotonic())
        await asyncio.sleep(0.005)
        self.ends.append(time.monotonic())
        return _Response()


@pytest.fixture(autouse=True)
def _reset_pacing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    monkeypatch.delenv("FEDERAL_API_MIN_INTERVAL_SECONDS", raising=False)
    srv._pacing_lock = None
    srv._last_credentialed_request_completed = None
    yield
    srv._pacing_lock = None
    srv._last_credentialed_request_completed = None


@pytest.mark.asyncio
async def test_real_key_requests_wait_after_prior_completion(monkeypatch: pytest.MonkeyPatch):
    client = _Client()
    monkeypatch.setenv("BLS_API_KEY", "test-registration-key")
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0.03")
    monkeypatch.setattr(srv, "_get_client", lambda: client)

    await asyncio.gather(
        srv._query_bls(["OEUN000000000000015125200"]),
        srv._query_bls(["OEUN000000000000013108200"]),
    )

    assert len(client.starts) == len(client.ends) == 2
    assert client.starts[1] - client.ends[0] >= 0.025


@pytest.mark.asyncio
async def test_keyless_requests_preserve_unpaced_default(monkeypatch: pytest.MonkeyPatch):
    client = _Client()
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0.03")
    monkeypatch.setattr(srv, "_get_client", lambda: client)

    await asyncio.gather(
        srv._query_bls(["OEUN000000000000015125200"]),
        srv._query_bls(["OEUN000000000000013108200"]),
    )

    assert client.starts[1] < client.ends[0]


@pytest.mark.asyncio
async def test_invalid_interval_stops_before_network(monkeypatch: pytest.MonkeyPatch):
    client = _Client()
    monkeypatch.setenv("BLS_API_KEY", "test-registration-key")
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "-1")
    monkeypatch.setattr(srv, "_get_client", lambda: client)

    with pytest.raises(RuntimeError, match="finite, non-negative"):
        await srv._query_bls(["OEUN000000000000015125200"])
    assert client.starts == []
