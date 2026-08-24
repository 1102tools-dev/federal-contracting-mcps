# SPDX-License-Identifier: MIT
"""Credential-readiness and model-visible failure contract."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import sam_gov_mcp.server as srv
from sam_gov_mcp.server import mcp


def _payload(result):
    return result.structured_content if hasattr(result, "structured_content") else result[1]


@pytest.mark.parametrize("value", [None, "", "   \t"])
def test_access_status_reports_missing_required_without_exposing_values(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SAM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("SAM_API_KEY", value)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "missing_required"
    assert payload["credential_env"] == "SAM_API_KEY"
    assert payload["fallback"] is None
    assert payload["validation"] == "presence_only"


def test_access_status_reports_configured_unverified_and_redacts_value(monkeypatch):
    secret = "SAM-11111111-1111-1111-1111-111111111111"
    monkeypatch.setenv("SAM_API_KEY", secret)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "configured_unverified"
    assert secret not in repr(payload)


def test_missing_key_is_model_visible_and_never_calls_network(monkeypatch):
    monkeypatch.delenv("SAM_API_KEY", raising=False)
    called = False

    async def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    srv._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="Missing required credential: SAM_API_KEY") as excinfo:
        asyncio.run(mcp.call_tool("search_opportunities", {
            "posted_from": "01/01/2026",
            "posted_to": "01/02/2026",
        }))
    assert "https://sam.gov/help" in str(excinfo.value)
    assert "paste the key" in str(excinfo.value)
    assert called is False
    asyncio.run(srv._client.aclose())
    srv._client = None


@pytest.mark.parametrize("status", [401, 403, 429])
def test_auth_and_rate_failures_remain_model_visible_and_redacted(monkeypatch, status):
    secret = "SAM-22222222-2222-2222-2222-222222222222"
    monkeypatch.setenv("SAM_API_KEY", secret)

    async def handler(request):
        return httpx.Response(status, text=f"rejected api_key={secret}", request=request)

    srv._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(mcp.call_tool("search_opportunities", {
            "posted_from": "01/01/2026",
            "posted_to": "01/02/2026",
        }))
    message = str(excinfo.value)
    assert secret not in message
    assert f"{status}" in message
    asyncio.run(srv._client.aclose())
    srv._client = None
