# SPDX-License-Identifier: MIT
"""City resolution against real GSA city-endpoint responses (FY2027).

Fixtures in tests/fixtures/gsa_city were captured from
api.gsa.gov/travel/perdiem/v2/rates/city/... on 2026-09-26 with DEMO_KEY.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

import gsa_perdiem_mcp.server as srv

FIXTURES = Path(__file__).parent / "fixtures" / "gsa_city"
_REAL_GET = srv._get


@pytest.fixture(autouse=True)
def _fixture_get(monkeypatch):
    async def fake_get(path):
        f = FIXTURES / (path.replace("/", "_").replace("%20", "20") + ".json")
        if not f.exists():
            raise AssertionError(f"no fixture for {path}")
        return json.loads(f.read_text())

    monkeypatch.setattr(srv, "_get", fake_get)
    monkeypatch.setenv("PERDIEM_HOSTED", "1")


def _city(city, state):
    return asyncio.run(srv.lookup_city_perdiem(city, state, 2027))


@pytest.mark.parametrize("city,state,expected,match_type,mie", [
    ("McLean", "VA", "District of Columbia", "census_tiebreak", 92),
    ("Chester", "MA", "Springfield", "census_tiebreak", 74),
    ("Tysons", "VA", "District of Columbia", "api_resolved", 92),
    ("Bethesda", "MD", "District of Columbia", "api_resolved", 92),
    ("Crystal City", "VA", "District of Columbia", "api_resolved", 92),
    ("Fort Meade", "MD", "Annapolis", "api_resolved", 80),
    ("Abingdon", "VA", "Standard Rate", "standard_fallback", 68),
    ("Boise", "ID", "Boise", "exact", 86),
])
def test_city_resolution(city, state, expected, match_type, mie):
    r = _city(city, state)
    assert r["status"] == "resolved"
    assert r["matched_city"] == expected
    assert r["match_type"] == match_type
    assert r["mie_daily"] == mie
    assert r["source"]["kind"] == "gsa_per_diem_api"


def test_chester_city_and_zip_agree():
    city = _city("Chester", "MA")
    zip_ = asyncio.run(srv.lookup_zip_perdiem("01011", 2027, county="Hampden"))
    assert city["matched_city"] == zip_["matched_city"] == "Springfield"


def test_unrecognized_city_is_unresolved_not_standard():
    r = _city("Xyzzyville", "VA")
    assert r["status"] == "unresolved"
    assert "matched_city" not in r
    assert "is_standard_rate" not in r


def test_estimate_refuses_unresolved_city():
    r = asyncio.run(srv.estimate_travel_cost("Xyzzyville", "VA", 3, fiscal_year=2027))
    assert r["status"] == "unresolved"
    assert "grand_total" not in r
    assert "no estimate" in r["error"]


def test_compare_lists_unresolved_without_rate():
    r = asyncio.run(srv.compare_locations(
        [{"city": "McLean", "state": "VA"}, {"city": "Xyzzyville", "state": "VA"}], 2027))
    rows = {row["location"]: row for row in r["locations"]}
    assert rows["McLean, VA"]["matched_city"] == "District of Columbia"
    assert rows["Xyzzyville, VA"]["status"] == "unresolved"
    assert "max_daily_total" not in rows["Xyzzyville, VA"]


def test_county_answers_without_api(monkeypatch):
    async def forbidden(path):
        raise AssertionError("county lookups for bundled years must not call the API")

    monkeypatch.setattr(srv, "_get", forbidden)
    r = asyncio.run(srv.lookup_city_perdiem("Chester", "MA", 2027, county="Hampden"))
    assert r["matched_city"] == "Springfield"
    assert r["source"]["kind"] == "bundled_gsa_files"


@pytest.mark.parametrize("today,month,fy", [
    (date(2026, 9, 26), "Nov", 2027),
    (date(2026, 9, 26), "Sep", 2026),
    (date(2026, 9, 26), "Jan", 2027),
    (date(2026, 10, 1), "Sep", 2027),
    (date(2026, 10, 1), "Oct", 2027),
    (date(2027, 3, 15), "Feb", 2028),
])
def test_fiscal_year_for_travel_month(today, month, fy):
    assert srv._fiscal_year_for_month(month, today) == fy


def test_hosted_city_results_have_no_key_language():
    for city, state in (("McLean", "VA"), ("Xyzzyville", "VA")):
        text = repr(_city(city, state))
        assert "DEMO_KEY" not in text and "PERDIEM_API_KEY" not in text


def test_local_city_lookup_without_key_asks_for_one(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.delenv("PERDIEM_HOSTED")
    monkeypatch.delenv("PERDIEM_API_KEY", raising=False)
    monkeypatch.setattr(srv, "_get", _REAL_GET)
    monkeypatch.setattr(srv, "_get_client", lambda: pytest.fail("no key, so no upstream request"))
    with pytest.raises(ToolError, match="set PERDIEM_API_KEY") as caught:
        _city("McLean", "VA")
    assert "DEMO_KEY" not in str(caught.value)
    zip_rate = asyncio.run(srv.lookup_zip_perdiem("22201", 2027))
    assert zip_rate["source"]["kind"] != "gsa_per_diem_api", "bundled lookups stay keyless"


# P2-1 (content test 2026-10-10). Milton and Gardiner were captured from the
# GSA API on 2026-10-10 with DEMO_KEY. GSA did not recognize Milton, OH: it
# returned all six Ohio rate areas plus the Standard Rate. "milton" is inside
# "Hamilton" but is not that rate area; Census puts Ohio's Miltons in counties
# that are all at the standard rate.
def test_town_inside_an_nsa_name_is_not_that_nsa():
    r = _city("Milton", "OH")
    assert r["status"] == "unresolved"
    assert "matched_city" not in r and "mie_daily" not in r
    suggestion = r["census_suggestion"]
    assert suggestion["destination"] == "Standard Rate"
    assert (suggestion["lodging_range"], suggestion["mie_daily"]) == ("$113/night", 68)


def test_compare_does_not_give_milton_hamiltons_rate():
    r = asyncio.run(srv.compare_locations([{"city": "Milton", "state": "OH"}], 2027))
    row = r["locations"][0]
    assert row["status"] == "unresolved"
    assert row.get("matched_city") != "Hamilton"


def test_whole_part_of_a_composite_name_still_matches():
    # GSA's name has no spaces around the second slash.
    r = _city("Gardiner", "MT")
    assert r["status"] == "resolved"
    assert r["matched_city"] == "Big Sky / West Yellowstone/Gardiner"
    assert r["match_type"] == "composite"


@pytest.mark.parametrize("query,name,match", [
    ("Milton", "Hamilton", False),
    ("Overland", "Kansas City / Overland Park", False),
    ("Park", "Kansas City / Overland Park", False),
    ("Fayette", "Lafayette / West Lafayette", False),
    ("Anton", "San Antonio", False),
    ("Columbia", "District of Columbia", False),
    ("Bedford", "Plymouth / Taunton / New Bedford", False),
    ("Overland Park", "Kansas City / Overland Park", True),
    ("west  lafayette", "Lafayette / West Lafayette", True),
    ("St Petersburg", "Tampa / St. Petersburg", True),
    ("Whitefish", "Kalispell/Whitefish", True),
])
def test_composite_match_uses_whole_parts(query, name, match):
    response = {"rates": [{"rate": [
        {"city": name, "county": "Somewhere", "meals": 80, "months": {"month": [{"short": "Jan", "value": 150}]}},
    ]}]}
    r = srv._resolve_city(response, query, "ZZ", 2027)
    assert (r.get("match_type") == "composite") is match
    best = srv._select_best_rate(response, query_city=query)
    assert (best["match_type"] == "composite") is match


# P3-1 / P3-6 (content test 2026-10-10). Sept 28 -> Oct 2, 2026 in San
# Francisco is 3 nights at the FY2026 Sep rate plus 1 at the FY2027 Oct rate;
# one travel_month prices all four at one rate, so the answer says so.
def test_estimate_says_every_night_uses_one_month():
    r = asyncio.run(srv.estimate_travel_cost(
        "San Francisco", "CA", 4, travel_month="Sep", fiscal_year=2026, county="San Francisco"))
    assert r["rate_month"] == "Sep"
    assert "All 4 nights" in r["rate_month_note"] and "each month" in r["rate_month_note"]
    one = asyncio.run(srv.estimate_travel_cost(
        "San Francisco", "CA", 1, travel_month="Sep", fiscal_year=2026, county="San Francisco"))
    assert "rate_month_note" not in one
    peak = asyncio.run(srv.estimate_travel_cost("San Francisco", "CA", 4, fiscal_year=2026, county="San Francisco"))
    assert "rate_month_note" not in peak


def test_estimate_flags_long_term_stays():
    r = asyncio.run(srv.estimate_travel_cost("San Antonio", "TX", 30, fiscal_year=2027, county="Bexar"))
    assert r["travel_days"] == 31
    assert "301-11.22" in r["long_term_note"]
    short = asyncio.run(srv.estimate_travel_cost("San Antonio", "TX", 29, fiscal_year=2027, county="Bexar"))
    assert "long_term_note" not in short


def test_estimate_cites_the_current_ftr_section():
    # FTR Case 2025-05 (90 FR 56893, Dec. 8, 2025) moved the 75% first/last
    # day rule to 41 CFR 301-11.20; 301-11.101 no longer exists.
    doc = srv.estimate_travel_cost.__doc__
    assert "301-11.20" in doc and "301-11.101" not in doc
