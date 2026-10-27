"""Government-side failures reach the client as plain, visible messages.

Every case goes through the real paced request path (_send/_cached) with a
fake HTTP client, so no network is used and the exact wording is pinned.
"""
import asyncio

import httpx
import pytest

import usaspending_gov_mcp.server as srv
from tests._sdk_error_assertions import government_error_text

RAW = "RAW-UPSTREAM-DETAIL-123"


def _down(reason):
    return (
        f"The government's USAspending API isn't responding right now ({reason}). "
        "This is on the government's side; try again in a few minutes."
    )


def _limited(wait):
    return (
        "The government's USAspending API is limiting requests right now. "
        f"This is on the government's side. {wait}"
    )


class _Client:
    is_closed = False

    def __init__(self, outcome):
        self.outcome = outcome

    async def _answer(self, path):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        request = httpx.Request("GET", "https://api.usaspending.gov" + path)
        status, body, headers = self.outcome
        return httpx.Response(status, content=body, headers=headers, request=request)

    async def get(self, path, params=None):
        return await self._answer(path)

    async def post(self, path, json=None):
        return await self._answer(path)


def _run(monkeypatch, outcome, tool="get_award_detail", args=None):
    monkeypatch.setattr(srv, "_get_client", lambda: _Client(outcome))
    args = args if args is not None else {"generated_award_id": "CONT_AWD_X_9700_-NONE-_-NONE-"}
    with pytest.raises(Exception) as caught:
        asyncio.run(srv.mcp.call_tool(tool, args))
    msg = government_error_text(caught.value, tool)
    assert RAW not in str(caught.value)
    return msg


def test_timeout(monkeypatch):
    msg = _run(monkeypatch, httpx.ReadTimeout(RAW))
    assert msg == _down("timed out")


def test_connect_failure(monkeypatch):
    msg = _run(monkeypatch, httpx.ConnectError(RAW))
    assert msg == _down("could not connect")


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_error(monkeypatch, status):
    msg = _run(monkeypatch, (status, f'{{"detail":"{RAW}"}}'.encode(), {}))
    assert msg == _down(f"error {status}")


@pytest.mark.parametrize("body", [
    b"<!doctype html><html><title>" + RAW.encode() + b"</title></html>",
    b"",
    b"null",
    b'["' + RAW.encode() + b'"]',
    b"\xff\xfe" + RAW.encode(),
])
def test_garbage_200(monkeypatch, body):
    msg = _run(monkeypatch, (200, body, {}))
    assert msg == _down("sent an unreadable response")


def test_garbage_200_on_list_endpoint(monkeypatch):
    msg = _run(monkeypatch, (200, b"<html>" + RAW.encode() + b"</html>", {}), "list_states", {})
    assert msg == _down("sent an unreadable response")


def test_rate_limited_with_retry_after(monkeypatch):
    msg = _run(monkeypatch, (429, RAW.encode(), {"Retry-After": "120"}))
    assert msg == _limited("Try again in about 2 minutes.")


def test_rate_limited_without_retry_after(monkeypatch):
    msg = _run(monkeypatch, (429, RAW.encode(), {}))
    assert msg == _limited("Wait a few minutes before trying again.")


def test_rate_limited_post_tool(monkeypatch):
    msg = _run(monkeypatch, (429, RAW.encode(), {"Retry-After": "30"}),
               "search_recipients", {"keyword": "x"})
    assert msg == _limited("Try again in about 1 minute.")


def test_client_404_keeps_request_guidance(monkeypatch):
    """A 404 describes the request, not an outage: it keeps its own guidance."""
    monkeypatch.setattr(srv, "_get_client", lambda: _Client((404, b'{"detail":"nope"}', {})))
    with pytest.raises(Exception) as caught:
        asyncio.run(srv.mcp.call_tool("get_award_detail", {"generated_award_id": "CONT_AWD_X_9700_-NONE-_-NONE-"}))
    text = str(caught.value)
    assert "government's" not in text or "Error executing tool" in text
    cause = caught.value.__cause__
    assert type(cause) is RuntimeError and "HTTP 404" in str(cause)
