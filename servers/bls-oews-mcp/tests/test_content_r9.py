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


# ---------------------------------------------------------------------------
# BLS-2: IGCE shows the sample behind the benchmark
# ---------------------------------------------------------------------------

def test_bls2_igce_shows_employment_and_rse():
    # Q7: Colorado Springs database administrators. BLS dt01 = 110,
    # dt02 = 19.5, dt05 = 9.4.
    data = _tool("igce_wage_benchmark", occ_code="15-1242", scope="metro", area_code="17820")
    assert data["reliability"] == {"employment": "110", "employment_rse": "19.5%", "mean_wage_rse": "9.4%"}
    assert "employment RSE 19.5%" in data["_reliability_warning"]
    assert "mean wage RSE" not in data["_reliability_warning"]


def test_bls2_no_warning_for_a_solid_estimate():
    # DC software developers: BLS dt01 = 69,060, dt02 = 3.2, dt05 = 1.0.
    data = _tool("igce_wage_benchmark", occ_code="15-1252", scope="metro", area_code="47900")
    assert data["reliability"] == {"employment": "69,060", "employment_rse": "3.2%", "mean_wage_rse": "1.0%"}
    assert "_reliability_warning" not in data
    assert "no_data" not in data


def test_bls2_wageless_cell_is_still_no_data():
    # DC emergency medicine physicians (29-1214): BLS publishes employment
    # 770 but every wage cell is "-" (footnote 5). Employment alone must not
    # make the IGCE look like it has benchmarks.
    data = _tool("igce_wage_benchmark", occ_code="29-1214", scope="metro", area_code="47900")
    assert data["no_data"] is True
    assert data["reliability"]["employment"] == "770"


# ---------------------------------------------------------------------------
# BLS-4: a wageless IGCE says what BLS did publish
# ---------------------------------------------------------------------------

def test_bls4_top_coded_igce_reports_employment_and_floor():
    # Q10: DC emergency medicine physicians. BLS: employment 770, every wage
    # "-" with footnote 5 (">= $115.00 per hour or $239,200 per year").
    data = _tool("igce_wage_benchmark", occ_code="29-1214", scope="metro", area_code="47900")
    reason = data["no_data_reason"]
    assert "BLS publishes no estimate" not in reason
    assert "employment (770)" in reason
    assert "equal to or greater than $115.00 per hour or $239,200 per year" in reason


def test_bls4_unreleased_igce_points_to_a_wider_area():
    # Q11: Bremerton (14740) information security analysts. BLS: employment
    # 70, every wage "-" with footnote 8 ("Estimate not released.").
    data = _tool("igce_wage_benchmark", occ_code="15-1212", scope="metro", area_code="14740")
    reason = data["no_data_reason"]
    assert "employment (70)" in reason
    assert "Estimate not released." in reason
    assert "scope='state'" in reason


# ---------------------------------------------------------------------------
# BLS-5: starter lists use BLS's names and carry the govcon basics
# ---------------------------------------------------------------------------

def test_bls5_common_metros_are_bls_area_names_and_include_govcon_metros():
    from bls_oews_mcp import snapshot

    metros = _tool("list_common_metros")["metros"]
    # oe.area: 26620 Huntsville, AL; 47260 Virginia Beach-Chesapeake-Norfolk,
    # VA-NC; 41700 San Antonio-New Braunfels, TX; 17820 Colorado Springs, CO;
    # 19430 Dayton-Kettering-Beavercreek, OH.
    for code in ("0026620", "0047260", "0041700", "0017820", "0019430"):
        assert code in metros
    for code, name in metros.items():
        assert name == snapshot.area_name(code), (code, name)


def test_bls5_common_soc_codes_are_bls_titles_and_include_15_1299():
    from bls_oews_mcp import snapshot

    socs = _tool("list_common_soc_codes")["soc_codes"]
    for code in ("151299", "151243", "172141", "131081", "131161"):
        assert code in socs
    for code, title in socs.items():
        assert title == snapshot.occupation_name(code), (code, title)


# ---------------------------------------------------------------------------
# BLS-6: get_wage_data names industry 999100 as BLS does
# ---------------------------------------------------------------------------

def test_bls6_industry_labels_match_bls_and_point_federal_it_to_15_1299():
    from bls_oews_mcp import snapshot

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    description = tools["get_wage_data"].description
    con = snapshot._connection()
    for code in ("541000", "541500", "999100"):
        (name,) = con.execute(
            "SELECT industry_name FROM industry WHERE industry_code = ?", (code,)
        ).fetchone()
        # oe.industry: 999100 = "Federal Executive Branch (OEWS Designation)".
        assert f"'{code}' ({name})" in description, (code, name)
    assert "(Federal Government)" not in description
    # BLS 999100: 15-1299 employment 86,390 vs 15-1252 employment 140.
    assert "15-1299" in description


# ---------------------------------------------------------------------------
# BLS-8: compare tools carry data_year at the top and keep the caller's order
# ---------------------------------------------------------------------------

def test_bls8_compare_tools_carry_data_year_and_keep_order():
    metros = _tool("compare_metros", occ_code="15-1232", metro_codes=["47900", "12580", "42660"], datatype="03")
    assert metros["data_year"] == "2025"
    # Already true before this fix: the server answers in the order asked
    # (a client that sorts JSON keys can show otherwise).
    assert list(metros["metros"]) == ["47900", "12580", "42660"]
    # BLS dt03: DC 38.84, Baltimore 32.19, Seattle 40.80.
    assert [v["numeric"] for v in metros["metros"].values()] == [38.84, 32.19, 40.8]
    occupations = _tool("compare_occupations", occ_codes=["151252", "151212"])
    assert occupations["data_year"] == "2025"
