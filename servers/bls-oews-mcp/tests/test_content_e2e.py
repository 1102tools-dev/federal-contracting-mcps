"""Realistic hourly-only IGCE regression: BLS footnote 4 is not no wage data."""
import asyncio
import pytest

from bls_oews_mcp.server import igce_wage_benchmark
from bls_oews_mcp.server import get_wage_data
from bls_oews_mcp.server import compare_occupations


def test_hourly_only_musicians_preserve_published_benchmarks():
    data = asyncio.run(igce_wage_benchmark("27-2042"))
    assert "no_data" not in data
    assert data["hourly_only"] is True
    mean = data["benchmarks"]["Annual Mean Wage"]
    assert mean["numeric_hourly"] == 60.46
    assert mean["hourly_burdened_low"] == "$108.83"
    assert mean["hourly_burdened_high"] == "$133.01"
    assert "numeric_annual" not in mean
    assert mean["annual_suppressed"] is True
    assert "suppressed" not in mean
    assert "Not published" in mean["annual"]
    assert data["benchmarks"]["Annual Median"]["numeric_hourly"] == 47.80
    assert "not annualized" in data["_annual_warning"]


def test_hourly_only_actors_followup():
    data = asyncio.run(igce_wage_benchmark("27-2011"))
    assert "no_data" not in data
    assert data["hourly_only"] is True
    for benchmark in data["benchmarks"].values():
        assert "numeric_annual" not in benchmark
    assert any("numeric_hourly" in b for b in data["benchmarks"].values())


def test_national_ratios_are_unavailable_measures_not_missing_occupation():
    with pytest.raises(ValueError, match="state/metro"):
        asyncio.run(get_wage_data("151252", datatypes=["16", "17"]))
    with pytest.raises(ValueError, match="state/metro"):
        asyncio.run(compare_occupations(["151252", "151212"], datatype="17"))
