# SPDX-License-Identifier: MIT
"""2026-10-10 content-test fixes (2.0.3), checked against saved API responses.

The fixture is slimmed from api.regulations.gov/v4 responses saved by the
content test; the expected values come from the Federal Register, not from
this server's own output.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import regulationsgov_mcp.server as srv

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "content_test_2026_10.json").read_text())


def _fake_get(monkeypatch, routes, calls=None):
    """routes: {path: payload} or a callable(path, params) -> payload."""

    async def fake(path, params=None):
        if calls is not None:
            calls.append((path, dict(params or {})))
        payload = routes(path, params or {}) if callable(routes) else routes[path]
        return json.loads(json.dumps(payload))

    monkeypatch.setattr(srv, "_get", fake)


def _rows_by_id(rows, key="document_id"):
    return {r[key]: r for r in rows}


# ---------------------------------------------------------------------------
# R1: comment deadlines in Eastern time
# ---------------------------------------------------------------------------

# Federal Register closing dates for the same documents (dl/fr_*.json).
FR_DEADLINES = {
    "GSA-GSAR-2026-0563-0001": "Oct 22, 2026 11:59 PM ET",  # FR 2026-19331: on or before Oct 22
    "FAR-2026-0006-0001": "Oct 19, 2026 11:59 PM ET",       # FR 2026-19160: comments_close_on 2026-10-19
    "SBA-2026-0199-2726": "Nov 20, 2026 11:59 PM ET",       # FR 2026-19546: Nov 20 (EST, after DST ends)
}


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-23T03:59:59Z", "Oct 22, 2026 11:59 PM ET"),   # EDT
    ("2026-11-21T04:59:59Z", "Nov 20, 2026 11:59 PM ET"),   # EST
    ("2024-02-03T04:59:59Z", "Feb 2, 2024 11:59 PM ET"),    # FAR 2021-017 NPRM
    ("2026-03-08T07:30:00Z", "Mar 8, 2026 3:30 AM ET"),     # just after the March switch
    ("2026-11-01T05:30:00Z", "Nov 1, 2026 1:30 AM ET"),     # repeated hour, EST side
    ("2026-08-18", "Aug 18, 2026"),                          # bare date: no shift
    ("", None), (None, None), ("not a date", None),
])
def test_eastern_deadline_conversion(raw, expected):
    assert srv._eastern_deadline(raw) == expected


def test_eastern_fallback_matches_tz_database():
    if srv._EASTERN is None:
        pytest.skip("no tz database here; fallback is the only path")
    for year in (2005, 2006, 2007, 2024, 2026, 2030):
        for month in range(1, 13):
            for day in (1, 7, 8, 14, 15, 28):
                for hour in (0, 5, 6, 7, 8):
                    m = datetime(year, month, day, hour, 30, tzinfo=timezone.utc)
                    local, _ = srv._eastern_fallback(m)
                    assert local.replace(tzinfo=None) == m.astimezone(srv._EASTERN).replace(tzinfo=None), m


def test_eastern_without_tz_database(monkeypatch):
    monkeypatch.setattr(srv, "_EASTERN", None)
    assert srv._eastern_deadline("2026-10-23T03:59:59Z") == "Oct 22, 2026 11:59 PM ET"
    assert srv._eastern_deadline("2026-11-21T04:59:59Z") == "Nov 20, 2026 11:59 PM ET"


def test_open_comment_periods_deadlines_are_eastern(monkeypatch):
    _fake_get(monkeypatch, {"documents": FIXTURE["open_documents"]})
    out = asyncio.run(srv.open_comment_periods(page_size=100))
    rows = _rows_by_id(out["documents"])
    for doc_id, expected in FR_DEADLINES.items():
        assert rows[doc_id]["comment_deadline"] == expected, doc_id
    assert rows["GSA-GSAR-2026-0563-0001"]["comment_end_date_utc"] == "2026-10-23T03:59:59Z"
    assert all("comment_end_date" not in r for r in out["documents"])


def test_search_and_detail_deadlines_are_eastern(monkeypatch):
    _fake_get(monkeypatch, {"documents": FIXTURE["open_documents"]})
    out = asyncio.run(srv.search_documents(agency_id="GSA", within_comment_period=True))
    attrs = {r["id"]: r["attributes"] for r in out["data"]}
    gsar = attrs["GSA-GSAR-2026-0563-0001"]
    assert gsar["commentDeadlineEastern"] == "Oct 22, 2026 11:59 PM ET"
    assert gsar["commentEndDateUtc"] == "2026-10-23T03:59:59Z"
    assert "commentEndDate" not in gsar

    row = next(r for r in FIXTURE["open_documents"]["data"] if r["id"] == "GSA-GSAR-2026-0563-0001")
    _fake_get(monkeypatch, {"documents/GSA-GSAR-2026-0563-0001": {"data": row}})
    detail = asyncio.run(srv.get_document_detail("GSA-GSAR-2026-0563-0001"))
    assert detail["data"]["attributes"]["commentDeadlineEastern"] == "Oct 22, 2026 11:59 PM ET"


def test_far_case_history_deadlines_are_eastern(monkeypatch):
    docs = FIXTURE["docs_FAR-2021-0017"]

    def route(path, params):
        if path == "dockets/FAR-2021-0017":
            return {"data": {"id": "FAR-2021-0017", "attributes": {"title": "t"}}}
        if path == "documents":
            return docs
        return {"data": [], "meta": {"totalElements": 81}}

    _fake_get(monkeypatch, route)
    out = asyncio.run(srv.far_case_history("FAR-2021-0017"))
    nprm = _rows_by_id(out["documents"])["FAR-2021-0017-0001"]
    assert nprm["comment_deadline"] == "Feb 2, 2024 11:59 PM ET"  # FR 2023-21328: Feb 2, 2024
    assert nprm["comment_end_date_utc"] == "2024-02-03T04:59:59Z"


def test_descriptions_explain_deadline_fields():
    tools = {t.name: t.description for t in asyncio.run(srv.mcp.list_tools())}
    for name in ("search_documents", "get_document_detail"):
        assert "commentDeadlineEastern" in tools[name], name
    for name in ("open_comment_periods", "far_case_history"):
        assert "comment_deadline" in tools[name] and "comment_end_date_utc" in tools[name], name


# ---------------------------------------------------------------------------
# R3: comment counts are labeled as posted submissions
# ---------------------------------------------------------------------------

def test_search_comments_labels_posted_count(monkeypatch):
    # CMMC DFARS proposed rule: API 97 posted; the FR records 109 received
    # (dl/fr_2024-18110.json), so an unlabeled 97 reads as the full count.
    _fake_get(monkeypatch, {"comments": FIXTURE["comments_on_0194"]})
    out = asyncio.run(srv.search_comments(comment_on_id="090000648664a1fa", page_size=5))
    assert out["posted_comments"] == 97
    assert "posted" in out["count_note"] and "received" in out["count_note"]
    assert "duplicateComments" in out["count_note"]


def test_far_case_history_reports_labeled_posted_count(monkeypatch):
    calls = []

    def route(path, params):
        if path.startswith("dockets/"):
            return {"data": {"id": "DARS-2020-0034", "attributes": {"title": "CMMC"}}}
        if path == "documents":
            return FIXTURE["docs_DARS-2020-0034"]
        assert path == "comments" and params["filter[docketId]"] == "DARS-2020-0034"
        return {"data": [], "meta": {"totalElements": 286}}  # dl/comments_docket_DARS-2020-0034.json

    _fake_get(monkeypatch, route, calls)
    out = asyncio.run(srv.far_case_history("DARS-2020-0034"))
    assert out["posted_comments"] == 286
    assert "not comments received" in out["count_note"]
    # later pages skip the extra count call
    calls.clear()
    asyncio.run(srv.far_case_history("DARS-2020-0034", page_size=5, page_number=2))
    assert [c[0] for c in calls] == ["dockets/DARS-2020-0034", "documents"]


def test_far_case_history_survives_count_failure(monkeypatch):
    def route(path, params):
        if path.startswith("dockets/"):
            return {"data": {"id": "X-1", "attributes": {}}}
        if path == "documents":
            return FIXTURE["docs_DARS-2020-0034"]
        raise srv.ToolError("HTTP 503: upstream")

    _fake_get(monkeypatch, route)
    out = asyncio.run(srv.far_case_history("DARS-2020-0034"))
    assert "posted_comments" not in out and "unavailable" in out["posted_comments_error"]
    assert len(out["documents"]) == 7


def test_count_descriptions_say_posted_not_received():
    tools = {t.name: t.description for t in asyncio.run(srv.mcp.list_tools())}
    for name in ("search_comments", "far_case_history"):
        assert "posted_comments" in tools[name] and "received" in tools[name], name
