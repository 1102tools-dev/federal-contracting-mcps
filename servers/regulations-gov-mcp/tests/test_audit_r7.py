# SPDX-License-Identifier: MIT
"""Round 7 regression tests.

Headline finding: open_comment_periods sorted DESCENDING by deadline and took
one page of 50, silently dropping the soonest-closing documents (live-proven
with FDA: 71 open, the ones closing in 2 days absent). These tests pin the
ascending sort, the API-true totals, the 40-page reality, comma-separated
multi-agency and multi-sort support, the withinCommentPeriod=False local
rejection, the empty-string filter guards, and the commentOnId objectId shape
guard.

Offline tests mock srv._get. Live tests gate on REGULATIONS_LIVE_TESTS=1 to
match the rest of this suite.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import regulationsgov_mcp.server as srv
from regulationsgov_mcp.server import mcp

LIVE = os.environ.get("REGULATIONS_LIVE_TESTS") == "1"
live = pytest.mark.skipif(
    not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY"
)


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


async def _call_expect_error(name: str, match: str, **kwargs):
    try:
        await mcp.call_tool(name, kwargs)
    except Exception as e:
        assert match.lower() in str(e).lower(), f"expected {match!r} in error, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


def _doc(doc_id: str, end_date: str | None, agency: str = "FAR"):
    return {
        "id": doc_id,
        "attributes": {
            "agencyId": agency,
            "title": f"Title {doc_id}",
            "documentType": "Proposed Rule",
            "commentEndDate": end_date,
            "docketId": "-".join(doc_id.split("-")[:3]),
        },
    }


def _patch_get(monkeypatch, responder, calls: list | None = None):
    async def fake_get(path, params=None):
        if calls is not None:
            calls.append({"path": path, "params": dict(params or {})})
        return responder(path, dict(params or {}))

    monkeypatch.setattr(srv, "_get", fake_get)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def test_multi_field_sort_accepted():
    out = srv._validate_sort(
        "lastModifiedDate,documentId", field="sort",
        valid_fields=srv._COMMENT_SORT_FIELDS,
    )
    assert out == "lastModifiedDate,documentId"


def test_multi_field_sort_bad_part_rejected():
    with pytest.raises(ValueError, match="not a valid sort field"):
        srv._validate_sort(
            "postedDate,bogusField", field="sort",
            valid_fields=srv._COMMENT_SORT_FIELDS,
        )


def test_multi_agency_comma_accepted():
    assert srv._validate_agency_id("FAR,GSA") == "FAR,GSA"
    assert srv._validate_agency_id(" FAR , GSA ") == "FAR,GSA"


def test_multi_agency_empty_token_rejected():
    for bad in ("FAR,,GSA", "FAR,", ",FAR"):
        with pytest.raises(ValueError, match="empty"):
            srv._validate_agency_id(bad)


def test_clamp_str_len_removed():
    assert not hasattr(srv, "_clamp_str_len")


# ---------------------------------------------------------------------------
# within_comment_period=False (finding 2)
# ---------------------------------------------------------------------------

def test_within_comment_period_false_rejected_locally_with_guidance():
    asyncio.run(_call_expect_error(
        "search_documents", "not supported by the API",
        agency_id="FAR", within_comment_period=False,
    ))


def test_within_comment_period_true_sends_true(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, lambda p, q: {"data": [], "meta": {"totalElements": 0}}, calls)
    asyncio.run(_call("search_documents", agency_id="FAR", within_comment_period=True))
    assert calls[0]["params"]["filter[withinCommentPeriod]"] == "true"


# ---------------------------------------------------------------------------
# Empty-string filter guards (finding 7)
# ---------------------------------------------------------------------------

def test_empty_docket_id_rejected_documents():
    asyncio.run(_call_expect_error(
        "search_documents", "cannot be empty", docket_id="",
    ))


def test_empty_docket_id_rejected_comments():
    asyncio.run(_call_expect_error(
        "search_comments", "cannot be empty", docket_id="  ",
    ))


def test_empty_comment_on_id_rejected():
    asyncio.run(_call_expect_error(
        "search_comments", "cannot be empty", comment_on_id="",
    ))


# ---------------------------------------------------------------------------
# commentOnId objectId shape guard (finding 8)
# ---------------------------------------------------------------------------

def test_comment_on_id_document_id_shape_rejected():
    asyncio.run(_call_expect_error(
        "search_comments", "objectId", comment_on_id="FAR-2023-0008-0024",
    ))


def test_comment_on_id_hex_accepted(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, lambda p, q: {"data": [], "meta": {"totalElements": 0}}, calls)
    asyncio.run(_call("search_comments", comment_on_id="0900006486531e6b"))
    assert calls[0]["params"]["filter[commentOnId]"] == "0900006486531e6b"


def test_no_data_context_includes_comment_on_id(monkeypatch):
    _patch_get(monkeypatch, lambda p, q: {"data": [], "meta": {"totalElements": 0}})
    data = _payload(asyncio.run(_call(
        "search_comments", comment_on_id="0900006486531e6b")))
    assert data.get("no_data") is True
    assert "0900006486531e6b" in data["no_data_reason"]


# ---------------------------------------------------------------------------
# Page cap 40 (finding 3)
# ---------------------------------------------------------------------------

def test_page_40_accepted(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, lambda p, q: {"data": [], "meta": {"totalElements": 0}}, calls)
    asyncio.run(_call("search_documents", agency_id="FAR", page_number=40))
    assert calls[0]["params"]["page[number]"] == 40


def test_page_41_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "exceeds maximum of 40",
        agency_id="FAR", page_number=41,
    ))


# ---------------------------------------------------------------------------
# open_comment_periods (finding 1)
# ---------------------------------------------------------------------------

def test_open_comment_periods_ascending_single_call_truncation(monkeypatch):
    calls: list = []

    def responder(path, params):
        assert path == "documents"
        return {
            "data": [
                _doc("FDA-2026-N-0002-0001", "2050-02-22", "FDA"),
                _doc("FDA-2026-N-0001-0001", "2026-08-18", "FDA"),
                _doc("FDA-2026-N-0003-0001", "2026-09-16", "FDA"),
                _doc("FDA-2026-N-0004-0001", None, "FDA"),
            ],
            "meta": {"totalElements": 71},
        }

    _patch_get(monkeypatch, responder, calls)
    data = _payload(asyncio.run(_call("open_comment_periods", agency_ids=["FDA"])))

    assert len(calls) == 1, "should be one comma-joined call, not per-agency loops"
    params = calls[0]["params"]
    assert params["sort"] == "commentEndDate", "ascending: soonest deadlines first"
    assert params["page[size]"] == 250
    assert params["filter[agencyId]"] == "FDA"

    assert data["total_open"] == 71
    assert data["returned"] == 4
    assert data["truncated"] is True
    assert "close LATER" in data["truncated_note"]
    dates = [d["comment_end_date"] for d in data["documents"] if d["comment_end_date"]]
    assert dates == sorted(dates), "documents must be sorted soonest-closing first"
    assert data["documents"][0]["comment_end_date"] == "2026-08-18"
    assert data["documents"][-1]["comment_end_date"] is None, "undated kept, listed last"
    assert "undated_note" in data


def test_open_comment_periods_default_agencies_comma_joined(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, lambda p, q: {"data": [], "meta": {"totalElements": 0}}, calls)
    data = _payload(asyncio.run(_call("open_comment_periods")))
    assert calls[0]["params"]["filter[agencyId]"] == "FAR,DARS,GSA,SBA,OFPP,DOD,NASA,VA"
    assert data["total_open"] == 0
    assert "truncated" not in data


# ---------------------------------------------------------------------------
# far_case_history pagination (finding 6)
# ---------------------------------------------------------------------------

def _paged_responder(total: int):
    def responder(path, params):
        if path.startswith("dockets/"):
            return {"data": {"attributes": {
                "title": "Big Docket", "dkAbstract": "A", "rin": "2060-AP86",
                "agencyId": "EPA",
            }}}
        page = params.get("page[number]", 1)
        start = (page - 1) * 250
        count = max(0, min(250, total - start))
        return {
            "data": [
                _doc(f"EPA-HQ-OAR-2009-0171-{start + i:05d}", "2010-01-01", "EPA")
                for i in range(count)
            ],
            "meta": {"totalElements": total},
        }

    return responder


def test_far_case_history_follows_pagination(monkeypatch):
    _patch_get(monkeypatch, _paged_responder(553))
    data = _payload(asyncio.run(_call(
        "far_case_history", docket_id="EPA-HQ-OAR-2009-0171")))
    assert data["total_documents"] == 553
    assert len(data["documents"]) == 553
    assert "truncated" not in data


def test_far_case_history_flags_truncation_past_cap(monkeypatch):
    _patch_get(monkeypatch, _paged_responder(1200))
    data = _payload(asyncio.run(_call(
        "far_case_history", docket_id="EPA-HQ-OAR-2009-0171")))
    assert data["total_documents"] == 1200
    assert len(data["documents"]) == 1000
    assert data["truncated"] is True


def test_far_case_history_small_docket_single_page(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, _paged_responder(12), calls)
    data = _payload(asyncio.run(_call("far_case_history", docket_id="FAR-2023-0008")))
    assert len(data["documents"]) == 12
    doc_calls = [c for c in calls if c["path"] == "documents"]
    assert len(doc_calls) == 1, "12 docs need one page, not four"


# ---------------------------------------------------------------------------
# Live confirmations
# ---------------------------------------------------------------------------

@live
def test_live_multi_agency_comma_filter():
    data = _payload(asyncio.run(_call(
        "search_documents", agency_id="FAR,GSA", page_size=25)))
    agencies = {
        (item.get("attributes") or {}).get("agencyId")
        for item in data.get("data", [])
    }
    assert agencies, "expected results for FAR,GSA"
    assert agencies <= {"FAR", "GSA"}


@live
def test_live_page_21_reachable():
    data = _payload(asyncio.run(_call(
        "search_documents", search_term="FAR", page_size=5, page_number=21)))
    assert data.get("data"), "page 21 should return real data (live API allows 40 pages)"


@live
def test_live_multi_field_sort_accepted_by_api():
    data = _payload(asyncio.run(_call(
        "search_comments", docket_id="FAR-2023-0008",
        sort="lastModifiedDate,documentId", page_size=5)))
    assert "data" in data


@live
def test_live_open_comment_periods_soonest_first():
    data = _payload(asyncio.run(_call("open_comment_periods", agency_ids=["FDA"])))
    dates = [d["comment_end_date"] for d in data["documents"] if d["comment_end_date"]]
    assert dates == sorted(dates)
    assert data["total_open"] >= data["returned"] - len(
        [d for d in data["documents"] if not d["comment_end_date"]]
    )
