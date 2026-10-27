# SPDX-License-Identifier: MIT
"""Exact wording for government-side failures: no raw bodies, no exception text,
and never blame the user's input for a timeout or dropped connection."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import sam_gov_mcp.server as srv

KEY = "SAM-00000000-0000-0000-0000-000000000000"


class _Client:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self.response, self.exc = response, exc

    async def get(self, url: str) -> httpx.Response:
        if self.exc is not None:
            raise self.exc
        return self.response


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SAM_API_KEY", KEY)
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))


def _resp(status: int, content: bytes, ctype: str, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"content-type": ctype, **(headers or {})},
        content=content,
        request=httpx.Request("GET", "https://api.sam.gov/x"),
    )


def _error(monkeypatch, client: _Client) -> str:
    monkeypatch.setattr(srv, "_get_client", lambda: client)
    with pytest.raises(ToolError) as captured:
        asyncio.run(srv._get("/x", {"q": "v"}))
    return str(captured.value)


UNREADABLE = (
    "The government's SAM.gov API isn't responding right now (sent an unreadable "
    "response). This is on the government's side; try again in a few minutes."
)


def test_429_without_retry_after(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(429, b'{"message":"throttled nextAccessTime"}', "application/json")))
    assert msg == (
        "The government's SAM.gov API is limiting requests right now. Each SAM.gov "
        "API key also has a daily request allowance. This is on the government's "
        "side. Wait a few minutes before trying again."
    )
    assert "nextAccessTime" not in msg and "Do not retry" not in msg


def test_429_with_retry_after(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(429, b"{}", "application/json", {"Retry-After": "120"})))
    assert msg.endswith("This is on the government's side. Try again in about 2 minutes.")


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_is_government_unavailable(monkeypatch, status):
    msg = _error(monkeypatch, _Client(_resp(status, b"<html><h1>Gateway stack trace</h1></html>", "text/html")))
    assert msg == (
        f"The government's SAM.gov API isn't responding right now (error {status}). "
        "This is on the government's side; try again in a few minutes."
    )


def test_other_4xx_has_no_raw_body(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(405, b"secret upstream detail", "text/plain")))
    assert msg == "HTTP 405: SAM.gov rejected this request."


def test_generic_400_has_no_raw_body(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(400, b"some upstream detail", "text/plain")))
    assert msg == (
        "HTTP 400: SAM.gov rejected the request parameters. Check the search "
        "values and try again."
    )


def test_invalid_search_400_keeps_guidance_without_body(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(400, b"INVALID_SEARCH_PARAMETER: foo=bar", "text/plain")))
    assert msg.startswith("HTTP 400: Invalid search parameter.")
    assert msg.endswith("Dates must be MM/DD/YYYY, not ISO 8601.")
    assert "foo=bar" not in msg


def test_date_400_keeps_guidance_without_body(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(400, b"date range format bad xyz123", "text/plain")))
    assert msg.endswith("Opportunity postedFrom/postedTo range max is 364 days.")
    assert "xyz123" not in msg


def test_plain_404_has_no_raw_body(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(404, b"route xyz123 missing", "text/plain")))
    assert msg == "HTTP 404: SAM.gov did not find a record matching this request."


def test_401_keeps_key_message(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(401, b"<h1>API_KEY_INVALID</h1>", "text/html")))
    assert msg.startswith("Configured credential rejected: SAM.gov returned HTTP 401.")


def test_non_object_json_200(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(200, b'"Max value allowed is 100"', "application/json")))
    assert msg == UNREADABLE


def test_malformed_json_200(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(200, b'{"totalRecords": 1, ', "application/json")))
    assert msg == UNREADABLE


def test_non_json_200(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(200, b"<html>maintenance page</html>", "text/html")))
    assert msg == UNREADABLE
    assert "maintenance" not in msg


def test_html_key_invalid_200_keeps_key_message(monkeypatch):
    msg = _error(monkeypatch, _Client(_resp(200, b"<h1>API_KEY_INVALID</h1>", "text/html")))
    assert msg.startswith("Configured credential rejected: SAM.gov returned HTTP 403.")


def test_timeout_does_not_blame_input(monkeypatch):
    exc = httpx.ReadTimeout("timed out reading https://api.sam.gov/x?api_key=" + KEY)
    msg = _error(monkeypatch, _Client(exc=exc))
    assert msg == (
        "The government's SAM.gov API isn't responding right now (timed out). "
        "This is on the government's side; try again in a few minutes."
    )
    assert KEY not in msg


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("Connection reset by peer"),
        httpx.RemoteProtocolError("Server disconnected without sending a response (EOF)"),
        httpx.ReadError(""),
    ],
)
def test_reset_or_eof_does_not_blame_input(monkeypatch, exc):
    msg = _error(monkeypatch, _Client(exc=exc))
    assert msg == (
        "The government's SAM.gov API isn't responding right now (could not "
        "connect). This is on the government's side; try again in a few minutes."
    )
    for bad in ("firewall", "special characters", "Original error", "reset", "EOF"):
        assert bad not in msg


def test_pacer_runtime_error_is_visible_tool_error(monkeypatch):
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "not-a-number")
    msg = _error(monkeypatch, _Client(_resp(200, b"{}", "application/json")))
    assert "FEDERAL_API_MIN_INTERVAL_SECONDS" in msg
