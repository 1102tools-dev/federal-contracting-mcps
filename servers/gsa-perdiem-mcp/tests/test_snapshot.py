# SPDX-License-Identifier: MIT
"""Bundled GSA snapshot: integrity, ZIP ambiguity, county definitions, M&IE.

These run offline against the data files shipped in the package. Any network
call fails the test, proving the bundled tools need no key.
"""

from __future__ import annotations

import asyncio
import hashlib
from importlib import resources

import pytest

import gsa_perdiem_mcp.server as srv
from gsa_perdiem_mcp import snapshot


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    async def forbidden(path):
        raise AssertionError(f"unexpected GSA API call: {path}")

    monkeypatch.setattr(srv, "_get", forbidden)


def _run(coro):
    return asyncio.run(coro)


def test_manifest_hashes_match_bundled_files():
    manifest = snapshot.manifest()
    years = snapshot.available_years()
    assert years == list(range(2021, max(years) + 1))
    data = resources.files("gsa_perdiem_mcp").joinpath("data")
    for fy in years:
        meta = manifest["fiscal_years"][str(fy)]
        blob = data.joinpath(meta["file"]).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == meta["file_sha256"]
        assert meta["zip"]["url"].startswith("https://www.gsa.gov/system/files/")
    places = data.joinpath("places.json.gz").read_bytes()
    assert hashlib.sha256(places).hexdigest() == manifest["places_sha256"]


@pytest.mark.parametrize("fy", snapshot.available_years())
def test_every_destination_is_complete(fy):
    year = snapshot.load_year(fy)
    tiers = {t["total"] for t in year.mie_tiers}
    assert year.standard["meals"] in tiers
    for d in year.destinations.values():
        assert len(d["months"]) == 12 and all(v > 0 for v in d["months"])
        assert d["meals"] in tiers


def test_zip_01011_is_ambiguous_with_both_candidates():
    r = _run(srv.lookup_zip_perdiem("01011", 2027))
    assert r["status"] == "ambiguous"
    assert "matched_city" not in r and "mie_daily" not in r
    got = {(c["destination"], c["mie_daily"]) for c in r["candidates"]}
    assert got == {("Northampton", 80), ("Springfield", 74)}
    assert r["source"]["kind"] == "bundled_gsa_files"


def test_zip_county_selects_candidate():
    r = _run(srv.lookup_zip_perdiem("01011", 2027, county="Hampden"))
    assert r["status"] == "resolved"
    assert r["matched_city"] == "Springfield"
    assert r["lodging_by_month"]["Oct"] == 131
    r = _run(srv.lookup_zip_perdiem("01054", 2027, county="Franklin"))
    assert r["status"] == "resolved" and r["is_standard_rate"] is True


def test_zip_county_answer_keeps_the_supplied_county():
    # P3-4 (content test 2026-10-10): GSA's FY2027 ZIP file lists 20120 under
    # Fairfax County, VA (District of Columbia) and Loudoun County, VA.
    r = _run(srv.lookup_zip_perdiem("20120", 2027, county="Fairfax"))
    assert r["status"] == "resolved" and r["matched_city"] == "District of Columbia"
    assert r["county_supplied"] == "Fairfax"
    assert "Fairfax" in r["county"] and r["county"] != "Fairfax"


def test_zip_invalid_county_is_reported():
    r = _run(srv.lookup_zip_perdiem("01011", 2027, county="Nowhere"))
    assert r["status"] == "invalid_county"


def test_zip_standard_plus_nsa_is_ambiguous():
    for z, nsa in (("01054", "Northampton"), ("84060", "Park City")):
        r = _run(srv.lookup_zip_perdiem(z, 2027))
        assert r["status"] == "ambiguous"
        assert {c["destination"] for c in r["candidates"]} == {"Standard Rate", nsa}


def test_zip_same_rate_areas_resolve():
    r = _run(srv.lookup_zip_perdiem("19003", 2027))
    assert r["status"] == "resolved"
    assert len(r["same_rate_areas"]) == 2


def test_zip_leading_zero_and_zip_plus_4():
    a = _run(srv.lookup_zip_perdiem("00501", 2027))
    b = _run(srv.lookup_zip_perdiem("00501-1234", 2027))
    assert a["status"] == b["status"] == "resolved"
    assert a["matched_city"] == "Riverhead / Ronkonkoma / Melville"


def test_zip_spanning_states_lists_states():
    r = _run(srv.lookup_zip_perdiem("10506", 2027))
    assert r["status"] == "ambiguous"
    assert {c["state"] for c in r["candidates"]} == {"CT", "NY"}


def test_zip_unknown_or_oconus():
    r = _run(srv.lookup_zip_perdiem("99501", 2027))
    assert "No rates found" in r["error"]
    assert "Alaska" in r["error"]


def test_state_rates_from_snapshot_match_gsa_state_list():
    r = _run(srv.lookup_state_rates("VA", 2027))
    # Same 10 areas GSA's API lists for Virginia (includes the DC area).
    assert sorted(x["city"] for x in r["rates"]) == [
        "Blacksburg", "Charlottesville", "District of Columbia", "Loudoun", "Lynchburg",
        "Richmond", "Roanoke", "Virginia Beach", "Wallops Island", "Williamsburg / York"]
    assert r["standard_rate"] == {"lodging": 113, "mie": 68}


def test_state_rates_show_season_months_for_seasonal_areas():
    # P3-2 (content test 2026-10-10). GSA FY2027 rate file: Virginia Beach
    # $129 Oct-May, $212 Jun-Aug, $129 Sep; Richmond is flat.
    rows = {x["city"]: x for x in _run(srv.lookup_state_rates("VA", 2027))["rates"]}
    vb = rows["Virginia Beach"]["lodging_by_month"]
    assert (vb["Oct"], vb["May"], vb["Jun"], vb["Jul"], vb["Aug"], vb["Sep"]) == (129, 129, 212, 212, 212, 129)
    assert rows["Richmond"]["seasonal"] is False and "lodging_by_month" not in rows["Richmond"]


def test_mie_breakdown_from_snapshot():
    r = _run(srv.get_mie_breakdown(2027))
    assert [t["total"] for t in r["tiers"]] == [68, 74, 80, 86, 92]
    t = r["tiers"][0]
    assert (t["breakfast"], t["lunch"], t["dinner"], t["incidental"], t["first_last_day_75pct"]) == (
        16, 19, 28, 5, 51.0)


def test_mie_breakdown_explains_the_fy2025_file_name():
    # P3-5 (content test 2026-10-10): GSA's "FY 2025 MIE Breakdown.docx" is
    # the current table; GSA's API conus/mie/2027 returns the same tiers.
    r = _run(srv.get_mie_breakdown(2027))
    assert r["source"]["mie_file_covers"] == "FY2025-present"
    assert "FY2025" in r["mie_note"] and "FY2027" in r["mie_note"]
    assert "mie_note" not in _run(srv.get_mie_breakdown(2025))


@pytest.mark.parametrize("state,city,county,expected", [
    ("AZ", "Sedona", "Yavapai", "Sedona"),
    ("AZ", "Cottonwood", "Yavapai", "Grand Canyon / Flagstaff"),
    ("CA", "Santa Monica", "Los Angeles", "Santa Monica"),
    ("CA", "Pasadena", "Los Angeles", "Los Angeles"),
    ("CA", "Edwards AFB", "Kern", "Los Angeles"),
    ("CA", "Bakersfield", "Kern", "Bakersfield / Ridgecrest"),
    ("MA", "Cambridge", "Middlesex", "Boston / Cambridge"),
    ("MA", "Lowell", "Middlesex", "Burlington / Woburn"),
    ("MA", "Falmouth", "Barnstable", "Falmouth"),
    ("MA", "Barnstable", "Barnstable", "Hyannis"),
    ("PA", "Hershey", "Dauphin", "Hershey"),
    ("PA", "Harrisburg", "Dauphin", "Harrisburg"),
    ("TX", "Grapevine", "Dallas", "Arlington / Fort Worth / Grapevine"),
    ("CT", "Stamford", "Fairfield", "Bridgeport / Danbury"),
    ("VA", "McLean", "Fairfax", "District of Columbia"),
    ("VA", "Richmond", "Richmond city", "Richmond"),
    ("VA", "Glen Allen", "Henrico", "Standard Rate"),
])
def test_county_definitions_and_carve_outs(state, city, county, expected):
    r = _run(srv.lookup_city_perdiem(city, state, 2027, county=county))
    assert r["status"] == "resolved", r
    assert r["match_type"] == "county"
    assert r["matched_city"] == expected
