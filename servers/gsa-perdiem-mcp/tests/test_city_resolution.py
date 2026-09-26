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


def test_local_demo_key_mode_adds_access_note(monkeypatch):
    monkeypatch.delenv("PERDIEM_HOSTED")
    monkeypatch.delenv("PERDIEM_API_KEY", raising=False)
    r = _city("McLean", "VA")
    assert "DEMO_KEY" in r["access_note"]
