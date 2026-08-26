# SPDX-License-Identifier: MIT
"""Credential-redaction regressions for upstream BLS responses."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import bls_oews_mcp.server as srv


def test_server_suppresses_credential_bearing_http_info_logs() -> None:
    assert srv.mcp.settings.log_level == "WARNING"


SECRET = "rc5-regression-secret"
SERIES = ["OEUN000000000000015125200"]


class _JsonResponse:
    status_code = 200
    text = ""
    headers: dict[str, str] = {}

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, response: object) -> None:
        self.response = response

    async def post(self, _url: str, *, content: str) -> object:
        assert SECRET in content
        return self.response


@pytest.fixture(autouse=True)
def _credential_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("BLS_API_KEY", SECRET)
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))


def test_request_not_processed_never_echoes_active_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    response = _JsonResponse(
        {
            "status": "REQUEST_NOT_PROCESSED",
            "message": [f"The key:{SECRET} provided by the User is invalid."],
        }
    )
    monkeypatch.setattr(srv, "_get_client", lambda: _Client(response))

    with pytest.raises(ToolError) as captured:
        asyncio.run(srv._query_bls(SERIES))

    rendered = str(captured.value)
    streams = capsys.readouterr()
    assert SECRET not in rendered
    assert SECRET not in streams.out
    assert SECRET not in streams.err
    assert "[REDACTED]" in rendered


def test_partial_and_success_messages_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _JsonResponse(
        {
            "status": "REQUEST_PARTIALLY_PROCESSED",
            "message": [f"Diagnostic copied {SECRET}"],
            "Results": {"series": []},
        }
    )
    monkeypatch.setattr(srv, "_get_client", lambda: _Client(response))

    data = asyncio.run(srv._query_bls(SERIES))

    assert SECRET not in repr(data)
    assert data["_warnings"] == ["Diagnostic copied [REDACTED]"]


def test_html_and_generic_http_errors_redact_active_key() -> None:
    html = (
        "<!doctype html><html><head><title>Forbidden "
        f"{SECRET}</title></head><body></body></html>"
    )
    assert SECRET not in srv._clean_error_body(html, (SECRET,))
    rendered = srv._format_error(500, f"upstream echoed {SECRET}", SECRET)
    assert SECRET not in rendered
    assert "[REDACTED]" in rendered


def test_http_status_error_path_redacts_active_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        500,
        text=f"upstream echoed {SECRET}",
        request=httpx.Request("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/"),
    )
    monkeypatch.setattr(srv, "_get_client", lambda: _Client(response))

    with pytest.raises(ToolError) as captured:
        asyncio.run(srv._query_bls(SERIES))

    assert SECRET not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)
