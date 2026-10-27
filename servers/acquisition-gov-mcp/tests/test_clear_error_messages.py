"""Exact wording for Acquisition.gov failures: visible to the user, and never a
raw response body, exception text, curl exit code, or curl stderr."""
import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import acquisition_gov_mcp.server as s
from acquisition_gov_mcp._errors import GovernmentApiError
from test_server import NoWaitPacer

TIMED_OUT = (
    "The government's Acquisition.gov API isn't responding right now (timed out). "
    "This is on the government's side; try again in a few minutes."
)
NO_CONNECT = (
    "The government's Acquisition.gov API isn't responding right now (could not "
    "connect). This is on the government's side; try again in a few minutes."
)


async def _fetch_error(monkeypatch, handler) -> GovernmentApiError:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    monkeypatch.setattr(s, "_pacer", NoWaitPacer())
    monkeypatch.setattr(s, "_client", client)
    monkeypatch.setattr(s, "_prefer_system_curl", False)
    monkeypatch.setattr(s.shutil, "which", lambda name: None)
    try:
        with pytest.raises(GovernmentApiError) as excinfo:
            await s._fetch_bytes(s.RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=1000)
    finally:
        await client.aclose()
    assert isinstance(excinfo.value, ToolError)
    return excinfo.value


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_is_government_unavailable_without_body(monkeypatch, status):
    error = await _fetch_error(
        monkeypatch, lambda r: httpx.Response(status, content=b"<h1>Varnish stack xyz123</h1>")
    )
    assert str(error) == (
        f"The government's Acquisition.gov API isn't responding right now (error {status}). "
        "This is on the government's side; try again in a few minutes."
    )


@pytest.mark.parametrize("status", [403, 404, 410])
async def test_4xx_is_short_and_has_no_body(monkeypatch, status):
    error = await _fetch_error(
        monkeypatch, lambda r: httpx.Response(status, content=b"secret page body xyz123")
    )
    assert str(error) == f"Acquisition.gov returned HTTP {status} for this page."


async def test_429_is_visible_government_limit(monkeypatch):
    error = await _fetch_error(
        monkeypatch, lambda r: httpx.Response(429, headers={"Retry-After": "600"}, content=b"slow down xyz123")
    )
    assert str(error) == (
        "The government's Acquisition.gov API is limiting requests right now. This is "
        "on the government's side. Try again in about 10 minutes."
    )


async def test_httpx_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("read timed out on socket 42", request=request)

    assert str(await _fetch_error(monkeypatch, handler)) == TIMED_OUT


async def test_httpx_connect_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("[Errno 8] nodename nor servname provided", request=request)

    error = await _fetch_error(monkeypatch, handler)
    assert str(error) == NO_CONNECT
    assert "Errno" not in str(error)


class _FakeStream:
    async def read(self, n):
        return b""


class _FakeProcess:
    def __init__(self, returncode, stderr=b""):
        self.returncode = None
        self._final = returncode
        self.stdout = _FakeStream()
        self._stderr = stderr

        class _Err:
            def __init__(inner):
                inner.sent = False

            async def read(inner, n):
                if inner.sent:
                    return b""
                inner.sent = True
                return stderr

        self.stderr = _Err()

    async def wait(self):
        self.returncode = self._final
        return self._final

    def kill(self):
        self.returncode = self._final


@pytest.mark.parametrize(
    "returncode,expected",
    [(28, TIMED_OUT), (6, NO_CONNECT), (7, NO_CONNECT), (35, NO_CONNECT)],
)
async def test_curl_failure_hides_exit_code_and_stderr(monkeypatch, returncode, expected):
    async def spawn(*args, **kwargs):
        return _FakeProcess(returncode, b"curl: (99) SSL_ERROR_SYSCALL secret-detail")

    monkeypatch.setattr(s.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(GovernmentApiError) as excinfo:
        await s._curl_once(s.RFO_INDEX_URL, max_bytes=1000)
    message = str(excinfo.value)
    assert message == expected
    assert "curl" not in message and "secret-detail" not in message and "exit" not in message


async def test_curl_filesize_limit_keeps_size_message(monkeypatch):
    async def spawn(*args, **kwargs):
        return _FakeProcess(63, b"curl: (63) Maximum file size exceeded")

    monkeypatch.setattr(s.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError) as excinfo:
        await s._curl_once(s.RFO_INDEX_URL, max_bytes=1000)
    assert str(excinfo.value) == "Acquisition.gov content exceeds the 1000-byte limit."


async def test_curl_wall_clock_timeout(monkeypatch):
    class Hanging(_FakeProcess):
        async def wait(self):
            while self.returncode is None:  # until kill()
                await asyncio.sleep(0.01)
            return self.returncode

    async def spawn(*args, **kwargs):
        return Hanging(0)

    async def fast_wait_for(awaitable, timeout):
        awaitable.cancel()
        raise asyncio.TimeoutError

    monkeypatch.setattr(s.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(s.asyncio, "wait_for", fast_wait_for)
    with pytest.raises(GovernmentApiError) as excinfo:
        await s._curl_once(s.RFO_INDEX_URL, max_bytes=1000)
    assert str(excinfo.value) == TIMED_OUT


async def test_long_cooldown_message_is_visible():
    with pytest.raises(GovernmentApiError) as excinfo:
        await s._bounded_pacing_sleep(1800)
    assert isinstance(excinfo.value, ToolError)
    assert str(excinfo.value) == (
        "The government's Acquisition.gov API is limiting requests right now. This is "
        "on the government's side. Try again in about 30 minutes."
    )


async def test_tool_call_shows_government_message(monkeypatch):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503, content=b"down xyz123")),
        follow_redirects=False,
    )
    monkeypatch.setattr(s, "_pacer", NoWaitPacer())
    monkeypatch.setattr(s, "_client", client)
    monkeypatch.setattr(s, "_prefer_system_curl", False)
    monkeypatch.setattr(s.shutil, "which", lambda name: None)
    try:
        with pytest.raises(ToolError) as excinfo:
            await s.mcp.call_tool("get_rfo_part", {"part": 10})
    finally:
        await client.aclose()
    assert "(error 503)" in str(excinfo.value)
    assert "xyz123" not in str(excinfo.value)
