# SPDX-License-Identifier: MIT
"""Live parity: bundled snapshot vs the GSA Per Diem API.

Gated on MCP_LIVE_TESTS=1 and a registered PERDIEM_API_KEY (DEMO_KEY's
~10 req/hr cannot cover the sample). Run before each release that changes
the bundled data:

    MCP_LIVE_TESTS=1 uv run pytest -q tests/test_live_parity.py
"""

from __future__ import annotations

import asyncio
import os

import pytest

import gsa_perdiem_mcp.server as srv
from gsa_perdiem_mcp import snapshot

LIVE = os.environ.get("MCP_LIVE_TESTS") == "1" and bool(os.environ.get("PERDIEM_API_KEY", "").strip())
pytestmark = pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1 + PERDIEM_API_KEY")

SAMPLE_PER_YEAR = 100
FIXED_ZIPS = ["01011", "01054", "00501", "22201", "84060", "10506", "19003", "02554", "91759", "93560"]


def _sample(year: snapshot.Year) -> list[str]:
    zips = sorted(year.zips)
    step = max(1, len(zips) // SAMPLE_PER_YEAR)
    return sorted(set(FIXED_ZIPS) | set(zips[::step]))


def _snapshot_set(year, zip5):
    out = set()
    for area, st in year.zip_areas(zip5):
        r = year.area_rate(area, st)
        out.add((r["destination"], r["meals"], tuple(r["lodging_by_month"][m] for m in year.months)))
    return out


def _api_set(response, months):
    out = set()
    for p in srv._parsed_entries(response):
        out.add((p["city"], p["meals"], tuple(p["lodging_by_month"].get(m, 0) for m in months)))
    return out


@pytest.mark.parametrize("fy", [2026, 2027])
def test_zip_candidates_match_api(fy):
    year = snapshot.load_year(fy)
    mismatches = []

    async def run():
        for z in _sample(year):
            api = _api_set(await srv._get(f"zip/{z}/year/{fy}"), year.months)
            snap = _snapshot_set(year, z)
            if api != snap:
                mismatches.append((z, sorted(snap), sorted(api)))

    asyncio.run(run())
    assert not mismatches, mismatches[:5]


@pytest.mark.parametrize("fy", [2027])
def test_state_lists_match_api(fy):
    year = snapshot.load_year(fy)

    async def run():
        bad = []
        for st in ("VA", "MD", "CA", "MA", "TX", "CT", "PA", "AZ"):
            api = {p["city"] for p in srv._parsed_entries(await srv._get(f"state/{st}/year/{fy}"))
                   if not p["is_standard_rate"]}
            snap = {year.destinations[i]["name"] for i in year.state_destination_ids(st)}
            if api != snap:
                bad.append((st, sorted(snap ^ api)))
        return bad

    assert asyncio.run(run()) == []


@pytest.mark.parametrize("city,state,expected", [
    ("McLean", "VA", "District of Columbia"),
    ("Chester", "MA", "Springfield"),
    ("Boise", "ID", "Boise"),
    ("Dallas", "TX", "Dallas"),
    ("Sedona", "AZ", "Sedona"),
    ("Cambridge", "MA", "Boston / Cambridge"),
    ("Hershey", "PA", "Hershey"),
    ("Abingdon", "VA", "Standard Rate"),
])
def test_city_corpus(city, state, expected):
    r = asyncio.run(srv.lookup_city_perdiem(city, state, 2027))
    assert r.get("status") == "resolved", r
    assert r["matched_city"] == expected


def test_unknown_city_unresolved():
    r = asyncio.run(srv.lookup_city_perdiem("Xyzzyville", "VA", 2027))
    assert r["status"] == "unresolved"
