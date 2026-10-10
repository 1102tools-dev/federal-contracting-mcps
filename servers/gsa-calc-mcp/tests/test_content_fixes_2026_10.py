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
