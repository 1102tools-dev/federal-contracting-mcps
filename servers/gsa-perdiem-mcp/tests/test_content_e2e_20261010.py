"""Content audit: reject misleading location input and split-trip totals."""
import asyncio

import pytest

from gsa_perdiem_mcp import server as srv


@pytest.mark.parametrize("zip_code", ["12345-garbage", "12345-1234-extra", "12345-", "12345-123", "１２３４５"])
def test_malformed_zip_is_rejected_before_lookup(zip_code):
    with pytest.raises(ValueError, match="5-digit US ZIP"):
        asyncio.run(srv.lookup_zip_perdiem(zip_code, 2027))


@pytest.mark.parametrize("city,state,county", [
    ("Cambridge", "MA", "Essex"),
    ("Santa Monica", "CA", "San Diego"),
    ("Sedona", "AZ", "Maricopa"),
])
def test_carveout_does_not_ignore_conflicting_county(city, state, county):
    r = asyncio.run(srv.lookup_city_perdiem(city, state, 2027, county))
    assert r["status"] == "invalid_county"
    assert "mie_daily" not in r
    assert "city or locality" in r["note"]
    estimate = asyncio.run(srv.estimate_travel_cost(city, state, 2, "Oct", 2027, county))
    assert "grand_total" not in estimate


def test_split_month_guidance_separates_lodging_from_trip_mie():
    def estimate(nights, month):
        return asyncio.run(srv.estimate_travel_cost(
            "Washington", "DC", nights, month, 2027, "District of Columbia"))
    first, second, whole = estimate(2, "Oct"), estimate(2, "Nov"), estimate(4, "Oct")
    # Each independent segment adds a calendar day; adding grand totals
    # overstates M&IE by half a daily allowance at each join.
    assert first["mie_total"] + second["mie_total"] - whole["mie_total"] == 46
    assert whole["mie_total"] == 414
    note = first["rate_month_note"]
    assert "lodging_total" in note and "once for the entire trip" in note
    assert "Do not add" in note and "grand_total" in note
    assert "each month's nights separately and add them" not in note


def test_comparison_keeps_each_rows_source():
    r = asyncio.run(srv.compare_locations([
        {"city": "Cambridge", "state": "MA", "county": "Middlesex"},
        {"city": "Cambridge", "state": "MA", "county": "Essex"},
    ], 2027))
    assert {row["status"] for row in r["locations"]} == {"resolved", "invalid_county"}
    for row in r["locations"]:
        assert row["source"]["kind"] == "bundled_gsa_files"
        assert row["source"]["fiscal_year"] == 2027
        assert "gsa.gov" in row["source"]["rate_file"]


def test_published_description_does_not_add_independent_trip_mie():
    tools = asyncio.run(srv.mcp.list_tools())
    description = next(t.description for t in tools if t.name == "estimate_travel_cost")
    assert "add only each month's lodging_total" in description
    assert "Calculate M&IE once across the actual trip days" in description
    assert "Do not add" in description and "grand_total" in description
    assert "month's nights separately and add them" not in description


def test_no_key_boston_county_lookup_estimate_and_comparison(monkeypatch):
    monkeypatch.delenv("PERDIEM_API_KEY", raising=False)
    async def no_network(*args, **kwargs):
        raise AssertionError("A bundled city-plus-county request must not call the API")
    monkeypatch.setattr(srv, "_get", no_network)
    city = dict(city="Boston", state="MA", county="Suffolk", fiscal_year=2027)
    lookup = asyncio.run(srv.lookup_city_perdiem(**city))
    assert lookup["lodging_by_month"]["Nov"] == 213 and lookup["mie_daily"] == 92
    estimate = asyncio.run(srv.estimate_travel_cost(**city, num_nights=4, travel_month="Nov"))
    assert estimate["grand_total"] == 1266 and estimate["source"]["kind"] == "bundled_gsa_files"
    comparison = asyncio.run(srv.compare_locations([
        {"city": "Boston", "state": "MA", "county": "Suffolk"},
        {"city": "Washington", "state": "DC", "county": "District of Columbia"},
    ], 2027))
    assert [row["max_daily_total"] for row in comparison["locations"]] == [457, 387]
    tools = asyncio.run(srv.mcp.list_tools())
    description = next(t.description for t in tools if t.name == "get_data_status")
    assert "supplied county for a bundled year also need no key or network call" in description
    assert "supplied county" in srv.get_data_status()["access_note"]
