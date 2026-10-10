"""Source-aware recovery for normal wage comparison questions."""
import asyncio

from bls_oews_mcp.server import compare_metros, compare_occupations, get_wage_data


def test_teacher_hourly_comparison_explains_annual_only_and_completes_followup():
    result = asyncio.run(compare_metros("252031", ["47900", "42660"], datatype="03"))
    reason = result["no_data_reason"]
    assert "retired" not in reason and "not surveyed" not in reason
    assert "do not generally work year-round" in reason
    assert "annual wage" in reason
    annual = asyncio.run(compare_metros("252031", ["47900", "42660"]))
    assert all(item["numeric"] is not None for item in annual["metros"].values())


def test_performer_annual_comparison_explains_hourly_only_and_completes_followup():
    result = asyncio.run(compare_occupations(["272011", "272042"]))
    reason = result["no_data_reason"]
    assert "retired" not in reason and "not surveyed" not in reason
    assert "do not generally work year-round" in reason
    assert "hourly wage" in reason
    hourly = asyncio.run(compare_occupations(["272011", "272042"], datatype="03"))
    assert [item["numeric"] for item in hourly["occupations"].values()] == [58.29, 60.46]


def test_topcoded_wage_reason_preserves_bls_floor_instead_of_claiming_absence():
    result = asyncio.run(get_wage_data("291214", scope="metro", area_code="47900"))
    reason = result["no_data_reason"]
    assert "BLS publishes no estimate" not in reason
    assert "equal to or greater than $115.00 per hour or $239,200 per year" in reason
