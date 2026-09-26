# SPDX-License-Identifier: MIT
"""Hosted-mode behavior, result size, cache bounds, and directory-listing rules."""

from __future__ import annotations

import asyncio
import json
import re

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import regulationsgov_mcp.server as srv
from regulationsgov_mcp import http as srv_http


def _mode(monkeypatch, key=None, hosted=None):
    if key is None:
        monkeypatch.delenv("REGULATIONS_GOV_API_KEY", raising=False)
    else:
        monkeypatch.setenv("REGULATIONS_GOV_API_KEY", key)
    if hosted is None:
        monkeypatch.delenv("REGULATIONS_HOSTED", raising=False)
    else:
        monkeypatch.setenv("REGULATIONS_HOSTED", hosted)


def _fake_get(monkeypatch, payload, calls=None):
    async def fake(path, params=None):
        if calls is not None:
            calls.append((path, dict(params or {})))
        return json.loads(json.dumps(payload))

    monkeypatch.setattr(srv, "_get", fake)


def _listing(n=3, agencies=300):
    return {
        "data": [
            {"id": f"FAR-2026-0001-{i:04d}", "type": "documents",
             "links": {"self": f"https://api.regulations.gov/v4/documents/FAR-2026-0001-{i:04d}"},
             "attributes": {"agencyId": "FAR", "title": f"Doc {i}", "highlightedContent": "",
                            "docketId": None, "subtype": None, "postedDate": "2026-09-01T04:00:00Z",
                            "withdrawn": False}}
            for i in range(n)
        ],
        "meta": {
            "totalElements": n, "pageNumber": 1, "pageSize": 25,
            "aggregations": {
                "agencyId": [{"value": f"A{i:03d}", "docCount": 1000 - i} for i in range(agencies)],
                "documentType": [{"label": "Rule", "docCount": 2}, {"label": "Notice", "docCount": 1}],
                "postedDate": [],
            },
        },
        "links": {"self": "https://api.regulations.gov/v4/documents"},
    }


# ---------------------------------------------------------------------------
# Hosted mode
# ---------------------------------------------------------------------------

def test_hosted_status_has_no_key_setup_language(monkeypatch):
    _mode(monkeypatch, key="publisher-secret", hosted="1")
    status = srv.get_access_status()
    assert status["status"] == "hosted_publisher_key"
    text = json.dumps(status)
    for word in ("DEMO_KEY", "REGULATIONS_GOV_API_KEY", "setup_url", "restart_required", "publisher-secret"):
        assert word not in text


def test_hosted_without_key_fails_closed(monkeypatch):
    _mode(monkeypatch, key=None, hosted="1")
    assert srv.get_access_status()["status"] == "hosted_key_missing"
    with pytest.raises(ToolError, match="server-side problem"):
        srv._get_api_key()


def test_hosted_entrypoint_refuses_to_start_without_key(monkeypatch):
    _mode(monkeypatch, key=None, hosted="1")
    with pytest.raises(SystemExit, match="REGULATIONS_GOV_API_KEY is required"):
        srv_http.require_hosted_credential()
    _mode(monkeypatch, key="k", hosted="1")
    srv_http.require_hosted_credential()


def test_access_note_only_for_local_demo_key(monkeypatch):
    _fake_get(monkeypatch, _listing())
    _mode(monkeypatch, key=None, hosted=None)
    assert "DEMO_KEY" in asyncio.run(srv.search_documents(agency_id="FAR"))["access_note"]
    _mode(monkeypatch, key="publisher-secret", hosted="1")
    assert "access_note" not in asyncio.run(srv.search_documents(agency_id="FAR"))


@pytest.mark.parametrize("status,body", [
    (403, '{"error":{"code":"API_KEY_INVALID","message":"An invalid api_key was supplied."}}'),
    (429, '{"error":{"code":"OVER_RATE_LIMIT"}}'),
])
def test_hosted_error_messages_do_not_ask_users_for_keys(monkeypatch, status, body):
    _mode(monkeypatch, key="publisher-secret", hosted="1")
    msg = srv._format_error(status, body, "publisher-secret")
    assert "REGULATIONS_GOV_API_KEY" not in msg and "Register" not in msg and "DEMO_KEY" not in msg
    _mode(monkeypatch, key=None, hosted=None)
    local = srv._format_error(status, body, "DEMO_KEY")
    assert "REGULATIONS_GOV_API_KEY" in local or "Register" in local


def test_waf_403_is_not_reported_as_key_problem(monkeypatch):
    _mode(monkeypatch, key="k", hosted="1")
    msg = srv._format_error(403, "<html><title>Request Rejected</title></html>", "k")
    assert "WAF" in msg and "credential" not in msg


# ---------------------------------------------------------------------------
# Result size
# ---------------------------------------------------------------------------

def test_listing_is_compacted_without_losing_rows(monkeypatch):
    _mode(monkeypatch, key="k", hosted="1")
    _fake_get(monkeypatch, _listing(n=3))
    r = asyncio.run(srv.search_documents(agency_id="FAR"))
    assert len(r["data"]) == 3
    assert "aggregations" not in r["meta"] and "links" not in r
    assert r["meta"]["totalElements"] == 3
    assert len(r["meta"]["facets"]["agencyId"]) == 10
    assert r["meta"]["facets"]["agencyId_more"] == 290
    assert r["meta"]["facets"]["documentType"] == {"Rule": 2, "Notice": 1}
    row = r["data"][0]
    assert "links" not in row
    assert set(row["attributes"]) == {"agencyId", "title", "postedDate", "withdrawn"}
    assert len(json.dumps(r)) < len(json.dumps(_listing(n=3))) / 3


def test_unknown_agency_lists_real_codes(monkeypatch):
    _mode(monkeypatch, key="k", hosted="1")
    payload = _listing(n=0)
    payload["meta"]["totalElements"] = 0
    _fake_get(monkeypatch, payload)
    r = asyncio.run(srv.search_documents(agency_id="XYZQ"))
    assert r["no_data"] is True
    assert r["agency_codes_with_most_records"][:2] == ["A000", "A001"]
    assert "document_type uses exact casing" in r["no_data_reason"]
    assert "case-insensitive at the API; unknown" not in r["no_data_reason"]


def test_public_page_size_capped_but_workflows_page_at_250(monkeypatch):
    _mode(monkeypatch, key="k", hosted="1")
    with pytest.raises(ValueError, match="exceeds maximum of 100"):
        asyncio.run(srv.search_documents(page_size=101))
    calls = []
    _fake_get(monkeypatch, _listing(n=0), calls)
    asyncio.run(srv.open_comment_periods(agency_ids=["FAR"]))
    assert calls[-1][1]["page[size]"] == 250


def test_partitioning_advice_matches_real_parameters():
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    for name in ("search_documents", "search_comments"):
        desc = tools[name].description
        assert "lastModifiedDate windows" not in desc
        assert "posted_date_ge/le" in desc
    params = {n: set(t.input_schema["properties"]) for n, t in tools.items()}
    assert "posted_date_ge" in params["search_comments"]
    assert "last_modified_date_ge" in params["search_dockets"]


# ---------------------------------------------------------------------------
# Cache bounds
# ---------------------------------------------------------------------------

def test_cache_is_bounded_by_bytes(monkeypatch):
    monkeypatch.setattr(srv, "RESPONSE_CACHE_SECONDS", 900.0)
    monkeypatch.setattr(srv, "_RESPONSE_CACHE_MAX_BYTES", 10_000)
    monkeypatch.setattr(srv, "_response_cache", {})
    monkeypatch.setattr(srv, "_response_cache_bytes", 0)
    for i in range(50):
        srv._cache_put(f"k{i}", {"blob": "x" * 900})
    assert srv._response_cache_bytes <= 10_000
    assert srv._response_cache_bytes == sum(v[2] for v in srv._response_cache.values())
    assert "k49" in srv._response_cache and "k0" not in srv._response_cache
    monkeypatch.setattr(srv, "_RESPONSE_CACHE_MAX_ENTRY_BYTES", 500)
    srv._cache_put("huge", {"blob": "y" * 5000})
    assert "huge" not in srv._response_cache
    assert srv._cache_get("k49") == {"blob": "x" * 900}


# ---------------------------------------------------------------------------
# Directory rules
# ---------------------------------------------------------------------------

def test_every_tool_declares_all_hints():
    tools = asyncio.run(srv.mcp.list_tools())
    assert len(tools) == 9
    for t in tools:
        a = t.annotations
        assert a.title and a.read_only_hint is True and a.destructive_hint is False, t.name
        assert a.open_world_hint is not None, t.name
    assert {t.name for t in tools if t.annotations.open_world_hint is False} == {"get_access_status"}


def test_no_instructions_or_model_directives():
    assert not srv.mcp.instructions
    for t in asyncio.run(srv.mcp.list_tools()):
        d = t.description or ""
        assert "DEMO_KEY" not in d, t.name
        assert not re.search(r"\b(you must|always call|before (the first|any))\b", d, re.I), t.name
        assert "previously returned" not in d and "verified working live" not in d, t.name
