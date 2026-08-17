# SPDX-License-Identifier: MIT
"""Round 6 regression tests: live-audit findings fixed in 1.0.1.

Round 6 audited the server against the API's own OpenAPI spec and the live
archive. Recurring lesson: earlier rounds hardened inputs against junk but
never tested legacy-real inputs (pre-2011 document numbers), and treated
payload size as the only output risk while result correctness went
unchecked (open_comment_periods missed the soonest deadlines entirely).

Tiers:
  1. Validation tests (offline, validators raise before any HTTP call)
  2. Mock tests (offline, monkeypatch _get to capture wire URLs and shape
     handling)
  3. Live tests (FR_LIVE_TESTS=1, hit the production Federal Register API)
"""

from __future__ import annotations

import asyncio
import os
import urllib.parse

import pytest

import federal_register_mcp.server as srv  # noqa: E402
from federal_register_mcp.server import _validate_doc_number, mcp  # noqa: E402


LIVE = os.environ.get("FR_LIVE_TESTS") == "1"
LIVE_REASON = "requires FR_LIVE_TESTS=1"


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
    # mcp>=2.0 returns CallToolResult; mcp 1.x returned (content, structured).
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


def _qs(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


# ===========================================================================
# 1. Legacy document-number families (validation layer)
# ===========================================================================

LEGACY_NUMBERS = ["E9-12940", "X94-70302", "Z9-10645", "94-16174", "00-27904"]
MODERN_NUMBERS = ["2026-07731", "C1-2026-01234"]


@pytest.mark.parametrize("dn", LEGACY_NUMBERS + MODERN_NUMBERS)
def test_validate_doc_number_accepts_live_verified_families(dn):
    assert _validate_doc_number(dn) == dn


@pytest.mark.parametrize("dn", [
    "", "abc", "../../admin", "2026_07731", "#2026-07731",
    "12345-12345", "2026-07731?x=1", "ABC1-2026-01234",
])
def test_validate_doc_number_still_rejects_junk(dn):
    with pytest.raises(ValueError):
        _validate_doc_number(dn)


def test_get_document_accepts_legacy_number(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"document_number": "E9-12940", "title": "Sunshine Act Meeting"}

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("get_document", document_number="E9-12940")))
    assert data["document_number"] == "E9-12940"
    assert seen[0].endswith("/documents/E9-12940.json")


# ===========================================================================
# 2. get_documents_batch single-item collapse
# ===========================================================================

def test_batch_of_one_wraps_bare_document(monkeypatch):
    async def fake(url):
        return {"document_number": "2026-04913", "title": "FAC 2026-01"}

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call(
        "get_documents_batch", document_numbers=["2026-04913"]
    )))
    assert data["count"] == 1
    assert data["results"][0]["document_number"] == "2026-04913"


def test_batch_multi_shape_passes_through(monkeypatch):
    upstream = {
        "count": 1,
        "results": [{"document_number": "2026-04913"}],
        "errors": {"not_found": ["2026-99999"]},
    }

    async def fake(url):
        return upstream

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call(
        "get_documents_batch", document_numbers=["2026-04913", "2026-99999"]
    )))
    assert data["count"] == 1
    assert data["errors"]["not_found"] == ["2026-99999"]


# ===========================================================================
# 3. far_case_history dual-query union
# ===========================================================================

def _doc(num, pub, title="doc"):
    return {"document_number": num, "publication_date": pub, "title": title}


def test_far_case_unions_docket_and_term_results(monkeypatch):
    docket_resp = {"count": 1, "results": [_doc("2025-16412", "2025-08-27")]}
    term_resp = {"count": 3, "results": [
        _doc("2025-16411", "2025-08-27"),
        _doc("2025-16412", "2025-08-27"),
        _doc("2024-00001", "2024-01-15"),
    ]}

    async def fake(url):
        # Route on the actual query key: every search URL carries
        # fields[]=docket_ids, so a bare substring check would misroute.
        return docket_resp if "conditions[docket_id]" in _qs(url) else term_resp

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("far_case_history", docket_id="FAC 2025-06")))
    nums = [d["document_number"] for d in data["documents"]]
    assert data["total_documents"] == 3
    assert set(nums) == {"2025-16411", "2025-16412", "2024-00001"}
    assert nums[0] == "2024-00001", "merged set must stay chronological"
    assert data["docket_matches"] == 1
    assert data["term_matches"] == 3
    assert data["truncated"] is False


def test_far_case_truncated_flag(monkeypatch):
    hundred = [_doc(f"2025-{10000 + i:05d}", "2025-01-01") for i in range(100)]
    docket_resp = {"count": 1625, "results": hundred}
    term_resp = {"count": 0, "results": []}

    async def fake(url):
        return docket_resp if "conditions[docket_id]" in _qs(url) else term_resp

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("far_case_history", docket_id="FAR Case")))
    assert data["truncated"] is True
    assert data["docket_matches"] == 1625
    assert data["total_documents"] == 100


# ===========================================================================
# 4. open_comment_periods correctness
# ===========================================================================

def _oc_doc(num, close):
    return {"document_number": num, "comments_close_on": close}


def test_open_comment_periods_scans_pages_and_sorts_globally(monkeypatch):
    # 250 open docs across 3 pages; the soonest close date sits on page 3,
    # which the pre-fix single-page implementation could never see.
    pages = {
        "1": {"count": 250, "results": [_oc_doc(f"p1-{i}", "2026-11-15") for i in range(100)]},
        "2": {"count": 250, "results": [_oc_doc(f"p2-{i}", "2026-10-15") for i in range(100)]},
        "3": {"count": 250, "results": (
            [_oc_doc("soonest", "2026-08-17")]
            + [_oc_doc(f"p3-{i}", "2026-09-15") for i in range(49)]
        )},
    }
    calls: list[str] = []

    async def fake(url):
        calls.append(url)
        page = _qs(url)["page"][0]
        return pages[page]

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("open_comment_periods", limit=5)))
    assert len(calls) == 3
    assert data["total_open"] == 250
    assert data["scanned"] == 250
    assert data["returned"] == 5
    assert data["documents"][0]["document_number"] == "soonest"
    closes = [d["comments_close_on"] for d in data["documents"]]
    assert closes == sorted(closes)


def test_open_comment_periods_requests_rule_type_oldest_first(monkeypatch):
    async def fake(url):
        return {"count": 0, "results": []}

    seen: list[str] = []

    async def spy(url):
        seen.append(url)
        return await fake(url)

    monkeypatch.setattr(srv, "_get", spy)
    _payload(asyncio.run(_call("open_comment_periods", limit=5)))
    q = _qs(seen[0])
    assert set(q["conditions[type][]"]) == {"PRORULE", "RULE", "NOTICE"}
    assert q["order"] == ["oldest"]
    assert "conditions[comment_date][gte]" in q


def test_open_comment_periods_honors_scan_cap(monkeypatch):
    full_page = {"count": 985, "results": [_oc_doc(f"d{i}", "2026-12-01") for i in range(100)]}
    calls: list[str] = []

    async def fake(url):
        calls.append(url)
        return full_page

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call("open_comment_periods", limit=50)))
    assert len(calls) == 5, "scan cap of 500 means at most 5 pages of 100"
    assert data["total_open"] == 985
    assert data["scanned"] == 500
    assert data["scan_cap"] == 500


# ===========================================================================
# 5. CFR title/part filters
# ===========================================================================

def test_search_cfr_params_reach_the_wire(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"count": 0, "results": []}

    monkeypatch.setattr(srv, "_get", fake)
    _payload(asyncio.run(_call("search_documents", cfr_title=48, cfr_part="52")))
    q = _qs(seen[0])
    assert q["conditions[cfr][title]"] == ["48"]
    assert q["conditions[cfr][part]"] == ["52"]


def test_facet_cfr_params_and_time_bucket_facet(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"2025": {"count": 1}}

    monkeypatch.setattr(srv, "_get", fake)
    _payload(asyncio.run(_call(
        "get_facet_counts", facet="weekly", cfr_title=48, cfr_part=52
    )))
    assert "/documents/facets/weekly?" in seen[0]
    q = _qs(seen[0])
    assert q["conditions[cfr][title]"] == ["48"]
    assert q["conditions[cfr][part]"] == ["52"]


def test_cfr_part_requires_title():
    asyncio.run(_call_expect_error(
        "search_documents", "requires cfr_title", cfr_part="52"
    ))
    asyncio.run(_call_expect_error(
        "get_facet_counts", "requires cfr_title", facet="type", cfr_part="52"
    ))


@pytest.mark.parametrize("title", [0, 51])
def test_cfr_title_out_of_range(title):
    asyncio.run(_call_expect_error(
        "search_documents", "between 1 and 50", cfr_title=title
    ))


def test_cfr_part_rejects_section_syntax():
    asyncio.run(_call_expect_error(
        "search_documents", "part number", cfr_title=48, cfr_part="52.212-4"
    ))


def test_cfr_part_accepts_range(monkeypatch):
    seen: list[str] = []

    async def fake(url):
        seen.append(url)
        return {"count": 0, "results": []}

    monkeypatch.setattr(srv, "_get", fake)
    _payload(asyncio.run(_call("search_documents", cfr_title=48, cfr_part="1-99")))
    assert _qs(seen[0])["conditions[cfr][part]"] == ["1-99"]


# ===========================================================================
# 6. Pre-1994 guard symmetry and facet doc_types typing
# ===========================================================================

def test_search_rejects_pre_1994_lte():
    asyncio.run(_call_expect_error(
        "search_documents", "predates", pub_date_lte="1990-01-01"
    ))


def test_facet_rejects_pre_1994_lte():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "predates", facet="type", pub_date_lte="1990-01-01"
    ))


def test_facet_doc_types_rejects_lowercase():
    # Pre-fix this silently returned {} from the API, indistinguishable
    # from "zero documents published".
    asyncio.run(_call_expect_error(
        "get_facet_counts", "input should be",
        facet="type", doc_types=["rule"], pub_date_gte="2026-08-01",
    ))


def test_facet_rejects_unknown_facet():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "input should be",
        facet="hourly", pub_date_gte="2026-08-01",
    ))


# ===========================================================================
# 7. Public inspection agency matching
# ===========================================================================

_PI_PAYLOAD = {
    "count": 2,
    "results": [
        {
            "document_number": "2026-16682",
            "title": "Defense Logistics Agency Privacy Act Notice",
            "agencies": [{
                "slug": "defense-logistics-agency",
                "name": "Defense Logistics Agency",
                "raw_name": "DEPARTMENT OF DEFENSE",
            }],
        },
        {
            "document_number": "2026-16683",
            "title": "Grant Program Update",
            "agencies": [{
                "slug": "children-and-families-administration",
                "name": "Children and Families Administration",
                "raw_name": "DEPARTMENT OF HEALTH AND HUMAN SERVICES",
            }],
        },
    ],
}


@pytest.mark.parametrize("flt,expected", [
    ("defense", 1),                    # substring of slug, name, and raw_name
    ("logistics agency", 1),           # human-readable name text
    ("department of defense", 1),      # raw_name text
    ("defense-logistics-agency", 1),   # exact slug
    ("Defense-Logistics", 1),          # hyphens-as-spaces fallback, any case
    ("defense-department", 0),         # parent slug still misses: documented caveat
    ("commerce", 0),
])
def test_pi_agency_filter_matches_names_and_raw_names(monkeypatch, flt, expected):
    async def fake(url):
        return _PI_PAYLOAD

    monkeypatch.setattr(srv, "_get", fake)
    data = _payload(asyncio.run(_call(
        "get_public_inspection", agency_filter=flt
    )))
    assert data["filtered_count"] == expected


# ===========================================================================
# 8. Live confirmations (FR_LIVE_TESTS=1)
# ===========================================================================

@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_legacy_document_fetch():
    data = _payload(asyncio.run(_call("get_document", document_number="E9-12940")))
    assert data["document_number"] == "E9-12940"


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_far_case_fac_2025_06_returns_full_set():
    data = _payload(asyncio.run(_call("far_case_history", docket_id="FAC 2025-06")))
    nums = {d["document_number"] for d in data["documents"]}
    assert data["total_documents"] >= 4
    assert {"2025-16411", "2025-16412", "2025-16413"} <= nums


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_open_comment_periods_sound():
    data = _payload(asyncio.run(_call("open_comment_periods", limit=10)))
    assert data["total_open"] >= data["scanned"] >= data["returned"]
    closes = [d.get("comments_close_on") for d in data["documents"]]
    assert closes == sorted(closes)
    if closes:
        assert closes[0] >= data["as_of"]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_cfr_far_part_52():
    data = _payload(asyncio.run(_call(
        "search_documents", cfr_title=48, cfr_part="52", per_page=1
    )))
    assert data["count"] > 0


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_facet_weekly_with_cfr():
    data = _payload(asyncio.run(_call(
        "get_facet_counts", facet="weekly",
        cfr_title=48, cfr_part="52", pub_date_gte="2025-01-01",
    )))
    assert isinstance(data, dict) and len(data) > 0
