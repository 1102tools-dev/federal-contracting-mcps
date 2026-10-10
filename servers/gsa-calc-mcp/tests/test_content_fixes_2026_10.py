# SPDX-License-Identifier: MIT
"""1.0.12: fixes from the 2026-10-10 hosted content test (findings G-1 to G-12).

Each offline test feeds a canned CALC+ body shaped like the real responses
saved during the content test and failed on 1.0.11. Live tests
(GSA_CALC_LIVE_TESTS=1) compare the tool against the CALC+ API directly.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

import gsa_calc_mcp.server as srv
from gsa_calc_mcp.server import mcp


LIVE = os.environ.get("GSA_CALC_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1 to run live API calls")

_BAH = "BOOZ ALLEN HAMILTON INC"
_API = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


class _MockGet:
    def __init__(self, body):
        self.body = body
        self.calls: list[str] = []

    async def __call__(self, qs: str):
        self.calls.append(qs)
        return self.body


def _api(qs: str) -> dict:
    """Direct CALC+ API call for live comparisons (not through the tool)."""
    r = httpx.get(_API + "?" + qs, timeout=60, headers={"User-Agent": "gsa-calc-mcp-tests"})
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# G-5: vendor_rate_card rows carry worksite
# ---------------------------------------------------------------------------

def _booz_pair_response() -> dict:
    """Same title, contract, SIN and education at two prices: the two rows
    differ only by worksite (saved Booz Allen page, GS00F008DA)."""
    common = {
        "labor_category": "ACQUISITION SPECIALIST, LEVEL I",
        "education_level": "Bachelors",
        "min_years_experience": 0,
        "sin": "541611",
        "idv_piid": "GS00F008DA",
        "business_size": "O",
        "vendor_name": _BAH,
        "contract_end": "2027-10-14",
    }
    return {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {"_source": {**common, "current_price": 148.7508, "worksite": "Customer_Facility"}},
                {"_source": {**common, "current_price": 180.6478, "worksite": "Contractor_Facility"}},
            ],
        },
        "aggregations": {
            "vendor_name": {"buckets": [{"key": _BAH, "doc_count": 2}]},
            "wage_stats": {"count": 2},
        },
    }


def test_g5_vendor_rate_card_rows_include_worksite(monkeypatch):
    monkeypatch.setattr(srv, "_get", _MockGet(_booz_pair_response()))
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz")))
    sites = [row.get("worksite") for row in r["rates"]]
    assert sites == ["Customer_Facility", "Contractor_Facility"], r["rates"]
    assert r["rates"][0]["contract_end"] == "2027-10-14"


@live
def test_live_g5_vendor_rate_card_worksite_matches_api():
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="Booz Allen", page_size=20)))
    api = _api("search=vendor_name:BOOZ+ALLEN+HAMILTON+INC&page=1&page_size=20&ordering=labor_category&sort=asc")
    api_sites = [h["_source"].get("worksite") for h in api["hits"]["hits"]]
    tool_sites = [row.get("worksite") for row in r["rates"]]
    assert tool_sites == api_sites
    assert all(tool_sites)


# ---------------------------------------------------------------------------
# G-2: price_reasonableness_check gives no verdict on a tiny sample
# ---------------------------------------------------------------------------

def _stats_response(n: int, price: float = 71.65) -> dict:
    """igce_benchmark body for n identical rates (the n=1 'Help Desk
    Specialist Tier 1' case: std 0, every percentile the same)."""
    pct = {k: price for k in ("10.0", "25.0", "50.0", "75.0", "90.0")}
    return {
        "hits": {"total": {"value": n, "relation": "eq"}, "hits": []},
        "aggregations": {
            "wage_stats": {"count": n, "min": price, "max": price, "avg": price,
                           "std_deviation": 0.0,
                           "std_deviation_bounds": {"lower": price, "upper": price}},
            "histogram_percentiles": {"values": pct},
        },
    }


@pytest.mark.parametrize("n", [1, 5, 19])
def test_g2_price_check_low_sample_has_no_verdict(monkeypatch, n):
    monkeypatch.setattr(srv, "_get", _MockGet(_stats_response(n)))
    r = _payload(asyncio.run(_call(
        "price_reasonableness_check", labor_category="Help Desk Specialist Tier 1", proposed_rate=95,
    )))
    assert r.get("status") == "LOW_SAMPLE", r
    assert r["total_rates"] == n
    assert r["analysis"]["iqr_position"] is None
    assert r["analysis"]["vs_median"] is None
    assert r["analysis"]["z_score"] is None
    assert str(n) in r["message"] and "too small" in r["message"]
    assert r["percentiles"]["p50_median"] == 71.65  # stats still shown


def test_g2_price_check_twenty_rates_gets_verdict(monkeypatch):
    monkeypatch.setattr(srv, "_get", _MockGet(_stats_response(20)))
    r = _payload(asyncio.run(_call(
        "price_reasonableness_check", labor_category="Help Desk Specialist", proposed_rate=95,
    )))
    assert r.get("status") != "LOW_SAMPLE"
    assert r["analysis"]["iqr_position"] == "above P75 (high)"


@live
def test_live_g2_help_desk_tier_1_low_sample():
    api = _api("keyword=Help+Desk+Specialist+Tier+1&page=1&page_size=1&ordering=current_price&sort=asc")
    api_n = api["aggregations"]["wage_stats"]["count"]
    assert api_n < 20
    r = _payload(asyncio.run(_call(
        "price_reasonableness_check", labor_category="Help Desk Specialist Tier 1", proposed_rate=95,
    )))
    assert r["total_rates"] == api_n
    assert r["status"] == "LOW_SAMPLE"
    assert r["analysis"]["iqr_position"] is None


@live
def test_live_g2_help_desk_full_population_keeps_verdict():
    api = _api("keyword=Help+Desk+Specialist&page=1&page_size=1&ordering=current_price&sort=asc")
    r = _payload(asyncio.run(_call(
        "price_reasonableness_check", labor_category="Help Desk Specialist", proposed_rate=95,
    )))
    assert r["total_rates"] == api["aggregations"]["wage_stats"]["count"] > 1000
    assert r["analysis"]["iqr_position"] == "within IQR P25-P75 (typical)"


# ---------------------------------------------------------------------------
# G-6: vendor_rate_card counts rows as rows and reports distinct titles
# ---------------------------------------------------------------------------

def _card_with_titles(total: int, titles: list[tuple[str, int]], other: int) -> dict:
    body = _booz_pair_response()
    body["hits"]["total"] = {"value": total, "relation": "eq"}
    body["aggregations"]["vendor_name"]["buckets"][0]["doc_count"] = total
    body["aggregations"]["labor_category"] = {
        "buckets": [{"key": k, "doc_count": c} for k, c in titles],
        "sum_other_doc_count": other,
    }
    return body


def test_g6_vendor_rate_card_row_count_and_distinct_titles(monkeypatch):
    titles = [("ACQUISITION SPECIALIST, LEVEL I", 2), ("Program Manager", 2)]
    monkeypatch.setattr(srv, "_get", _MockGet(_card_with_titles(4, titles, 0)))
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz")))
    assert "total_categories" not in r
    assert r["total_rates"] == 4
    assert r["distinct_labor_categories"] == 2


def test_g6_distinct_titles_unknown_when_bucket_list_truncated(monkeypatch):
    titles = [(f"Title {i}", 2) for i in range(500)]
    monkeypatch.setattr(srv, "_get", _MockGet(_card_with_titles(1879, titles, 324)))
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz")))
    assert r["total_rates"] == 1879
    assert r["distinct_labor_categories"] is None
    assert r["distinct_labor_categories_min"] == 500


@live
def test_live_g6_vendor_rate_card_counts_match_api():
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="Accenture", page_size=3)))
    api = _api("search=vendor_name:" + r["vendor"].replace(" ", "+") + "&page=1&page_size=1&ordering=labor_category&sort=asc")
    assert r["total_rates"] == api["hits"]["total"]["value"]
    lc = api["aggregations"]["labor_category"]
    if lc.get("sum_other_doc_count", 0) == 0:
        assert r["distinct_labor_categories"] == len(lc["buckets"])
    else:
        assert r["distinct_labor_categories_min"] == len(lc["buckets"])


# ---------------------------------------------------------------------------
# G-9: the 2-sigma lower bound never goes below $0
# ---------------------------------------------------------------------------

def test_g9_negative_lower_bound_clamped(monkeypatch):
    body = _stats_response(27820, price=143.57)
    body["aggregations"]["wage_stats"]["std_deviation"] = 72.09
    body["aggregations"]["wage_stats"]["std_deviation_bounds"] = {"lower": -0.61, "upper": 287.75}
    monkeypatch.setattr(srv, "_get", _MockGet(body))
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="541611")))
    b = r["outlier_bounds_2sigma"]
    assert b["lower"] == 0
    assert b["lower_clamped_to_zero"] is True
    assert b["upper"] == 287.75


def test_g9_positive_lower_bound_unchanged(monkeypatch):
    body = _stats_response(298, price=167.08)
    body["aggregations"]["wage_stats"]["std_deviation_bounds"] = {"lower": 74.96, "upper": 259.2}
    monkeypatch.setattr(srv, "_get", _MockGet(body))
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Senior Software Engineer")))
    assert r["outlier_bounds_2sigma"] == {"lower": 74.96, "upper": 259.2}


@live
def test_live_g9_sin_541611_lower_bound_not_negative():
    api = _api("filter=sin:541611&page=1&page_size=1&ordering=current_price&sort=asc")
    api_lower = api["aggregations"]["wage_stats"]["std_deviation_bounds"]["lower"]
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="541611", page_size=1)))
    b = r["outlier_bounds_2sigma"]
    assert b["lower"] >= 0
    if api_lower < 0:
        assert b["lower"] == 0 and b["lower_clamped_to_zero"] is True
    else:
        assert b["lower"] == api_lower


# ---------------------------------------------------------------------------
# G-12: suggest_contains says when GSA's 100-value list is cut off
# ---------------------------------------------------------------------------

def _suggest_body(n_values: int, other: int) -> dict:
    return {
        "hits": {"total": {"value": 539, "relation": "eq"}, "hits": []},
        "aggregations": {"labor_category": {
            "buckets": [{"key": f"Scrum Master {i}", "doc_count": 4} for i in range(n_values)],
            "sum_other_doc_count": other,
        }},
    }


def test_g12_suggest_contains_flags_truncated_list(monkeypatch):
    monkeypatch.setattr(srv, "_get", _MockGet(_suggest_body(100, 102)))
    r = _payload(asyncio.run(_call("suggest_contains", field="labor_category", term="Scrum Master")))
    assert r["truncated"] is True
    assert r["other_records"] == 102


def test_g12_suggest_contains_complete_list(monkeypatch):
    monkeypatch.setattr(srv, "_get", _MockGet(_suggest_body(3, 0)))
    r = _payload(asyncio.run(_call("suggest_contains", field="labor_category", term="Scrum Master")))
    assert r["truncated"] is False
    assert r["other_records"] == 0


@live
def test_live_g12_scrum_master_truncation_matches_api():
    api = _api("suggest-contains=labor_category:Scrum+Master&page=1&page_size=100&ordering=current_price&sort=asc")
    other = api["aggregations"]["labor_category"]["sum_other_doc_count"]
    r = _payload(asyncio.run(_call("suggest_contains", field="labor_category", term="Scrum Master")))
    assert r["other_records"] == other
    assert r["truncated"] is (other > 0)
    assert len(r["suggestions"]) == len(api["aggregations"]["labor_category"]["buckets"])


# ---------------------------------------------------------------------------
# G-7: an acronym miss points to the registered legal name
# ---------------------------------------------------------------------------

def test_g7_vendor_not_found_suggests_legal_name(monkeypatch):
    empty = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {"vendor_name": {"buckets": []}}}
    monkeypatch.setattr(srv, "_get", _MockGet(empty))
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="SAIC")))
    assert "No vendor found matching 'SAIC'" in r["error"]
    assert "legal name" in r["error"]


@live
def test_live_g7_saic_points_to_legal_name():
    api = _api("suggest-contains=vendor_name:SAIC&page=1&page_size=1&ordering=current_price&sort=asc")
    assert api["aggregations"]["vendor_name"]["buckets"] == []
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="SAIC")))
    assert "legal name" in r["error"]


# ---------------------------------------------------------------------------
# G-4: sin and security_clearance reach the workflow tools
# ---------------------------------------------------------------------------

def test_g4_price_check_passes_sin_and_clearance(monkeypatch):
    mock = _MockGet(_stats_response(59, price=204.30))
    monkeypatch.setattr(srv, "_get", mock)
    r = _payload(asyncio.run(_call(
        "price_reasonableness_check", labor_category="Senior Program Manager", proposed_rate=150,
        business_size="S", sin="541611", security_clearance="yes",
    )))
    qs = mock.calls[0]
    assert "filter=sin:541611" in qs, qs
    assert "filter=security_clearance:yes" in qs, qs
    assert "sin:541611" in r["filters_applied"]


def test_g4_igce_benchmark_passes_clearance(monkeypatch):
    mock = _MockGet(_stats_response(325, price=134.19))
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("igce_benchmark", labor_category="Systems Administrator", security_clearance="yes"))
    assert "filter=security_clearance:yes" in mock.calls[0], mock.calls[0]


@live
def test_live_g4_price_check_sin_population_matches_api():
    api = _api("keyword=Senior+Program+Manager&filter=business_size:S&filter=sin:541611&page=1&page_size=1&ordering=current_price&sort=asc")
    r = _payload(asyncio.run(_call(
        "price_reasonableness_check", labor_category="Senior Program Manager", proposed_rate=150,
        business_size="S", sin="541611",
    )))
    assert r["total_rates"] == api["aggregations"]["wage_stats"]["count"]


@live
def test_live_g4_igce_clearance_population_matches_api():
    api = _api("keyword=Systems+Administrator&filter=security_clearance:yes&page=1&page_size=1&ordering=current_price&sort=asc")
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Systems Administrator", security_clearance="yes")))
    assert r["total_rates"] == api["aggregations"]["wage_stats"]["count"]
    assert r["avg_rate"] == round(api["aggregations"]["wage_stats"]["avg"], 2)


# ---------------------------------------------------------------------------
# G-3: igce_benchmark shows which titles were pooled
# ---------------------------------------------------------------------------

def _pooled_body(titles: list[tuple[str, int]], other: int) -> dict:
    body = _stats_response(sum(c for _, c in titles) + other, price=167.08)
    body["aggregations"]["labor_category"] = {
        "buckets": [{"key": k, "doc_count": c} for k, c in titles],
        "sum_other_doc_count": other,
    }
    return body


def test_g3_igce_benchmark_lists_pooled_titles(monkeypatch):
    titles = [("Senior Software Engineer", 175)] + [(f"Senior Software Engineer {r}", 5) for r in "I II III IV V VI VII VIII VIII IX X XI".split()]
    monkeypatch.setattr(srv, "_get", _MockGet(_pooled_body(titles, 0)))
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Senior Software Engineer")))
    top = r["matched_titles"]["top"]
    assert top[0] == {"title": "Senior Software Engineer", "count": 175}
    assert len(top) == 10
    assert r["matched_titles"]["distinct"] == len(titles)
    assert "literal phrase" in r["_note"]


def test_g3_pooled_titles_distinct_unknown_when_truncated(monkeypatch):
    titles = [(f"Program Manager {i}", 3) for i in range(500)]
    monkeypatch.setattr(srv, "_get", _MockGet(_pooled_body(titles, 40)))
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Program Manager")))
    assert r["matched_titles"]["distinct"] is None
    assert r["matched_titles"]["distinct_min"] == 500


@live
def test_live_g3_pooled_titles_match_api():
    api = _api("keyword=Senior+Software+Engineer&page=1&page_size=1&ordering=current_price&sort=asc")
    lc = api["aggregations"]["labor_category"]
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Senior Software Engineer")))
    want = [{"title": b["key"], "count": b["doc_count"]} for b in lc["buckets"][:10]]
    assert r["matched_titles"]["top"] == want
    if lc.get("sum_other_doc_count", 0) == 0:
        assert r["matched_titles"]["distinct"] == len(lc["buckets"])


# ---------------------------------------------------------------------------
# G-8: sin_analysis lists the labor categories on the SIN
# ---------------------------------------------------------------------------

def test_g8_sin_analysis_lists_top_categories(monkeypatch):
    titles = [("Project Manager", 1070), ("Program Manager", 871), ("Technical Writer", 441)]
    body = _pooled_body(titles, 89084)
    monkeypatch.setattr(srv, "_get", _MockGet(body))
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="54151S")))
    lc = r["labor_categories"]
    assert lc["top"][0] == {"title": "Project Manager", "count": 1070}
    assert lc["distinct"] is None and lc["distinct_min"] == 3
    assert lc["records_in_titles_not_listed"] == 89084


@live
def test_live_g8_sin_54151S_categories_match_api():
    api = _api("filter=sin:54151S&page=1&page_size=1&ordering=current_price&sort=asc")
    agg = api["aggregations"]["labor_category"]
    r = _payload(asyncio.run(_call("sin_analysis", sin_code="54151S", page_size=1)))
    # On a SIN this large GSA's per-title counts wobble by a record or two
    # between identical calls (sharded terms aggregation), so compare titles
    # exactly and counts within 1%.
    want = {b["key"]: b["doc_count"] for b in agg["buckets"][:25]}
    got = {t["title"]: t["count"] for t in r["labor_categories"]["top"]}
    assert len(got) == 25
    shared = set(got) & set(want)
    assert len(shared) >= 23, (got, want)
    for k in shared:
        assert abs(got[k] - want[k]) <= max(2, want[k] * 0.01), (k, got[k], want[k])
    other = r["labor_categories"]["records_in_titles_not_listed"]
    assert abs(other - agg["sum_other_doc_count"]) <= agg["sum_other_doc_count"] * 0.01


# ---------------------------------------------------------------------------
# G-10: worksite counts in the statistics
# ---------------------------------------------------------------------------

def test_g10_stats_include_worksite_counts(monkeypatch):
    body = _stats_response(6613, price=146.59)
    body["aggregations"]["worksite"] = {"buckets": [
        {"key": "Customer_Facility", "doc_count": 3635},
        {"key": "Contractor_Facility", "doc_count": 2665},
        {"key": "Virtual", "doc_count": 313},
    ]}
    monkeypatch.setattr(srv, "_get", _MockGet(body))
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Systems Engineer")))
    assert r["worksite_breakdown"] == {"Customer_Facility": 3635, "Contractor_Facility": 2665, "Virtual": 313}


@live
def test_live_g10_systems_engineer_worksite_counts_match_api():
    api = _api("keyword=Systems+Engineer&page=1&page_size=1&ordering=current_price&sort=asc")
    want = {b["key"]: b["doc_count"] for b in api["aggregations"]["worksite"]["buckets"]}
    r = _payload(asyncio.run(_call("igce_benchmark", labor_category="Systems Engineer")))
    assert r["worksite_breakdown"] == want
    assert sum(want.values()) == r["total_rates"]
