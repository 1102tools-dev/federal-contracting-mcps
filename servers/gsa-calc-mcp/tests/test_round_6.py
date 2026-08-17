# SPDX-License-Identifier: MIT
"""Round 6 (1.0.1): differential-count audit regressions.

Background: rounds 1-5 asserted response shape (isinstance(data, dict)) on
live calls and never compared a filtered total against the unfiltered total
or the API's own aggregation buckets. Round 6 ran those differential
assertions against the live CALC+ v3 API and found two high-severity
silent-wrong-data paths plus stale hardcoded SINs:

1. The API silently ignores the worksite filter. Every value (Customer,
   Contractor, Both, and the raw v3 data values Customer_Facility,
   Contractor_Facility, Virtual) returned identical unfiltered totals
   (49,090 for keyword=engineer against worksite buckets of 25,358 /
   21,245 / 2,487). The server now raises on any worksite value.
2. experience_min alone emitted min_years_experience:N, which the API
   treats as an exact term match: experience_min=5 matched 7,343 records
   (the exactly-5 bucket) instead of the expected 29,120 (>= 5). The
   server now emits experience_range:N,999.
3. 541512, 541513, 541610, and 541519 return 0 records (retired or
   absorbed under MAS consolidation); sin_analysis recommended 541512 in
   its docstring. Dead codes removed; sin_analysis appends a retirement
   note when a SIN returns 0 records.
4. price_max=0 built price_range:0,0 (matches nothing, silent empty
   response). Now rejected; the 0.2.2 testing record claimed this guard
   existed, but it never did.

Tiers:
  1. Validation tests (offline, validators raise before any HTTP call)
  2. Mock tests (offline, monkeypatch _get to capture the wire query string)
  3. Live tests (GSA_CALC_LIVE_TESTS=1, hit production CALC+; differential
     count assertions, ~5 API calls)
"""

from __future__ import annotations

import asyncio
import os

import pytest

import gsa_calc_mcp.server as srv
from gsa_calc_mcp.server import mcp


LIVE = os.environ.get("GSA_CALC_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1 to run live API calls")


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


def _tool_docs() -> dict[str, str]:
    return {t.name: (t.description or "") for t in mcp._tool_manager.list_tools()}


_EMPTY_RESPONSE = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}


class _MockGet:
    """Capture the query string _get was called with; return a canned body."""

    def __init__(self, response=None):
        self.response = response if response is not None else _EMPTY_RESPONSE
        self.calls: list[str] = []

    async def __call__(self, params_str: str):
        self.calls.append(params_str)
        return self.response


# ===========================================================================
# TIER 1: VALIDATION (offline)
# ===========================================================================

@pytest.mark.parametrize("ws", [
    "Customer", "Contractor", "Both", "Customer_Facility",
    "Contractor_Facility", "Virtual",
])
def test_keyword_search_worksite_rejected(ws):
    asyncio.run(_call_expect_error(
        "keyword_search", "worksite filtering is not supported",
        keyword="engineer", worksite=ws,
    ))


def test_filtered_browse_worksite_rejected():
    asyncio.run(_call_expect_error(
        "filtered_browse", "worksite filtering is not supported",
        worksite="Customer", education_level="BA",
    ))


def test_price_max_zero_rejected():
    asyncio.run(_call_expect_error(
        "filtered_browse", "price_max must be > 0", price_max=0,
    ))


def test_price_max_zero_rejected_on_keyword_search():
    asyncio.run(_call_expect_error(
        "keyword_search", "price_max must be > 0",
        keyword="engineer", price_max=0.0,
    ))


def test_price_max_negative_still_rejected():
    asyncio.run(_call_expect_error(
        "filtered_browse", "price_max", price_max=-5,
    ))


def test_price_min_zero_still_allowed():
    """0 is a legitimate lower bound; only the ceiling rejects 0."""
    pmin, pmax = srv._validate_price_range(0.0, 50.0)
    assert (pmin, pmax) == (0.0, 50.0)


# ===========================================================================
# TIER 1.5: HARDCODED-VALUE GUARDS (offline)
# ===========================================================================

def test_common_sins_contain_no_dead_codes():
    """541512/541513/541610/541519 return 0 records on the live API."""
    from gsa_calc_mcp.constants import COMMON_SINS
    for dead in ("541512", "541513", "541610", "541519"):
        assert dead not in COMMON_SINS, f"dead SIN {dead} back in COMMON_SINS"


def test_sin_analysis_docstring_recommends_no_dead_codes():
    doc = _tool_docs()["sin_analysis"]
    for dead in ("541512", "541513", "541610", "541519"):
        assert dead not in doc, f"dead SIN {dead} recommended in docstring"


def test_keyword_search_docstring_lists_all_ordering_fields():
    from gsa_calc_mcp.constants import ORDERING_FIELDS
    doc = _tool_docs()["keyword_search"]
    for field in ORDERING_FIELDS:
        assert field in doc, f"ordering field {field} missing from docstring"


# ===========================================================================
# TIER 2: MOCK (offline, verify wire filters)
# ===========================================================================

def test_experience_min_alone_emits_range(monkeypatch):
    """min-only must go out as experience_range:N,999, never as the
    exact-match min_years_experience:N filter."""
    mock = _MockGet()
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("keyword_search", keyword="engineer", experience_min=5))
    qs = mock.calls[-1]
    assert "filter=experience_range:5%2C999" in qs, qs
    assert "min_years_experience" not in qs, qs


def test_experience_both_bounds_unchanged(monkeypatch):
    mock = _MockGet()
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "keyword_search", keyword="engineer", experience_min=5, experience_max=10,
    ))
    qs = mock.calls[-1]
    assert "filter=experience_range:5%2C10" in qs, qs


def test_experience_max_alone_unchanged(monkeypatch):
    mock = _MockGet()
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("keyword_search", keyword="engineer", experience_max=10))
    qs = mock.calls[-1]
    assert "filter=experience_range:0%2C10" in qs, qs


def test_worksite_never_reaches_wire(monkeypatch):
    """The rejection fires before any HTTP call is attempted."""
    mock = _MockGet()
    monkeypatch.setattr(srv, "_get", mock)
    with pytest.raises(Exception, match="worksite filtering is not supported"):
        asyncio.run(mcp.call_tool("filtered_browse", {
            "worksite": "Customer", "education_level": "BA",
        }))
    assert mock.calls == []


def test_sin_analysis_zero_records_gets_retirement_note(monkeypatch):
    mock = _MockGet()
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="541512")))
    assert r["total_rates"] == 0
    assert "retired" in r.get("_note", "").lower()


def test_sin_analysis_nonzero_records_no_note(monkeypatch):
    mock = _MockGet({
        "hits": {"total": {"value": 5}, "hits": []},
        "aggregations": {"wage_stats": {"count": 5}},
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="54151S")))
    assert r["total_rates"] == 5
    assert "_note" not in r


# ===========================================================================
# TIER 3: LIVE (guarded; ~5 API calls)
# ===========================================================================

@live
def test_live_experience_min_is_true_minimum():
    """Differential: with experience_min=5 the response's own
    min_years_experience buckets must contain no key below 5, and the total
    must exceed the exactly-5 bucket (both fail if the server regresses to
    the exact-match filter, and the first fails if the API drops the
    filter)."""
    r = _payload(asyncio.run(_call(
        "keyword_search", keyword="engineer", experience_min=5, page_size=1,
    )))
    total = r["_stats"]["total_rates"]
    buckets = {}
    for b in r["aggregations"]["min_years_experience"]["buckets"]:
        try:
            buckets[int(b["key"])] = b["doc_count"]
        except (KeyError, TypeError, ValueError):
            continue
    assert buckets, "no min_years_experience buckets in response"
    assert min(buckets) >= 5, f"filter leaked sub-minimum years: {sorted(buckets)}"
    exact_five = buckets.get(5, 0)
    assert total > exact_five, (
        f"total {total} not above the exactly-5 bucket {exact_five}; "
        f"min-only filter looks like an exact match again"
    )


@live
def test_live_worksite_filter_still_ignored_upstream():
    """Canary: if this fails, GSA started honoring the worksite filter and
    the 1.0.1 local rejection should be reverted."""
    base_qs = "keyword=engineer&page=1&page_size=1&ordering=current_price&sort=asc"
    filt_qs = (
        "keyword=engineer&filter=worksite:Customer_Facility"
        "&page=1&page_size=1&ordering=current_price&sort=asc"
    )

    async def _both():
        # Both GETs inside one event loop: the shared httpx client binds to
        # the loop of its first request, and a second asyncio.run() would hit
        # "Event loop is closed" (the 0.2.2 _reset_client lesson).
        return await srv._get(base_qs), await srv._get(filt_qs)

    base, filt = asyncio.run(_both())
    base_count = base["aggregations"]["wage_stats"]["count"]
    filt_count = filt["aggregations"]["wage_stats"]["count"]
    assert base_count == filt_count, (
        f"worksite filter changed the total ({base_count} vs {filt_count}): "
        f"GSA now honors it; revert the 1.0.1 worksite rejection"
    )


@live
def test_live_dead_sin_gets_retirement_note():
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="541512", page_size=1)))
    assert r["total_rates"] == 0
    assert "retired" in r.get("_note", "").lower()


@live
def test_live_replacement_sin_has_records():
    """561210FAC replaced 541512 in the docstring; it must stay live."""
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="561210FAC", page_size=1)))
    assert r["total_rates"] > 0
    assert "_note" not in r


# ===========================================================================
# VENDOR RATE CARD PAGINATION (the CALC-3 field finding)
# ===========================================================================
# Before 1.0.1 vendor_rate_card had page_size but no page parameter: rows
# 501+ of a large vendor's card were unreachable at any size, the 500-row
# default payload for Booz Allen Hamilton (1,886 categories) was ~114KB and
# overflowed MCP client output limits, and the alphabetical ordering meant
# the visible slice was systematically biased toward the front of the
# alphabet while presenting as complete.

_BAH = "BOOZ ALLEN HAMILTON INC"


def _rate_card_response(total: int, n_rows: int) -> dict:
    """One canned body serving both vendor_rate_card steps: the suggest step
    reads aggregations.vendor_name.buckets, the search step reads hits."""
    return {
        "hits": {
            "total": {"value": total},
            "hits": [
                {"_source": {
                    "labor_category": f"Category {i:04d}",
                    "current_price": 100.0 + i,
                }}
                for i in range(n_rows)
            ],
        },
        "aggregations": {
            "vendor_name": {"buckets": [{"key": _BAH, "doc_count": total}]},
            "wage_stats": {"count": total},
        },
    }


def test_vendor_rate_card_page_passthrough(monkeypatch):
    """page wires through to the search step's query string."""
    mock = _MockGet(_rate_card_response(total=1886, n_rows=100))
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("vendor_rate_card", vendor_name="booz", page=3))
    assert len(mock.calls) == 2, "expected suggest + search calls"
    qs = mock.calls[1]
    assert "search=vendor_name:BOOZ+ALLEN+HAMILTON+INC" in qs, qs
    assert "&page=3&" in qs, qs


def test_vendor_rate_card_default_page_size_100(monkeypatch):
    """Default dropped from 500 to 100: a 500-row page for a vendor the size
    of Booz Allen Hamilton is ~114KB and overflows MCP client output
    limits; 100 rows is ~23KB."""
    mock = _MockGet(_rate_card_response(total=1886, n_rows=100))
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("vendor_rate_card", vendor_name="booz"))
    qs = mock.calls[1]
    assert "&page=1&" in qs, qs
    assert "&page_size=100&" in qs, qs


def test_vendor_rate_card_partial_page_metadata(monkeypatch):
    mock = _MockGet(_rate_card_response(total=250, n_rows=100))
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz")))
    assert r["total_categories"] == 250
    assert r["page"] == 1
    assert r["returned"] == 100
    assert r["returned_range"] == "rows 1-100 of 250"
    assert r["has_more"] is True
    assert r["next_page"] == 2
    note = r.get("_truncation_note", "")
    assert "alphabetical" in note and "page=2" in note, note


def test_vendor_rate_card_middle_page_metadata(monkeypatch):
    mock = _MockGet(_rate_card_response(total=250, n_rows=100))
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz", page=2)))
    assert r["returned_range"] == "rows 101-200 of 250"
    assert r["has_more"] is True
    assert r["next_page"] == 3


def test_vendor_rate_card_complete_card_no_note(monkeypatch):
    mock = _MockGet(_rate_card_response(total=50, n_rows=50))
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz")))
    assert r["total_categories"] == 50
    assert r["returned_range"] == "rows 1-50 of 50"
    assert r["has_more"] is False
    assert r["next_page"] is None
    assert "_truncation_note" not in r


def test_vendor_rate_card_paged_past_end_flagged(monkeypatch):
    mock = _MockGet(_rate_card_response(total=50, n_rows=0))
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz", page=9)))
    assert r["returned"] == 0
    assert r["returned_range"] is None
    assert r["has_more"] is False
    assert r.get("paged_past_end") is True


def test_vendor_rate_card_es_window_clamped():
    """page * page_size past the 10k Elasticsearch window rejects locally."""
    asyncio.run(_call_expect_error(
        "vendor_rate_card", "10,000-result", vendor_name="booz",
        page=30, page_size=500,
    ))


@live
def test_live_vendor_rate_card_page2_differs_total_stable():
    async def _two_pages():
        # Both calls inside one event loop: the shared httpx client binds to
        # the loop of its first request (the 0.2.2 _reset_client lesson).
        a = await _call("vendor_rate_card", vendor_name="BOOZ ALLEN")
        b = await _call("vendor_rate_card", vendor_name="BOOZ ALLEN", page=2)
        return _payload(a), _payload(b)

    r1, r2 = asyncio.run(_two_pages())
    assert r1["vendor"] == r2["vendor"] == _BAH
    assert r1["total_categories"] == r2["total_categories"]
    assert r1["total_categories"] > 1000, "BAH carried 1,886 categories at audit time"
    assert r1["returned"] == r2["returned"] == 100
    assert r1["has_more"] is True and r1["next_page"] == 2
    assert "_truncation_note" in r1
    assert r2["returned_range"].startswith("rows 101-200")
    cats1 = [x["labor_category"] for x in r1["rates"]]
    cats2 = [x["labor_category"] for x in r2["rates"]]
    assert cats1 != cats2, "page 2 returned the same rows as page 1"


@live
def test_live_vendor_rate_card_late_alphabet_reachable():
    """Rows past 500 were unreachable before 1.0.1. The tail of the
    alphabetized ~1,886-row BAH card (rows 1501+) must be fetchable and
    carry late-alphabet categories (the CALC-3 probe showed Software /
    Network / Systems Engineer all sorted past the old cutoff)."""
    r = _payload(asyncio.run(_call(
        "vendor_rate_card", vendor_name="BOOZ ALLEN", page=4, page_size=500,
    )))
    assert r["returned"] > 0, "page 4 empty: rows past 1500 unreachable"
    cats = [x["labor_category"] or "" for x in r["rates"]]
    assert any(c[:1].lower() >= "r" for c in cats if c), (
        f"expected late-alphabet categories in the card's tail, got {cats[:5]}"
    )
