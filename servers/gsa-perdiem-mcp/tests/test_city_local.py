# SPDX-License-Identifier: MIT
"""City lookups settled from bundled Census and GSA county data (FY2027).

Expected rate areas and M&IE come from the real GSA city responses captured in
tests/fixtures/gsa_city (see test_city_resolution.py); here GSA must not be
called at all.
"""

from __future__ import annotations

import asyncio

import pytest

import gsa_perdiem_mcp.server as srv


@pytest.fixture(autouse=True)
def _no_gsa(monkeypatch):
    async def forbidden(path):
        raise AssertionError(f"GSA called for {path}")

    monkeypatch.setattr(srv, "_get", forbidden)
    monkeypatch.setenv("PERDIEM_HOSTED", "1")


def _city(city, state):
    return asyncio.run(srv.lookup_city_perdiem(city, state, 2027))


@pytest.mark.parametrize("city,state,expected,match_type,mie", [
    ("McLean", "VA", "District of Columbia", "census_local", 92),
    ("Chester", "MA", "Springfield", "census_local", 74),
    ("Tysons", "VA", "District of Columbia", "census_local", 92),
    ("Bethesda", "MD", "District of Columbia", "census_local", 92),
    ("Fort Meade", "MD", "Annapolis", "census_local", 80),
    ("Abingdon", "VA", "Standard Rate", "standard_local", 68),
    ("Boise", "ID", "Boise", "exact", 86),
    ("Chicago", "IL", "Chicago", "exact", 92),
])
def test_bundled_city_matches_gsa_answer(city, state, expected, match_type, mie):
    r = _city(city, state)
    assert r["status"] == "resolved"
    assert r["matched_city"] == expected
    assert r["match_type"] == match_type
    assert r["mie_daily"] == mie
    assert r["source"]["kind"] != "gsa_per_diem_api"


def test_unknown_city_still_asks_gsa():
    with pytest.raises(AssertionError, match="GSA called"):
        _city("Xyzzyville", "VA")
