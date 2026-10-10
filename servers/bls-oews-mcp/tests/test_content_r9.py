# SPDX-License-Identifier: MIT
"""Round 9 (2026-10-10 content test): BLS-1 to BLS-9.

Each test reproduces a finding against the bundled release and checks the
answer against the value BLS publishes in oe.data.0.Current (May 2025,
SHA-256 09879508...3370b), quoted in the comments.
"""

from __future__ import annotations

import asyncio

import bls_oews_mcp.server as srv
from bls_oews_mcp.constants import OEWS_RELEASE_NAME
from bls_oews_mcp.server import mcp


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


def _tool(name: str, **kwargs):
    return _payload(asyncio.run(mcp.call_tool(name, kwargs)))


# ---------------------------------------------------------------------------
# BLS-1: the IGCE says which month the wages describe and to escalate them
# ---------------------------------------------------------------------------

def test_bls1_igce_states_wage_period_beside_burdened_rates():
    # Q5 repro: help desk (15-1232), Virginia Beach-Norfolk (47260).
    data = _tool("igce_wage_benchmark", occ_code="15-1232", scope="metro", area_code="47260")
    assert data["wage_period"] == OEWS_RELEASE_NAME == "May 2025"  # oe.release: 2025A01 May 2025
    assert data["_escalation_note"].startswith("May 2025 wages; escalate to the period of performance")
    keys = list(data)
    assert keys.index("wage_period") < keys.index("benchmarks") < keys.index("_escalation_note")


def test_bls1_wage_period_comes_from_the_release(monkeypatch):
    monkeypatch.setattr(srv, "OEWS_RELEASE_NAME", "May 2031")
    data = _tool("igce_wage_benchmark", occ_code="151252")
    assert data["wage_period"] == "May 2031"
    assert data["_escalation_note"].startswith("May 2031 wages; escalate to the period of performance")


# ---------------------------------------------------------------------------
# BLS-7: IGCE hourly figures are BLS's published hourly wages
# ---------------------------------------------------------------------------

def test_bls7_igce_uses_published_hourly_wages():
    # Q5: Norfolk help desk 10th percentile. BLS dt06 = 19.01 (annual
    # 39,530 / 2080 = 19.0048 -> 19.00 was shown).
    data = _tool("igce_wage_benchmark", occ_code="15-1232", scope="metro", area_code="47260")
    tenth = data["benchmarks"]["Annual 10th Percentile"]
    assert tenth["annual"] == "$39,530"
    assert tenth["hourly_base"] == "$19.01"
    assert tenth["numeric_hourly"] == 19.01
    assert tenth["hourly_burdened_low"] == "$34.22"  # 19.01 x 1.8
    # Q38: Colorado Springs database architects mean. BLS dt03 = 64.14
    # (annual 133,400 / 2080 = 64.13 was shown).
    data = _tool("igce_wage_benchmark", occ_code="15-1243", scope="metro", area_code="17820")
    assert data["benchmarks"]["Annual Mean Wage"]["hourly_base"] == "$64.14"


def test_bls7_annual_only_still_derives_hourly_and_warns():
    # Secondary teachers (25-2031): BLS hourly is "-" (footnote 4); annual
    # mean 76,320 / 2080 = 36.69.
    data = _tool("igce_wage_benchmark", occ_code="25-2031")
    assert data["annual_only"] is True
    assert data["benchmarks"]["Annual Mean Wage"]["hourly_base"] == "$36.69"


# ---------------------------------------------------------------------------
# BLS-3: IGCE carries the 25th and 75th percentiles
# ---------------------------------------------------------------------------

def test_bls3_igce_has_25th_and_75th_percentiles():
    # Q7: Colorado Springs database administrators (15-1242). BLS dt12 =
    # 84,850, dt07 = 40.80, dt14 = 160,330, dt09 = 77.08.
    data = _tool("igce_wage_benchmark", occ_code="15-1242", scope="metro", area_code="17820")
    bench = data["benchmarks"]
    assert list(bench) == [
        "Annual Mean Wage", "Annual 10th Percentile", "Annual 25th Percentile",
        "Annual Median", "Annual 75th Percentile", "Annual 90th Percentile",
    ]
    assert (bench["Annual 25th Percentile"]["annual"], bench["Annual 25th Percentile"]["hourly_base"]) == ("$84,850", "$40.80")
    assert (bench["Annual 75th Percentile"]["annual"], bench["Annual 75th Percentile"]["hourly_base"]) == ("$160,330", "$77.08")
