# SPDX-License-Identifier: MIT
"""Credential-readiness contract for Regulations.gov access."""

from __future__ import annotations

import asyncio

import pytest

from regulationsgov_mcp.server import mcp


def _payload(result):
    return result.structured_content if hasattr(result, "structured_content") else result[1]


@pytest.mark.parametrize("value", [None, "", "   \t"])
def test_access_status_discloses_demo_key_fallback(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("REGULATIONS_GOV_API_KEY", raising=False)
    else:
        monkeypatch.setenv("REGULATIONS_GOV_API_KEY", value)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "limited_fallback"
    assert payload["credential_env"] == "REGULATIONS_GOV_API_KEY"
    assert payload["fallback"]["mode"] == "api.data.gov DEMO_KEY"
    assert "10 requests per hour" in payload["fallback"]["limit"]


def test_access_status_reports_configured_unverified_without_value(monkeypatch):
    secret = "regulations-secret-value"
    monkeypatch.setenv("REGULATIONS_GOV_API_KEY", secret)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "configured_unverified"
    assert payload["fallback"] is None
    assert secret not in repr(payload)
