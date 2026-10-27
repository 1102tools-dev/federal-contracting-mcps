"""Plain government-side error messages: no raw bodies, no exception text."""
import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from regulationsgov_mcp import server as srv

KEY = "test-key-not-real"
UNAVAILABLE = (
    "The government's Regulations.gov API isn't responding right now ({}). "
    "This is on the government's side; try again in a few minutes."
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("REGULATIONS_GOV_API_KEY", KEY)
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))
    monkeypatch.delenv("REGULATIONS_HOSTED", raising=False)
    monkeypatch.setattr(srv, "_upstream_starts", srv.collections.deque())


def _call(monkeypatch, handler):
    class FakeClient:
        async def get(self, url, headers=None):
            return handler(httpx.Request("GET", url, headers=headers))

    monkeypatch.setattr(srv, "_get_client", lambda: FakeClient())
    with pytest.raises(ToolError) as exc:
        asyncio.run(srv._get("documents", {"filter[searchTerm]": "FAR"}))
    text = str(exc.value)
    assert KEY not in text
    return text


def test_timeout_message(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout(f"secret-timeout-detail {request.url}", request=request)

    text = _call(monkeypatch, handler)
    assert text == UNAVAILABLE.format("timed out")
    assert "secret-timeout-detail" not in text


def test_connect_error_message(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("secret-dns-detail", request=request)

    text = _call(monkeypatch, handler)
    assert text == UNAVAILABLE.format("could not connect")
    assert "secret-dns-detail" not in text


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_message_has_status_and_no_body(monkeypatch, status):
    text = _call(monkeypatch, lambda r: httpx.Response(
        status, text="<html><title>BODY-LEAK</title></html>", request=r))
    assert text == UNAVAILABLE.format(f"error {status}")
    assert "BODY-LEAK" not in text
    assert "firewall" not in text and "special characters" not in text


@pytest.mark.parametrize("content", [b"<html>BODY-LEAK</html>", b"{broken", b"[1, 2]", b'"BODY-LEAK"'])
def test_unreadable_200_message(monkeypatch, content):
    text = _call(monkeypatch, lambda r: httpx.Response(200, content=content, request=r))
    assert text == UNAVAILABLE.format("sent an unreadable response")
    assert "BODY-LEAK" not in text


@pytest.mark.parametrize("hosted,retry_after,expected", [
    (None, "90",
     "The government's Regulations.gov API is limiting requests right now. "
     "Your Regulations.gov API key allows 1,000 calls per hour by default. "
     "This is on the government's side. Try again in about 2 minutes."),
    (None, None,
     "The government's Regulations.gov API is limiting requests right now. "
     "Your Regulations.gov API key allows 1,000 calls per hour by default. "
     "This is on the government's side. Wait a few minutes before trying again."),
    ("1", "90",
     "The government's Regulations.gov API is limiting requests right now. "
     "This is on the government's side. Try again in about 2 minutes."),
    ("1", None,
     "The government's Regulations.gov API is limiting requests right now. "
     "This is on the government's side. Wait a few minutes before trying again."),
])
def test_429_messages(monkeypatch, hosted, retry_after, expected):
    if hosted:
        monkeypatch.setenv("REGULATIONS_HOSTED", hosted)
    headers = {"Retry-After": retry_after} if retry_after else {}
    text = _call(monkeypatch, lambda r: httpx.Response(
        429, headers=headers, text='{"error":{"code":"OVER_RATE_LIMIT","message":"BODY-LEAK"}}', request=r))
    assert text == expected


def test_waf_403_keeps_hint_without_body(monkeypatch):
    text = _call(monkeypatch, lambda r: httpx.Response(
        403, text="<html><title>Request Rejected BODY-LEAK</title></html>", request=r))
    assert text == (
        "HTTP 403: Request blocked. Common cause: Regulations.gov's WAF "
        "rejects angle brackets and a handful of other patterns. Remove "
        "special characters from search terms."
    )


@pytest.mark.parametrize("hosted,expected", [
    (None, "This Regulations.gov install has used its hourly budget of 2 government calls. "
           "Try again in about 60 minutes."),
    ("1", "The hosted Regulations.gov server has used its hourly budget of 2 calls. "
          "Try again in about 60 minutes."),
])
def test_hourly_budget_messages(monkeypatch, hosted, expected):
    if hosted:
        monkeypatch.setenv("REGULATIONS_HOSTED", hosted)
    monkeypatch.setattr(srv, "HOURLY_UPSTREAM_CAP", 2)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []}, request=request)

    class FakeClient:
        async def get(self, url, headers=None):
            return handler(httpx.Request("GET", url, headers=headers))

    monkeypatch.setattr(srv, "_get_client", lambda: FakeClient())
    for _ in range(2):
        asyncio.run(srv._get("documents", {"filter[searchTerm]": "FAR"}))
    with pytest.raises(ToolError) as exc:
        asyncio.run(srv._get("documents", {"filter[searchTerm]": "FAR"}))
    assert str(exc.value) == expected
    assert len(calls) == 2
