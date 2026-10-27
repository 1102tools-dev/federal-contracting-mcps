"""Government-side failures reach the client as plain, visible messages.

Cases run through the real paced request paths (_fetch_json and
_get_xml_uncached) with a mock transport: no network, exact wording pinned.
"""
import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ecfr_mcp import server as srv
from ecfr_mcp.constants import DEFAULT_TIMEOUT_CONTENT

RAW = "RAW-UPSTREAM-DETAIL-123"
XML_PATH = "/api/versioner/v1/full/2026-10-01/title-48.xml"


def _down(reason):
    return (
        f"The government's eCFR API isn't responding right now ({reason}). "
        "This is on the government's side; try again in a few minutes."
    )


def _limited(wait):
    return (
        "The government's eCFR API is limiting requests right now. "
        f"This is on the government's side. {wait}"
    )


def _use(monkeypatch, outcome):
    def handler(request):
        if isinstance(outcome, Exception):
            raise outcome
        status, body, headers = outcome
        return httpx.Response(status, content=body, headers=headers)
    client = httpx.AsyncClient(base_url="https://www.ecfr.gov", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(srv, "_get_client", lambda: client)


def _fail(monkeypatch, outcome, kind):
    _use(monkeypatch, outcome)
    with pytest.raises(srv.GovernmentApiError) as caught:
        if kind == "xml":
            asyncio.run(srv._get_xml_uncached(XML_PATH, {"section": "15.305"}))
        else:
            asyncio.run(srv._get_json("/api/admin/v1/agencies.json", None, 1))
    error = caught.value
    assert isinstance(error, ToolError) and isinstance(error, RuntimeError)
    assert RAW not in str(error)
    return str(error)


def test_content_timeout_stays_under_hosted_deadline():
    assert DEFAULT_TIMEOUT_CONTENT == 40.0


@pytest.mark.parametrize("kind", ["xml", "json"])
def test_timeout(monkeypatch, kind):
    assert _fail(monkeypatch, httpx.ReadTimeout(RAW), kind) == _down("timed out")


@pytest.mark.parametrize("kind", ["xml", "json"])
def test_connect_failure(monkeypatch, kind):
    assert _fail(monkeypatch, httpx.ConnectError(RAW), kind) == _down("could not connect")


@pytest.mark.parametrize("kind", ["xml", "json"])
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_error(monkeypatch, kind, status):
    msg = _fail(monkeypatch, (status, RAW.encode(), {}), kind)
    assert msg == _down(f"error {status}")


@pytest.mark.parametrize("body", [
    b"<!doctype html><html><title>" + RAW.encode() + b"</title></html>",
    b"",
    b'"' + RAW.encode() + b'"',
    b"42",
])
def test_garbage_200_json(monkeypatch, body):
    assert _fail(monkeypatch, (200, body, {}), "json") == _down("sent an unreadable response")


@pytest.mark.parametrize("body", [
    b"<!DOCTYPE html><html><head><title>" + RAW.encode() + b"</title></head></html>",
    b"\n  <html lang='en'><body>" + RAW.encode() + b"</body></html>",
])
def test_html_page_instead_of_xml(monkeypatch, body):
    """An HTML outage page is not regulation text: no 'paragraphs' of it."""
    msg = _fail(monkeypatch, (200, body, {"content-type": "text/html"}), "xml")
    assert msg == _down("sent an unreadable response")


def test_real_xml_still_passes(monkeypatch):
    _use(monkeypatch, (200, b'<?xml version="1.0"?><DIV8 N="15.305" TYPE="SECTION"><HEAD>x</HEAD></DIV8>', {}))
    assert "DIV8" in asyncio.run(srv._get_xml_uncached(XML_PATH, {}))


@pytest.mark.parametrize("kind", ["xml", "json"])
def test_rate_limited_with_retry_after(monkeypatch, kind):
    msg = _fail(monkeypatch, (429, RAW.encode(), {"Retry-After": "120"}), kind)
    assert msg == _limited("Try again in about 2 minutes.")


@pytest.mark.parametrize("kind", ["xml", "json"])
def test_rate_limited_without_retry_after(monkeypatch, kind):
    msg = _fail(monkeypatch, (429, RAW.encode(), {}), kind)
    assert msg == _limited("Wait a few minutes before trying again.")


@pytest.mark.parametrize("kind", ["xml", "json"])
def test_404_keeps_http_404_prefix(monkeypatch, kind):
    """404 is a request problem, not an outage: callers rely on the prefix."""
    _use(monkeypatch, (404, b'{"error":"No matching content found."}', {}))
    with pytest.raises(srv.SourceNotFoundError) as caught:
        if kind == "xml":
            asyncio.run(srv._get_xml_uncached(XML_PATH, {}))
        else:
            asyncio.run(srv._fetch_json("/x", None, 1))
    assert str(caught.value).startswith("HTTP 404")


def test_visible_through_the_tool(monkeypatch):
    _use(monkeypatch, (503, RAW.encode(), {}))
    with pytest.raises(ToolError) as caught:
        asyncio.run(srv.mcp.call_tool("list_agencies", {}))
    assert _down("error 503") in str(caught.value)
    assert RAW not in str(caught.value)


def test_content_tool_html_page(monkeypatch):
    _use(monkeypatch, (200, b"<!doctype html><html>" + RAW.encode() + b"</html>", {}))
    with pytest.raises(ToolError) as caught:
        asyncio.run(srv.mcp.call_tool(
            "get_cfr_content", {"title_number": 48, "date": "2026-10-01", "section": "15.305"}))
    assert _down("sent an unreadable response") in str(caught.value)
    assert RAW not in str(caught.value)
