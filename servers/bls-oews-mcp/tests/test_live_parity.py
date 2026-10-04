# SPDX-License-Identifier: MIT
"""Compare bundled values with the live BLS API (opt-in).

Run with BLS_LIVE_TESTS=1. Uses one keyless BLS v1 request (25 series, one
of the 25 requests v1 allows per day), so no API key is needed. CI runners
share IP addresses and with them that daily allowance, so when BLS_API_KEY
is set the same request goes to v2 with the key instead. The sample
is fixed and spans national, state, and metro cells, several datatypes,
an unreleased cell, and a top-coded wage.
"""

from __future__ import annotations

import os

import httpx
import pytest

from bls_oews_mcp import snapshot

pytestmark = pytest.mark.live_parity

SAMPLE = [
    "OEUN000000000000000000004",
    "OEUN000000000000015125201",
    "OEUN000000000000015125203",
    "OEUN000000000000015125204",
    "OEUN000000000000015125208",
    "OEUN000000000000013108213",
    "OEUN000000000000013111115",
    "OEUN000000000000029114111",
    "OEUN000000054150015125204",
    "OEUN000000099910013108204",
    "OEUS510000000000015125204",
    "OEUS510000000000015125216",
    "OEUS060000000000015125217",
    "OEUS110000000000013111104",
    "OEUS480000000000029114108",
    "OEUM004790000000015125201",
    "OEUM004790000000015125204",
    "OEUM004790000000013108213",
    "OEUM004266000000015125204",
    "OEUM001258000000015125215",
    "OEUM003562000000011102104",
    "OEUM003108000000015121104",
    "OEUM001018000000015125404",  # unreleased cell, footnote 8
    "OEUM001054000000029121515",  # top-coded wage, footnote 5
    "OEUN000000000000053201103",  # annual-only occupation (pilots)
]


def test_bundled_values_match_live_bls_api():
    query = {"seriesid": SAMPLE, "startyear": snapshot.data_year(), "endyear": snapshot.data_year()}
    key = os.environ.get("BLS_API_KEY", "").strip()
    if key:
        query["registrationkey"] = key
    r = httpx.post(
        f"https://api.bls.gov/publicAPI/{'v2' if key else 'v1'}/timeseries/data/",
        json=query,
        headers={"User-Agent": "bls-oews-mcp live parity test"},
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    assert body.get("status") == "REQUEST_SUCCEEDED", body.get("message")
    bundled = snapshot.lookup(SAMPLE)
    mismatches = []
    for series in body["Results"]["series"]:
        sid = series["seriesID"]
        entry = series["data"][0] if series["data"] else None
        live = None
        if entry:
            codes = sorted(f["code"] for f in entry.get("footnotes", []) if f and f.get("code"))
            live = (entry["value"].strip(), codes)
        mine = bundled[sid]
        ours = (mine[0], sorted(n["code"] for n in mine[1])) if mine else None
        if live != ours:
            mismatches.append((sid, live, ours))
    assert not mismatches, mismatches
