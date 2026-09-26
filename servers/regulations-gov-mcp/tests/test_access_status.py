# SPDX-License-Identifier: MIT
"""Credential-readiness contract for Regulations.gov access."""

from __future__ import annotations

import asyncio

import pytest

from regulationsgov_mcp.server import mcp


def _payload(result):
    return result.structured_content if hasattr(result, "structured_content") else result[1]


def _set_key(monkeypatch, value):
    monkeypatch.delenv("REGULATIONS_HOSTED", raising=False)
    if value is None:
        monkeypatch.delenv("REGULATIONS_GOV_API_KEY", raising=False)
    else:
        monkeypatch.setenv("REGULATIONS_GOV_API_KEY", value)


@pytest.mark.parametrize("value", [None, "", "   \t"])
def test_access_status_reports_missing_key_and_setup(monkeypatch, value):
    _set_key(monkeypatch, value)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "key_missing"
    assert payload["credential_env"] == "REGULATIONS_GOV_API_KEY"
    assert payload["setup_url"] == "https://open.gsa.gov/api/regulationsgov/#getting-started"
    assert "DEMO_KEY" not in repr(payload) and "fallback" not in payload


def test_access_status_reports_configured_unverified_without_value(monkeypatch):
    secret = "regulations-secret-value"
    _set_key(monkeypatch, secret)
    payload = _payload(asyncio.run(mcp.call_tool("get_access_status", {})))
    assert payload["status"] == "configured_unverified"
    assert secret not in repr(payload)


def test_server_publishes_no_instructions():
    # The hosted release gate rejects initialize instructions; key setup
    # guidance travels in tool errors and get_access_status instead.
    assert not mcp.instructions


@pytest.mark.parametrize("value", [None, "", "   \t"])
def test_data_tools_without_key_ask_for_one_before_any_request(monkeypatch, value):
    from regulationsgov_mcp import server

    _set_key(monkeypatch, value)
    monkeypatch.setattr(server, "_get_client", lambda: pytest.fail("no key, so no upstream request"))
    with pytest.raises(Exception, match="set\\s+REGULATIONS_GOV_API_KEY") as caught:
        asyncio.run(mcp.call_tool("get_docket_detail", {"docket_id": "FAR-2023-0008"}))
    assert "DEMO_KEY" not in str(caught.value)


def test_data_results_have_no_access_note_with_configured_key(monkeypatch):
    from regulationsgov_mcp import server

    async def fake_get(path, params=None):
        return {"data": {"id": "FAR-2023-0008", "attributes": {"title": "Case"}}}

    secret = "regulations-secret-value"
    _set_key(monkeypatch, secret)
    monkeypatch.setattr(server, "_get", fake_get)
    payload = _payload(asyncio.run(mcp.call_tool("get_docket_detail", {"docket_id": "FAR-2023-0008"})))
    assert "access_note" not in payload
    assert secret not in repr(payload)
