"""Open-comment completeness regressions from the October 10 E2E audit."""
import asyncio
import copy

import federal_register_mcp.server as srv
from .test_round_6 import _call, _payload


def test_open_deadlines_disclose_scan_can_miss_earlier_deadlines(monkeypatch):
    # Live repro: 1,040 matches, 500 scanned, response through October 15
    # omitted 2026-19904 closing October 13. The omitted item must not be
    # represented as a later deadline merely because publication was newer.
    async def search(**kwargs):
        return {"count": 1040, "results": [
            {"document_number": f"2026-{kwargs['page']}-{i}",
             "comments_close_on": "2026-10-15"} for i in range(100)]}
    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call("open_comment_periods", limit=100)))
    assert data["total_open"] == 1040
    assert data["scanned"] == 500
    assert data["complete"] is False
    assert data["truncated"] is True
    assert "earlier" in data["note"]
    assert "comment_date_gte/lte" in data["note"]


def test_open_far_deadlines_preserve_lower_bound_and_scan_metadata(monkeypatch):
    scan = {"nasa_documents": 900, "scanned": 500, "complete": False}
    async def search(**kwargs):
        return {"count": 1, "count_is_lower_bound": True,
                "far_council": copy.deepcopy(scan), "results": [
                    {"document_number": "2026-19158", "comments_close_on": "2026-10-19"}]}
    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call("open_comment_periods", far_council=True)))
    assert data["scanned"] == data["total_open"] == 1
    assert data["complete"] is False
    assert data["total_open_is_lower_bound"] is True
    assert data["far_council"] == scan


def test_complete_open_scan_can_still_limit_returned_documents(monkeypatch):
    async def search(**kwargs):
        return {"count": 2, "results": [
            {"document_number": "2026-19158", "comments_close_on": "2026-10-19"},
            {"document_number": "2026-19159", "comments_close_on": "2026-10-20"}]}
    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call("open_comment_periods", limit=1)))
    assert data["complete"] is True
    assert data["truncated"] is True
    assert "note" not in data


def test_empty_open_scan_is_complete(monkeypatch):
    async def search(**kwargs):
        return {"count": 0, "results": []}
    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call("open_comment_periods")))
    assert data["complete"] is True
    assert data["truncated"] is False
