# SPDX-License-Identifier: MIT
"""Credential-redaction regressions for SAM.gov requests."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import sam_gov_mcp.server as srv


SECRET = "SAM-rc5-secret-value"


class _Client:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response

    async def get(self, url: str) -> httpx.Response:
        if self.response is None:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError(f"failed request {url}", request=request)
        return self.response


@pytest.fixture(autouse=True)
def _credential_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SAM_API_KEY", SECRET)
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))


def test_invalid_format_guidance_never_echoes_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = "definitely-not-a-sam-key"
    monkeypatch.setenv("SAM_API_KEY", invalid)
    with pytest.raises(ToolError) as captured:
        srv._get_api_key()
    assert invalid not in str(captured.value)
    assert invalid[:10] not in str(captured.value)


def test_error_formatting_redacts_raw_and_encoded_key() -> None:
    body = f"raw={SECRET}&api_key={SECRET}"
    rendered = srv._format_error(400, body, SECRET)
    assert SECRET not in rendered
    assert "[REDACTED]" in rendered


def test_json_payload_is_redacted_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "https://api.sam.gov/test")
    response = httpx.Response(
        200,
        json={"echo": SECRET, "nested": {"url": f"api_key={SECRET}"}},
        headers={"content-type": "application/json"},
        request=request,
    )
    monkeypatch.setattr(srv, "_get_client", lambda: _Client(response))
    result = asyncio.run(srv._get("/test", {"q": "value"}))
    assert SECRET not in repr(result)
    assert "[REDACTED]" in repr(result)


def test_network_error_url_never_echoes_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(srv, "_get_client", lambda: _Client())
    with pytest.raises(ToolError) as captured:
        asyncio.run(srv._get("/test", {"q": "value"}))
    assert SECRET not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)
