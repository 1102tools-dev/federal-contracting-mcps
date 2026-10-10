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


# ---------------------------------------------------------------------------
# R10: far_case_history keeps subtype (and the FR document number)
# ---------------------------------------------------------------------------

# Pay Equity (FAR-2023-0021). The 2025 row is the withdrawal: the FR API says
# 2025-00118 is "Proposed rule; withdrawal." with regulations.gov document
# FAR-2023-0021-5147; search_documents in the content test showed its
# subtype "Withdrawal". The documents listing was not saved (quota), so the
# two rows are rebuilt from those values.
PAY_EQUITY_DOCS = {
    "data": [
        {"id": "FAR-2023-0021-5147", "type": "documents", "attributes": {
            "agencyId": "FAR", "docketId": "FAR-2023-0021", "documentType": "Proposed Rule",
            "subtype": "Withdrawal", "frDocNum": "2025-00118",
            "title": "Pay Equity and Transparency in Federal Contracting",
            "postedDate": "2025-01-08T05:00:00Z", "withinCommentPeriod": False}},
        {"id": "FAR-2023-0021-0001", "type": "documents", "attributes": {
            "agencyId": "FAR", "docketId": "FAR-2023-0021", "documentType": "Proposed Rule",
            "subtype": "Notice of Proposed Rulemaking (NPRM)", "frDocNum": "2024-01343",
            "title": "Federal Acquisition Regulation: Pay Equity and Transparency in Federal Contracting",
            "postedDate": "2024-01-30T05:00:00Z", "commentEndDate": "2024-04-02T03:59:59Z",
            "withinCommentPeriod": False}},
    ],
    "meta": {"totalElements": 2, "lastPage": True},
}


def _history_route(docs, posted=0):
    def route(path, params):
        if path.startswith("dockets/"):
            return {"data": {"id": path.split("/")[1], "attributes": {"title": "t"}}}
        if path == "documents":
            return docs
        return {"data": [], "meta": {"totalElements": posted}}
    return route


def test_far_case_history_shows_withdrawal_subtype(monkeypatch):
    _fake_get(monkeypatch, _history_route(PAY_EQUITY_DOCS, 5145))
    out = asyncio.run(srv.far_case_history("FAR-2023-0021", page_size=5))
    rows = _rows_by_id(out["documents"])
    assert rows["FAR-2023-0021-5147"]["subtype"] == "Withdrawal"
    assert rows["FAR-2023-0021-5147"]["fr_doc_num"] == "2025-00118"
    assert rows["FAR-2023-0021-0001"]["subtype"] == "Notice of Proposed Rulemaking (NPRM)"


def test_far_case_history_shows_extension_subtype_from_saved_listing(monkeypatch):
    # dl/docs_FAR-2021-0017.json: -0012 shares the NPRM's title; only the
    # subtype says it is the extension notice.
    _fake_get(monkeypatch, _history_route(FIXTURE["docs_FAR-2021-0017"], 81))
    rows = _rows_by_id(asyncio.run(srv.far_case_history("FAR-2021-0017"))["documents"])
    assert rows["FAR-2021-0017-0012"]["subtype"] == "Extension of Comment Period"
    assert rows["FAR-2021-0017-0012"]["fr_doc_num"] == "2023-24025"


def test_open_comment_periods_rows_carry_subtype(monkeypatch):
    _fake_get(monkeypatch, {"documents": FIXTURE["open_documents"]})
    rows = _rows_by_id(asyncio.run(srv.open_comment_periods(page_size=100))["documents"])
    gsar = rows["GSA-GSAR-2026-0563-0001"]
    assert gsar["subtype"] == "Notice of Proposed Rulemaking (NPRM)"
    assert gsar["fr_doc_num"] == "2026-19331"


# ---------------------------------------------------------------------------
# R2: organization on comment search rows
# ---------------------------------------------------------------------------

def _comment_rows():
    # Search rows as the API returns them (dl/comments_on_0194.json shape:
    # no organization attribute), for PSC's comment plus two others.
    base = FIXTURE["comments_on_0194"]["data"][0]["attributes"]
    rows = []
    for cid in ("DARS-2020-0034-0276", "DARS-2020-0034-0230", "DARS-2020-0034-0231"):
        rows.append({"id": cid, "type": "comments", "attributes": dict(base)})
    return {"data": rows, "meta": {"totalElements": 3, "lastPage": True}}


def test_comment_search_rows_lack_organization_at_the_source():
    for row in FIXTURE["comments_on_0194"]["data"]:
        assert "organization" not in row["attributes"]


def test_search_comments_include_organization(monkeypatch):
    calls = []

    def route(path, params):
        if path == "comments":
            return _comment_rows()
        if path == "comments/DARS-2020-0034-0276":
            return FIXTURE["comment_DARS-2020-0034-0276"]  # organization: PSC
        if path == "comments/DARS-2020-0034-0230":
            return {"data": {"id": "DARS-2020-0034-0230", "attributes": {"organization": None}}}
        raise srv.ToolError("HTTP 503: upstream")

    _fake_get(monkeypatch, route, calls)
    out = asyncio.run(srv.search_comments(comment_on_id="090000648664a1fa", page_size=5,
                                          include_organization=True))
    attrs = {r["id"]: r["attributes"] for r in out["data"]}
    assert attrs["DARS-2020-0034-0276"]["organization"] == "Professional Services Council"
    assert "organization" not in attrs["DARS-2020-0034-0230"]
    assert attrs["DARS-2020-0034-0231"]["organizationLookupFailed"] is True
    assert out["organization_lookup"]["rows_with_organization"] == 1
    assert out["organization_lookup"]["lookups_failed"] == 1
    assert [c[0] for c in calls[1:]] == [f"comments/{i}" for i in attrs]


def test_search_comments_default_warns_about_missing_organization(monkeypatch):
    calls = []
    _fake_get(monkeypatch, lambda p, q: _comment_rows(), calls)
    out = asyncio.run(srv.search_comments(docket_id="DARS-2020-0034"))
    assert len(calls) == 1, "no detail lookups unless asked"
    assert "include_organization=True" in out["organization_note"]


def test_include_organization_caps_page_size(monkeypatch):
    _fake_get(monkeypatch, lambda p, q: _comment_rows())
    with pytest.raises(ValueError, match="capped at 25"):
        asyncio.run(srv.search_comments(docket_id="DARS-2020-0034", page_size=50,
                                        include_organization=True))


# ---------------------------------------------------------------------------
# R8: the 40-page ceiling is flagged, not passed through as lastPage=true
# ---------------------------------------------------------------------------

def _page(n_rows, total, page_number, page_size, kind="comments", prefix="FAR-2023-0021"):
    return {
        "data": [{"id": f"{prefix}-{i:04d}", "type": kind,
                  "attributes": {"agencyId": "FAR", "title": "Comment", "postedDate": "2024-03-29T04:00:00Z"}}
                 for i in range(n_rows)],
        "meta": {"totalElements": total, "totalPages": 40, "pageNumber": page_number,
                 "pageSize": page_size, "hasNextPage": page_number < 40,
                 "lastPage": page_number == 40, "numberOfElements": n_rows},
    }


def test_pay_equity_page_40_is_flagged_truncated(monkeypatch):
    # Content test Q25: totalElements 5145 (= FR's regulations.gov count,
    # dl/fr_2024-01343.json); page 40 x 100 came back lastPage=true.
    _fake_get(monkeypatch, lambda p, q: _page(100, 5145, 40, 100))
    out = asyncio.run(srv.search_comments(docket_id="FAR-2023-0021", page_size=100,
                                          page_number=40, sort="postedDate"))
    assert out["truncated"] is True
    assert out["records_beyond_page_limit"] == 1145
    assert out["meta"]["lastPage"] is False
    assert "posted_date_ge/le" in out["truncated_note"]


def test_page_one_warns_when_results_exceed_the_ceiling(monkeypatch):
    _fake_get(monkeypatch, lambda p, q: _page(25, 5145, 1, 25))
    out = asyncio.run(srv.search_comments(docket_id="FAR-2023-0021"))
    assert "truncated" not in out
    assert "4145 cannot be reached" in out["page_limit_note"]
    assert "page_size up to 100" in out["page_limit_note"]


def test_documents_and_dockets_flag_the_ceiling(monkeypatch):
    _fake_get(monkeypatch, lambda p, q: _page(10, 932, 40, 10, "dockets", "DARS-2020"))
    out = asyncio.run(srv.search_dockets(agency_id="DARS", page_size=10, page_number=40))
    assert out["truncated"] is True and out["records_beyond_page_limit"] == 532
    assert "last_modified_date_ge/le" in out["truncated_note"]
    _fake_get(monkeypatch, lambda p, q: _page(100, 4001, 40, 100, "documents"))
    out = asyncio.run(srv.search_documents(agency_id="FAR", page_size=100, page_number=40))
    assert out["records_beyond_page_limit"] == 1


def test_no_ceiling_flag_when_everything_is_reachable(monkeypatch):
    _fake_get(monkeypatch, lambda p, q: _page(81, 81, 1, 100))
    out = asyncio.run(srv.search_comments(docket_id="FAR-2021-0017", page_size=100))
    assert "truncated" not in out and "page_limit_note" not in out


# ---------------------------------------------------------------------------
# P3s: R4 document_type on open_comment_periods, R5 self-filtered facets,
# R7 HTML text, R9/R11 search-term guidance, docket sort fields
# ---------------------------------------------------------------------------

def test_open_comment_periods_document_type_filter(monkeypatch):
    calls = []
    _fake_get(monkeypatch, {"documents": {"data": [], "meta": {"totalElements": 0}}}, calls)
    out = asyncio.run(srv.open_comment_periods(document_type="Proposed Rule"))
    assert calls[0][1]["filter[documentType]"] == "Proposed Rule"
    assert calls[0][1]["filter[withinCommentPeriod]"] == "true"
    assert out["document_type"] == "Proposed Rule"


def test_self_filtered_facets_are_dropped(monkeypatch):
    # dl/open_far_dars.json: an agency-filtered, open-only query whose
    # agencyId facet lists FDA/FAA/FMCSA and withinCommentPeriod lists false.
    payload = {
        "data": FIXTURE["open_documents"]["data"][:2],
        "meta": {"totalElements": 70, "aggregations": {
            "agencyId": [{"value": "FDA", "docCount": 149}, {"value": "FAA", "docCount": 117}],
            "withinCommentPeriod": [{"label": "true", "docCount": 70}, {"label": "false", "docCount": 1706}],
            "documentType": [{"label": "Notice", "docCount": 61}, {"label": "Proposed Rule", "docCount": 9}],
        }},
    }
    _fake_get(monkeypatch, {"documents": payload})
    out = asyncio.run(srv.search_documents(agency_id="FAR,DARS", within_comment_period=True))
    facets = out["meta"]["facets"]
    assert "agencyId" not in facets and "withinCommentPeriod" not in facets
    assert facets["documentType"] == {"Notice": 61, "Proposed Rule": 9}


def test_comment_text_and_snippets_are_plain_text(monkeypatch):
    # dl/comment_DARS-2020-0034-0276.json: &ldquo;...&rdquo; and <br/><br/>.
    _fake_get(monkeypatch, {"comments/DARS-2020-0034-0276": FIXTURE["comment_DARS-2020-0034-0276"]})
    out = asyncio.run(srv.get_comment_detail("DARS-2020-0034-0276"))
    text = out["data"]["attributes"]["comment"]
    assert "&ldquo;" not in text and "<br" not in text
    assert "“Defense Federal Acquisition Regulation Supplement" in text
    assert "2024.\n\nPlease see the attached file" in text
    assert srv._html_to_text("<mark><em>association</em></mark> &hellip; 5 &lt; 6") == "association … 5 < 6"


def test_no_data_reason_mentions_the_search_term(monkeypatch):
    _fake_get(monkeypatch, {"comments": {"data": [], "meta": {"totalElements": 0}}})
    term = '"Coalition for Common Sense" OR "Professional Services Council"'
    out = asyncio.run(srv.search_comments(docket_id="GSA-GSAR-2014-0020", search_term=term))
    assert "search_term" in out["no_data_reason"] and "OR" in out["no_data_reason"]


def test_search_descriptions_cover_phrase_quoting_and_docket_sorts():
    tools = {t.name: t.description for t in asyncio.run(srv.mcp.list_tools())}
    assert "quote" in tools["search_documents"].lower() and "not relevance" in tools["search_documents"]
    assert "Quote a phrase" in tools["search_comments"]
    assert "-lastModifiedDate" in tools["search_dockets"]
    assert "document_type='Proposed Rule'" in tools["open_comment_periods"]
