# SPDX-License-Identifier: MIT
"""Round 7 regression tests.

The headline round-7 finding: the GSA city endpoint does city-to-county-to-NSA
resolution server-side, so correct API-resolved answers (Washington ->
'District of Columbia', Penasco -> 'Taos') were being stamped with a false
'unmatched_nsa' WARNING. These tests pin the new api_resolved semantics plus
the OCONUS guards, month-value hygiene, zero-rate refusal, and honest
compare_locations labels.

Offline tests mock srv._get. Live tests gate on MCP_LIVE_TESTS=1 to match the
rest of this suite.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import gsa_perdiem_mcp.server as srv
from gsa_perdiem_mcp import __version__
from gsa_perdiem_mcp.server import mcp

LIVE = os.environ.get("MCP_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1 + PERDIEM_API_KEY")


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


def _entry(city: str, county: str = "N/A", meals: int = 68, months: dict | None = None):
    if months is None:
        months = {m: 110 for m in ("Jan", "Feb", "Mar")}
    return {
        "city": city,
        "county": county,
        "meals": meals,
        "standardRate": "false",
        "months": {"month": [{"short": k, "value": v} for k, v in months.items()]},
    }


def _resp(entries: list) -> dict:
    return {"rates": [{"rate": entries}]}


def _patch_get(monkeypatch, response, calls: list | None = None):
    async def fake_get(path):
        if calls is not None:
            calls.append(path)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(srv, "_get", fake_get)


# ---------------------------------------------------------------------------
# api_resolved semantics (finding 1)
# ---------------------------------------------------------------------------

def test_api_resolved_city_gets_neutral_note(monkeypatch):
    # Washington/DC: API returns the DC NSA, no Standard Rate row, no name match.
    _patch_get(monkeypatch, _resp([
        _entry("District of Columbia", county="Washington", meals=92,
               months={"Jan": 216, "Aug": 276}),
    ]))
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Washington", state="DC")))
    assert data["match_type"] == "api_resolved"
    assert data["matched_city"] == "District of Columbia"
    note = data["match_note"] or ""
    assert "WARNING" not in note
    assert "resolved" in note.lower()


def test_api_resolved_prefers_county_mentioning_query(monkeypatch):
    _patch_get(monkeypatch, _resp([
        _entry("Loudoun", county="Loudoun"),
        _entry("District of Columbia",
               county="Washington; Arlington; Alexandria", meals=92),
        _entry("Wallops Island", county="Accomack"),
    ]))
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Arlington", state="VA")))
    assert data["match_type"] == "api_resolved"
    assert data["matched_city"] == "District of Columbia"
    assert set(data["other_candidates"]) == {"Loudoun", "Wallops Island"}
    assert "Loudoun" in (data["match_note"] or "")


def test_standard_fallback_still_wins_when_standard_row_present(monkeypatch):
    _patch_get(monkeypatch, _resp([
        _entry("Standard Rate", county="N/A", meals=68, months={"Jan": 110}),
        _entry("Some Other NSA", county="Elsewhere"),
    ]))
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Nowhereville", state="MA")))
    assert data["match_type"] == "standard_fallback"
    assert data["is_standard_rate"] is True


def test_exact_match_unchanged(monkeypatch):
    _patch_get(monkeypatch, _resp([_entry("Boston / Cambridge", county="Suffolk")]))
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Boston / Cambridge", state="MA")))
    assert data["match_type"] == "exact"
    assert data["match_note"] is None


# ---------------------------------------------------------------------------
# compare_locations honest labels (finding 2)
# ---------------------------------------------------------------------------

def test_compare_locations_labels_by_query(monkeypatch):
    _patch_get(monkeypatch, _resp([
        _entry("District of Columbia", county="Washington; Arlington", meals=92),
    ]))
    data = _payload(asyncio.run(_call(
        "compare_locations",
        locations=[{"city": "Arlington", "state": "VA"}])))
    row = data["locations"][0]
    assert row["location"] == "Arlington, VA"
    assert row["matched_city"] == "District of Columbia"
    assert row["match_type"] == "api_resolved"
    assert row["is_standard_rate"] is False


# ---------------------------------------------------------------------------
# OCONUS guards (finding 3)
# ---------------------------------------------------------------------------

def test_state_rates_oconus_explains_instead_of_empty(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, _resp([]), calls=calls)
    data = _payload(asyncio.run(_call("lookup_state_rates", state="HI")))
    assert data["oconus"] is True
    assert "DoD" in data["error"]
    assert calls == [], "OCONUS states should not burn an API call"


def test_city_lookup_oconus(monkeypatch):
    _patch_get(monkeypatch, _resp([]))
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Anchorage", state="AK")))
    assert data["oconus"] is True
    assert "CONUS" in data["error"]


def test_estimate_oconus(monkeypatch):
    _patch_get(monkeypatch, _resp([]))
    data = _payload(asyncio.run(_call(
        "estimate_travel_cost", city="Honolulu", state="HI", num_nights=3)))
    assert data["oconus"] is True


def test_zip_empty_result_mentions_oconus(monkeypatch):
    _patch_get(monkeypatch, {"rates": []})
    data = _payload(asyncio.run(_call("lookup_zip_perdiem", zip_code="96813")))
    assert "Alaska" in data["error"]


# ---------------------------------------------------------------------------
# Month value hygiene (finding 5)
# ---------------------------------------------------------------------------

def test_null_month_values_do_not_poison_min():
    parsed = srv._parse_rate_entry({
        "city": "Testville",
        "meals": 68,
        "months": {"month": [
            {"short": "Jan", "value": None},
            {"short": "Feb", "value": 250},
        ]},
    })
    assert parsed["lodging_min"] == 250
    assert parsed["lodging_max"] == 250
    assert parsed["has_seasonal_variation"] is False
    assert parsed["months_without_data"] == ["Jan"]


def test_float_string_month_value_parses():
    parsed = srv._parse_rate_entry({
        "city": "Testville",
        "meals": 68,
        "months": {"month": [{"short": "Jan", "value": "107.0"}]},
    })
    assert parsed["lodging_by_month"]["Jan"] == 107


# ---------------------------------------------------------------------------
# estimate_travel_cost guards (finding 6)
# ---------------------------------------------------------------------------

def test_estimate_refuses_zero_lodging(monkeypatch):
    _patch_get(monkeypatch, _resp([
        _entry("Brokenville", months={"Jan": 0}),
    ]))
    data = _payload(asyncio.run(_call(
        "estimate_travel_cost", city="Brokenville", state="MA", num_nights=2)))
    assert "error" in data
    assert "refusing" in data["error"]


def test_estimate_reports_month_fallback_honestly(monkeypatch):
    _patch_get(monkeypatch, _resp([
        _entry("Testville", months={"Feb": 200, "Mar": 150}),
    ]))
    data = _payload(asyncio.run(_call(
        "estimate_travel_cost", city="Testville", state="MA",
        num_nights=2, travel_month="Jan")))
    assert data["rate_month"] == "MAX"
    assert data["nightly_lodging"] == 200
    assert "month_fallback_note" in data


def test_estimate_math_unchanged(monkeypatch):
    # 4 nights DC in a $216 month at $92 M&IE:
    # lodging 864; MIE = 92*3 + 69*2 = 414; total 1278.
    _patch_get(monkeypatch, _resp([
        _entry("District of Columbia", meals=92, months={"Mar": 216}),
    ]))
    data = _payload(asyncio.run(_call(
        "estimate_travel_cost", city="Washington", state="DC",
        num_nights=4, travel_month="Mar")))
    assert data["lodging_total"] == 864
    assert data["mie_total"] == 414.0
    assert data["grand_total"] == 1278.0
    assert data["rate_month"] == "Mar"


# ---------------------------------------------------------------------------
# travel_month exact matching (finding 4)
# ---------------------------------------------------------------------------

def test_travel_month_rejects_prefix_words():
    for bad in ("Mayhem", "Janitor", "Decadent", "Marbles"):
        with pytest.raises(ValueError, match="exact month"):
            srv._validate_travel_month(bad)


def test_travel_month_accepts_exact_forms():
    assert srv._validate_travel_month("May") == "May"
    assert srv._validate_travel_month("SEPTEMBER") == "Sep"
    assert srv._validate_travel_month("january") == "Jan"


# ---------------------------------------------------------------------------
# Fiscal year floor (finding 7)
# ---------------------------------------------------------------------------

def test_fiscal_year_floor_2020():
    assert srv._validate_fiscal_year(2020) == 2020
    for dead in (2015, 2019):
        with pytest.raises(ValueError, match="out of range"):
            srv._validate_fiscal_year(dead)


# ---------------------------------------------------------------------------
# serverInfo version (finding 14)
# ---------------------------------------------------------------------------

def test_server_reports_package_version():
    assert mcp.version == __version__
    assert __version__ != ""


# ---------------------------------------------------------------------------
# Live confirmations
# ---------------------------------------------------------------------------

@live
def test_live_washington_dc_no_false_warning():
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Washington", state="DC")))
    assert data["match_type"] in ("exact", "composite", "api_resolved")
    assert "WARNING" not in (data.get("match_note") or "")
    assert data["mie_daily"] >= 80
    assert data["is_standard_rate"] is False


@live
def test_live_arlington_resolves_to_dc_nsa():
    data = _payload(asyncio.run(_call(
        "lookup_city_perdiem", city="Arlington", state="VA")))
    assert data["match_type"] in ("exact", "composite", "api_resolved")
    assert "WARNING" not in (data.get("match_note") or "")


@live
def test_live_hawaii_oconus_guard():
    data = _payload(asyncio.run(_call("lookup_state_rates", state="HI")))
    assert data.get("oconus") is True
