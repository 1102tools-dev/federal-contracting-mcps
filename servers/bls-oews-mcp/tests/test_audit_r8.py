# Round 8 (2026-08-18 super-cycle): live contract anchors, one call per test.
# The cross-foot canary is the guard for the round-7 money bug (hourly
# percentile labels shifted one slot, inflating Hourly Median 26%).
import asyncio
import json
import os
import re

import pytest

from .test_audit_r7 import _call, _payload

LIVE = os.environ.get("BLS_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires BLS_LIVE_TESTS=1 + BLS_API_KEY")


def _text(data) -> str:
    return json.dumps(data, default=str)


@live
@pytest.mark.live_smoke
def test_live_smoke_crossfoot_hourly_median_times_2080():
    # r7 headline guard: hourly median x 2080 must land within 12% of the
    # annual median for a big national SOC (they differ slightly by BLS
    # methodology, but a one-slot percentile shift throws this by ~26%).
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="15-1252")))
    txt = _text(data)
    hourly = re.search(r'[Hh]ourly.{0,40}?[Mm]edian.{0,40}?(\d+\.\d+)', txt)
    annual = re.search(r'[Aa]nnual.{0,40}?[Mm]edian.{0,40}?(\d{5,6})', txt)
    if hourly and annual:
        h, a = float(hourly.group(1)), float(annual.group(1))
        assert abs(h * 2080 - a) / a < 0.12, f"cross-foot broke: {h}*2080 vs {a}"


@live
@pytest.mark.live_smoke
def test_live_smoke_bad_soc_fails_loud():
    # The tool answers gracefully (no exception) but must SAY the series is
    # invalid/nonexistent, never return numbers for a fake SOC.
    try:
        data = _payload(asyncio.run(_call("get_wage_data", occ_code="99-9999")))
    except Exception:
        return  # loud rejection also acceptable
    txt = _text(data).lower()
    assert any(k in txt for k in ("does not exist", "no data", "invalid", "not found", "unknown")), txt[:200]


@live
@pytest.mark.live_smoke
def test_live_smoke_latest_year_detection_sane():
    data = _payload(asyncio.run(_call("detect_latest_year")))
    years = [int(y) for y in re.findall(r"20\d\d", _text(data))]
    assert years and max(years) >= 2024
