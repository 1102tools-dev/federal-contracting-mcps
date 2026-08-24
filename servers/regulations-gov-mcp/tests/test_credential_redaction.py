# SPDX-License-Identifier: MIT
"""Credential-redaction regressions for Regulations.gov requests."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import regulationsgov_mcp.server as srv


SECRET = "rc5-regulations-secret/value"


class _Response:
    status_code = 200
    text = ""
    headers = {"content-type": "application/json"}

    def json(self) -> dict[str, str]:
        return {"echo": SECRET, "url": f"api_key={SECRET}"}


class _Client:
    async def get(self, _url: str) -> _Response:
        return _Response()


@pytest.fixture(autouse=True)
def _credential_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("REGULATIONS_GOV_API_KEY", SECRET)
    monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FEDERAL_API_PACING_DIR", str(tmp_path))


def test_error_formatting_redacts_raw_and_encoded_key() -> None:
    body = f"raw={SECRET}&api_key=rc5-regulations-secret%2Fvalue"
    rendered = srv._format_error(500, body, SECRET)
    assert SECRET not in rendered
    assert "rc5-regulations-secret%2Fvalue" not in rendered
    assert "[REDACTED]" in rendered


def test_json_payload_is_redacted_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(srv, "_get_client", lambda: _Client())
    result = asyncio.run(srv._get("documents", {"filter[searchTerm]": "FAR"}))
    assert SECRET not in repr(result)
    assert "[REDACTED]" in repr(result)


def test_network_error_url_never_echoes_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        async def get(self, url: str) -> _Response:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError(f"failed request {url}", request=request)

    monkeypatch.setattr(srv, "_get_client", lambda: FailingClient())
    with pytest.raises(ToolError) as captured:
        asyncio.run(srv._get("documents", {"filter[searchTerm]": "FAR"}))
    assert SECRET not in str(captured.value)
    assert "rc5-regulations-secret%2Fvalue" not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)
