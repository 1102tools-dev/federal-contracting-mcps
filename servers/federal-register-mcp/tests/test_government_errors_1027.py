"""Government-side failures reach the client as plain, visible messages.

Every case goes through the real paced request path (_fetch/_get) with a fake
HTTP client, so no network is used and the exact wording is pinned.
"""
import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import federal_register_mcp.server as srv

RAW = "RAW-UPSTREAM-DETAIL-123"


def _down(reason):
    return (
        f"The government's Federal Register API isn't responding right now ({reason}). "
        "This is on the government's side; try again in a few minutes."
    )


def _limited(wait):
    return (
        "The government's Federal Register API is limiting requests right now. "
        f"This is on the government's side. {wait}"
    )


class _Client:
    is_closed = False

    def __init__(self, outcome):
        self.outcome = outcome

    async def get(self, url, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        status, body, headers = self.outcome
        request = httpx.Request("GET", url)
        return httpx.Response(status, content=body, headers=headers, request=request)


def _run(monkeypatch, outcome, tool="search_documents", args=None):
    monkeypatch.setattr(srv, "_get_client", lambda: _Client(outcome))
    args = args if args is not None else {"term": "commercial"}
    with pytest.raises(ToolError) as caught:
        asyncio.run(srv.mcp.call_tool(tool, args))
    error = caught.value
    gov = error
    while gov is not None and not isinstance(gov, srv.GovernmentApiError):
        gov = gov.__cause__
    assert isinstance(gov, ToolError), repr(error)
    assert str(gov) in str(error)  # visible, not the SDK's hidden wrapper
    assert RAW not in str(error)
    return str(gov)


def test_timeout(monkeypatch):
    assert _run(monkeypatch, httpx.ReadTimeout(RAW)) == _down("timed out")


def test_connect_failure(monkeypatch):
    assert _run(monkeypatch, httpx.ConnectError(RAW)) == _down("could not connect")


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_error(monkeypatch, status):
    msg = _run(monkeypatch, (status, f'{{"errors":"{RAW}"}}'.encode(), {}))
    assert msg == _down(f"error {status}")


@pytest.mark.parametrize("body", [
    b"<!doctype html><html><title>" + RAW.encode() + b"</title></html>",
    b"",
    b"null",
    b'"' + RAW.encode() + b'"',
    b"\xff\xfe" + RAW.encode(),
])
def test_garbage_200(monkeypatch, body):
    assert _run(monkeypatch, (200, body, {})) == _down("sent an unreadable response")


def test_garbage_200_document(monkeypatch):
    msg = _run(monkeypatch, (200, b"<html>" + RAW.encode() + b"</html>", {}),
               "get_document", {"document_number": "2026-03065"})
    assert msg == _down("sent an unreadable response")


def test_rate_limited_with_retry_after(monkeypatch):
    msg = _run(monkeypatch, (429, RAW.encode(), {"Retry-After": "120"}))
    assert msg == _limited("Try again in about 2 minutes.")


def test_rate_limited_without_retry_after(monkeypatch):
    msg = _run(monkeypatch, (429, RAW.encode(), {}))
    assert msg == _limited("Wait a few minutes before trying again.")
    assert "delay" not in msg.lower()


def test_client_404_keeps_request_guidance(monkeypatch):
    """A 404 describes the request, not an outage: it keeps its own guidance."""
    monkeypatch.setattr(srv, "_get_client", lambda: _Client((404, b"not here", {})))
    with pytest.raises(ToolError) as caught:
        asyncio.run(srv.mcp.call_tool("get_document", {"document_number": "2026-03065"}))
    cause = caught.value.__cause__
    assert type(cause) is RuntimeError and str(cause).startswith("HTTP 404")
