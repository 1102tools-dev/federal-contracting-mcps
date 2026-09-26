# SPDX-License-Identifier: MIT
"""Data-status and credential-readiness contract for GSA Per Diem."""

from __future__ import annotations

import asyncio

import pytest

from gsa_perdiem_mcp.server import mcp


def _payload(result):
    return result.structured_content if hasattr(result, "structured_content") else result[1]


def _status(monkeypatch, key=None, hosted=None):
    if key is None:
        monkeypatch.delenv("PERDIEM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("PERDIEM_API_KEY", key)
    if hosted is None:
        monkeypatch.delenv("PERDIEM_HOSTED", raising=False)
    else:
        monkeypatch.setenv("PERDIEM_HOSTED", hosted)
    return _payload(asyncio.run(mcp.call_tool("get_data_status", {})))


@pytest.mark.parametrize("value", [None, "", "   \t"])
def test_local_without_key_reports_key_missing_and_setup(monkeypatch, value):
    payload = _status(monkeypatch, key=value)
    assert payload["live_lookup_access"] == "key_missing"
    assert payload["credential_env"] == "PERDIEM_API_KEY"
    assert payload["setup_url"] == "https://api.data.gov/signup/"
    assert "work without a key" in payload["access_note"]
    assert "DEMO_KEY" not in repr(payload)


def test_local_with_key_reports_configured_unverified_without_value(monkeypatch):
    secret = "perdiem-secret-value"
    payload = _status(monkeypatch, key=secret)
    assert payload["live_lookup_access"] == "configured_unverified"
    assert payload["validation"] == "presence_only"
    assert "access_note" not in payload
    assert secret not in repr(payload)


def test_hosted_status_has_no_key_language(monkeypatch):
    secret = "publisher-secret-value"
    payload = _status(monkeypatch, key=secret, hosted="1")
    assert payload["live_lookup_access"] == "hosted_publisher_key"
    text = repr(payload)
    assert "DEMO_KEY" not in text
    assert "PERDIEM_API_KEY" not in text
    assert secret not in text


def test_hosted_without_key_fails_closed(monkeypatch):
    import gsa_perdiem_mcp.server as srv
    from gsa_perdiem_mcp import http as srv_http
    from mcp.server.mcpserver.exceptions import ToolError

    payload = _status(monkeypatch, key=None, hosted="1")
    assert payload["live_lookup_access"] == "hosted_key_missing"
    assert "access_note" not in payload
    with pytest.raises(ToolError, match="server-side problem"):
        srv._get_api_key()
    with pytest.raises(SystemExit, match="PERDIEM_API_KEY is required"):
        srv_http.require_hosted_credential()


def test_status_reports_bundled_years_and_sources(monkeypatch):
    payload = _status(monkeypatch, hosted="1")
    years = payload["bundled_fiscal_years"]
    assert years == sorted(years)
    assert 2027 in years and 2021 in years
    src = payload["bundled_sources"]["2027"]
    assert src["zip_file"].startswith("https://www.gsa.gov/")
    assert len(src["zip_file_sha256"]) == 64
    # GSA names breakdown files for their first year; the label says what they cover.
    assert src["mie_file_covers"] == "FY2025-present"
    assert payload["bundled_sources"]["2023"]["mie_file_covers"] == "FY2022-FY2024"
    assert set(payload["live_api_tools"]) == {
        "lookup_city_perdiem", "estimate_travel_cost", "compare_locations"}
