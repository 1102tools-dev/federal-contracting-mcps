"""Plain government-side error messages: no raw bodies, no exception text."""
import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import gsa_calc_mcp.server as S
from gsa_calc_mcp._throughput import GsaCalcPacer

UNAVAILABLE = (
    "The government's GSA CALC+ API isn't responding right now ({}). "
    "This is on the government's side; try again in a few minutes."
)


def _call(handler):
    class FakeClient:
        async def get(self, url, **kw):
            return handler(httpx.Request("GET", url))

    orig = S._get_client
    S._get_client = lambda: FakeClient()
    try:
        with pytest.raises(ToolError) as exc:
            asyncio.run(S._get("keyword=test"))
    finally:
        S._get_client = orig
    assert isinstance(exc.value, RuntimeError)
    return str(exc.value)


def test_timeout_message():
    def handler(request):
        raise httpx.ReadTimeout("secret-timeout-detail", request=request)

    text = _call(handler)
    assert text == UNAVAILABLE.format("timed out")
    assert "secret-timeout-detail" not in text


def test_connect_error_message():
    def handler(request):
        raise httpx.ConnectError("secret-dns-detail", request=request)

    text = _call(handler)
    assert text == UNAVAILABLE.format("could not connect")
    assert "secret-dns-detail" not in text


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_message_has_status_and_no_body(status):
    text = _call(lambda r: httpx.Response(status, text="<html><title>BODY-LEAK</title></html>", request=r))
    assert text == UNAVAILABLE.format(f"error {status}")
    assert "BODY-LEAK" not in text
    assert "firewall" not in text and "special characters" not in text


@pytest.mark.parametrize("content", [b"<html>BODY-LEAK</html>", b"", b"[1, 2]", b'"BODY-LEAK"'])
def test_unreadable_200_message(content):
    text = _call(lambda r: httpx.Response(200, content=content, request=r))
    assert text == UNAVAILABLE.format("sent an unreadable response")
    assert "BODY-LEAK" not in text


def test_429_with_retry_after():
    text = _call(lambda r: httpx.Response(429, headers={"Retry-After": "90"}, text="BODY-LEAK", request=r))
    assert text == (
        "The government's GSA CALC+ API is limiting requests right now. "
        "This is on the government's side. Try again in about 2 minutes."
    )


def test_429_without_retry_after():
    text = _call(lambda r: httpx.Response(429, text="BODY-LEAK", request=r))
    assert text == (
        "The government's GSA CALC+ API is limiting requests right now. "
        "This is on the government's side. Wait a few minutes before trying again."
    )
    assert "concurrency" not in text and "provider guidance" not in text


def test_403_keeps_firewall_hint():
    text = _call(lambda r: httpx.Response(403, text="BODY-LEAK", request=r))
    assert "firewall" in text
    assert "BODY-LEAK" not in text


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


def test_budget_messages_reach_user_as_tool_error(tmp_path, monkeypatch):
    clock = Clock()
    p = GsaCalcPacer(pacing_dir=tmp_path, environment={}, clock=clock, sleep=clock.sleep)

    async def fill():
        for _ in range(500):
            await p._reserve(0.01)

    asyncio.run(fill())
    monkeypatch.setattr(S, "_pacer", p)
    text = _call(lambda r: httpx.Response(200, json={}, request=r))
    assert text == (
        "This GSA CALC+ install has used its hourly budget of 500 government calls. "
        "Try again in about 60 minutes."
    )


def test_hosted_budget_message_points_to_local_install(tmp_path, monkeypatch):
    clock = Clock()
    p = GsaCalcPacer(pacing_dir=tmp_path, environment={}, clock=clock, sleep=clock.sleep)

    async def fill():
        for _ in range(500):
            await p._reserve(0.01)

    asyncio.run(fill())
    monkeypatch.setattr(S, "_pacer", p)
    monkeypatch.setenv("CALC_HOSTED", "1")
    text = _call(lambda r: httpx.Response(200, json={}, request=r))
    assert text == (
        "The hosted GSA CALC+ server has used its shared hourly budget of 500 calls. "
        "Try again in about 60 minutes. "
        "For no shared limit, install it locally: https://1102tools.com/#local-or-hosted"
    )
