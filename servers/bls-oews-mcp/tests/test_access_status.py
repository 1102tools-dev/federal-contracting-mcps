# SPDX-License-Identifier: MIT
"""Credential-readiness contract for BLS access."""

from __future__ import annotations

import asyncio

import pytest

from bls_oews_mcp.server import mcp


def _payload(result):
    return result.structured_content if hasattr(result, "structured_content") else result[1]


@pytest.mark.parametrize("value", [None, "", "   \t"])
def test_access_status_discloses_limited_v1_fallback(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BLS_API_KEY", raising=False)
    else:
        monkeypatch.setenv("BLS_API_KEY", value)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "limited_fallback"
    assert payload["credential_env"] == "BLS_API_KEY"
    assert payload["fallback"]["limit"] == "25 requests per day and 10 years per query"
    assert payload["validation"] == "presence_only"


def test_access_status_reports_configured_unverified_without_value(monkeypatch):
    secret = "bls-secret-value"
    monkeypatch.setenv("BLS_API_KEY", secret)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "configured_unverified"
    assert payload["fallback"] is None
    assert secret not in repr(payload)
