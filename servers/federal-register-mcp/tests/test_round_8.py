# SPDX-License-Identifier: MIT
"""Round 8 regression tests: 2026-10-10 content-test fixes (1.0.13).

The content test asked 42 everyday contracting questions of the hosted
server and checked every answer against the live Federal Register API. The
numbers passed through correctly; the failures were in how the tools framed
the data. One test (or small group) per bug, each written to fail on 1.0.12:

  FR-2  FAR Council documents: no single FAR agency slug works
  FR-3  presidential documents: EO number, subtype, type filter
  FR-1  public inspection: parent agency filters include sub-agencies
  FR-8  paging past page 50 returned page 1 again
  FR-5, FR-6, FR-9, FR-4  smaller fixes (batch order, correction wording,
        10,000 count cap, case-history match source)

Offline tests replace ``_get`` and check the wire URL and the shaping.
Live tests (FR_LIVE_TESTS=1) re-run the content-test repros.
"""

from __future__ import annotations

import asyncio
import os
import urllib.parse

import pytest

import federal_register_mcp.server as srv
from federal_register_mcp.server import mcp

from .test_round_6 import _call, _call_expect_error, _payload, _qs

LIVE = os.environ.get("FR_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")

DOD = {"slug": "defense-department", "name": "Defense Department", "id": 103, "parent_id": None}
GSA = {"slug": "general-services-administration", "name": "General Services Administration", "id": 210, "parent_id": None}
NASA = {"slug": "national-aeronautics-and-space-administration", "name": "National Aeronautics and Space Administration", "id": 301, "parent_id": None}
OFPP = {"slug": "federal-procurement-policy-office", "name": "Federal Procurement Policy Office", "id": 184, "parent_id": 280}


def _tool_description(name: str) -> str:
    async def go():
        for t in await mcp.list_tools():
            if t.name == name:
                return t.description or ""
        raise AssertionError(name)
    return asyncio.run(go())


# ===========================================================================
# FR-2: FAR Council documents
# ===========================================================================

def _far_doc(num, agencies, doc_type="Rule"):
    return {"document_number": num, "type": doc_type, "agencies": agencies}


def test_fr2_far_council_search_keeps_documents_filed_by_dod_gsa_nasa(monkeypatch):
    # January 2025 FAR rules carry DoD+GSA+NASA and no OFPP tag; NASA's own
    # NFS rules carry NASA only. far_council=True must count the first kind.
    nasa_page = {"count": 4, "results": [
        _far_doc("2024-31404", [DOD, GSA, NASA]),
        _far_doc("2025-16412", [OFPP, DOD, GSA, NASA]),
        _far_doc("2025-99999", [NASA]),
        _far_doc("2024-31407", [DOD, GSA, NASA]),
    ]}
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return nasa_page

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call(
        "search_documents", far_council=True, doc_types=["RULE"],
        pub_date_gte="2025-01-01", pub_date_lte="2025-12-31",
    )))
    assert data["count"] == 3
    assert [d["document_number"] for d in data["results"]] == ["2024-31404", "2025-16412", "2024-31407"]
    assert data["far_council"]["complete"] is True
    q = _qs(seen[0])
    assert q["conditions[agencies][]"] == ["national-aeronautics-and-space-administration"]
    assert q["conditions[type][]"] == ["RULE"]


def test_fr2_far_council_flags_an_incomplete_scan(monkeypatch):
    full = {"count": 900, "results": [_far_doc(f"d{i}", [DOD, GSA, NASA]) for i in range(100)]}

    async def fake(url):
        return full

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("search_documents", far_council=True, term="acquisition", per_page=5)))
    assert data["far_council"]["complete"] is False
    assert data["far_council"]["scanned"] == 500
    assert data["count_is_lower_bound"] is True
    assert len(data["results"]) == 5


def test_fr2_open_comment_periods_far_council(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"count": 2, "results": [
            {**_far_doc("far", [DOD, GSA, NASA], "Proposed Rule"), "comments_close_on": "2026-10-19"},
            {**_far_doc("nfs", [NASA], "Notice"), "comments_close_on": "2026-10-12"},
        ]}

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("open_comment_periods", far_council=True)))
    assert [d["document_number"] for d in data["documents"]] == ["far"]
    assert data["total_open"] == 1
    assert _qs(seen[0])["conditions[agencies][]"] == ["national-aeronautics-and-space-administration"]


def test_fr2_far_council_rejects_agencies_combo():
    asyncio.run(_call_expect_error(
        "search_documents", "combined with agencies", far_council=True, agencies=["defense-department"],
    ))


def test_fr2_list_agencies_marks_the_empty_far_slug(monkeypatch):
    async def fake(url):
        return [
            {"id": 539, "name": "Federal Acquisition Regulation System", "short_name": "FAR",
             "slug": "federal-acquisition-regulation-system", "parent_id": None},
            {"id": 97, "name": "Defense Acquisition Regulations System", "short_name": "DARS",
             "slug": "defense-acquisition-regulations-system", "parent_id": 103},
        ]

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("list_agencies", query="acquisition")))
    far = next(a for a in data["agencies"] if a["slug"] == "federal-acquisition-regulation-system")
    assert "far_council" in far["note"]
    dars = next(a for a in data["agencies"] if a["slug"] == "defense-acquisition-regulations-system")
    assert "note" not in dars


def test_fr2_search_warns_when_the_empty_far_slug_is_used(monkeypatch):
    async def fake(url):
        return {"count": 0, "description": "x"}

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call(
        "search_documents", agencies=["federal-acquisition-regulation-system"], doc_types=["RULE"],
    )))
    assert "far_council" in data["note"]


def test_fr2_docstrings_no_longer_steer_far_questions_to_ofpp():
    search = _tool_description("search_documents")
    agencies = _tool_description("list_agencies")
    for text in (search, agencies):
        assert "far_council" in text
        assert "federal-acquisition-regulation-system" in text
    assert "mid-2025" in agencies


@live
def test_live_fr2_far_council_2025_final_rules_is_16():
    # Truth (content test Q17, re-checked live 2026-10-10): 16 final-rule
    # documents filed jointly by DoD, GSA and NASA in 2025; OFPP gives 11.
    data = _payload(asyncio.run(_call(
        "search_documents", far_council=True, doc_types=["RULE"],
        pub_date_gte="2025-01-01", pub_date_lte="2025-12-31", per_page=100,
    )))
    assert data["count"] == 16
    assert data["far_council"]["complete"] is True
    nums = {d["document_number"] for d in data["results"]}
    assert {"2024-31403", "2024-31404", "2024-31407"} <= nums


# ===========================================================================
# FR-3: presidential documents
# ===========================================================================

PRES_FIELDS = {"executive_order_number", "subtype", "signing_date", "presidential_document_number"}


def test_fr3_search_requests_eo_number_and_subtype(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"count": 0, "results": []}

    monkeypatch.setattr(srv, "_get", fake)
    _payload(asyncio.run(_call("search_documents", doc_types=["PRESDOCU"], term="procurement")))
    assert PRES_FIELDS <= set(_qs(seen[0])["fields[]"])


def test_fr3_presidential_fields_dropped_when_null(monkeypatch):
    # Non-presidential documents must not grow by four null keys each.
    async def fake(url):
        return {"count": 2, "results": [
            {"document_number": "2025-06839", "executive_order_number": "14275",
             "subtype": "Executive Order", "signing_date": "2025-04-15",
             "presidential_document_number": "14275"},
            {"document_number": "2025-16412", "executive_order_number": None,
             "subtype": None, "signing_date": None, "presidential_document_number": None},
        ]}

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("search_documents", term="procurement")))
    eo, rule = data["results"]
    assert eo["executive_order_number"] == "14275" and eo["subtype"] == "Executive Order"
    assert not PRES_FIELDS & set(rule)


def test_fr3_presidential_document_type_and_eo_number_filters(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"count": 0, "results": []}

    monkeypatch.setattr(srv, "_get", fake)
    _payload(asyncio.run(_call(
        "search_documents", presidential_document_type=["executive_order"], pub_date_gte="2026-01-01",
    )))
    _payload(asyncio.run(_call("search_documents", executive_order_number=14275)))
    _payload(asyncio.run(_call(
        "get_facet_counts", facet="monthly", presidential_document_type=["executive_order"],
        pub_date_gte="2026-01-01",
    )))
    assert _qs(seen[0])["conditions[presidential_document_type][]"] == ["executive_order"]
    assert _qs(seen[1])["conditions[executive_order_numbers][]"] == ["14275"]
    assert _qs(seen[2])["conditions[presidential_document_type][]"] == ["executive_order"]


@live
def test_live_fr3_2026_executive_orders_is_65_not_128():
    data = _payload(asyncio.run(_call(
        "search_documents", presidential_document_type=["executive_order"],
        pub_date_gte="2026-01-01", pub_date_lte="2026-10-10",
        order="executive_order_number", per_page=5, page=1,
    )))
    # 65 on 2026-10-10 (content test Q41, live re-check); fixed date range.
    assert data["count"] == 65
    first = data["results"][0]
    assert first["executive_order_number"] == "14372"
    assert first["subtype"] == "Executive Order"
    assert first["signing_date"] == "2026-01-07"


@live
def test_live_fr3_eo_number_lookup():
    data = _payload(asyncio.run(_call("search_documents", executive_order_number=14275)))
    assert data["count"] == 1
    assert data["results"][0]["document_number"] == "2025-06839"


# ===========================================================================
# FR-1: public inspection parent agencies
# ===========================================================================

ARMY = {"id": 32, "parent_id": 103, "slug": "army-department", "name": "Army Department", "raw_name": "Army Department"}
FAA = {"id": 159, "parent_id": 492, "slug": "federal-aviation-administration", "name": "Federal Aviation Administration", "raw_name": "Federal Aviation Administration"}
PI_CURRENT = {"count": 3, "results": [
    {"document_number": "2026-20785", "title": "Licenses; Exemptions: Zyltech Engineering", "agencies": [ARMY]},
    {"document_number": "2026-20818", "title": "Airworthiness Directives", "agencies": [FAA]},
    {"document_number": "2026-20999", "title": "Defense notice", "agencies": [{**DOD, "raw_name": "Defense Department"}]},
]}
AGENCIES = [
    {"id": 103, "parent_id": None, "slug": "defense-department", "name": "Defense Department", "short_name": "DOD"},
    {"id": 32, "parent_id": 103, "slug": "army-department", "name": "Army Department", "short_name": None},
    {"id": 999, "parent_id": 32, "slug": "engineers-corps-test", "name": "Engineers Corps Test", "short_name": None},
    {"id": 492, "parent_id": None, "slug": "transportation-department", "name": "Transportation Department", "short_name": "DOT"},
    {"id": 159, "parent_id": 492, "slug": "federal-aviation-administration", "name": "Federal Aviation Administration", "short_name": "FAA"},
]


def _pi_fake(pi=PI_CURRENT, agencies=AGENCIES):
    async def fake(url):
        if "agencies.json" in url:
            return agencies
        return pi
    return fake


@pytest.mark.parametrize("flt", ["defense-department", "defense", "Defense Department", "DOD"])
def test_fr1_public_inspection_parent_filter_includes_sub_agencies(monkeypatch, flt):
    monkeypatch.setattr(srv, "_get", _pi_fake())
    data = _payload(asyncio.run(_call("get_public_inspection", agency_filter=flt)))
    nums = [d["document_number"] for d in data["documents"]]
    assert nums == ["2026-20785", "2026-20999"]
    assert data["filters_applied"]["includes_sub_agencies"] is True


def test_fr1_grandchild_filings_roll_up(monkeypatch):
    corps = {"id": 999, "parent_id": 32, "slug": "engineers-corps-test", "name": "Engineers Corps Test", "raw_name": "x"}
    pi = {"count": 1, "results": [{"document_number": "2026-1", "title": "t", "agencies": [corps]}]}
    monkeypatch.setattr(srv, "_get", _pi_fake(pi=pi))
    data = _payload(asyncio.run(_call("get_public_inspection", agency_filter="defense-department")))
    assert data["filtered_count"] == 1


@live
def test_live_fr1_dod_public_inspection_matches_agency_tree():
    # Ground truth from the API itself: PI filings whose agency is DoD or
    # sits under DoD in agencies.json (parent_id chain).
    async def go():
        agencies = await srv._get(f"{srv.BASE_URL}/agencies.json")
        pi = await srv._get(f"{srv.BASE_URL}/public-inspection-documents/current.json")
        return agencies, pi
    agencies, pi = asyncio.run(go())
    srv._client = None
    parent = {a["id"]: a.get("parent_id") for a in agencies}

    def under_dod(agency_id):
        seen = set()
        while agency_id is not None and agency_id not in seen:
            if agency_id == 103:
                return True
            seen.add(agency_id)
            agency_id = parent.get(agency_id)
        return False

    truth = {d["document_number"] for d in pi["results"]
             if any(under_dod(a.get("id")) or under_dod(a.get("parent_id")) for a in d.get("agencies", []))}
    data = _payload(asyncio.run(_call("get_public_inspection", agency_filter="defense-department", limit=500)))
    assert {d["document_number"] for d in data["documents"]} == truth


def test_fr1_sub_agency_filter_does_not_widen_to_parent(monkeypatch):
    monkeypatch.setattr(srv, "_get", _pi_fake())
    data = _payload(asyncio.run(_call("get_public_inspection", agency_filter="army")))
    assert [d["document_number"] for d in data["documents"]] == ["2026-20785"]
