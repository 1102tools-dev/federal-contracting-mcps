# SPDX-License-Identifier: MIT
"""Snapshot builder: schema-drift detection and location-definition parsing."""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from gsa_perdiem_mcp._geo import parse_location_defined  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "build_snapshot", Path(__file__).resolve().parents[1] / "scripts" / "build_snapshot.py")
bs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bs)


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return bs.read_rows(buf.getvalue(), "test.xlsx")


FY26_RATES = [
    [None, "FY2026 Per Diem Rates - Effective October 1, 2025"],
    ["ID", "STATE", "DESTINATION", "COUNTY/LOCATION DEFINED", "SEASON BEGIN", "SEASON END",
     "FY26 Lodging Rate", "FY26 M&IE", None, None, None],
    [None, None, "Standard CONUS rate applies to all counties not specifically listed.", None, None, None, 110, 68],
    [1, "AL", "Birmingham", "Jefferson", "", "", 126, 80],
    [2, "AL", "Gulf Shores", "Baldwin", "October 1", "February 28", 134, 74],
    [2, "AL", "Gulf Shores", "Baldwin", "March 1", "May 31", 170, 74],
    [2, "AL", "Gulf Shores", "Baldwin", "June 1", "July 31", 222, 74],
    [2, "AL", "Gulf Shores", "Baldwin", "August 1", dt.datetime(2026, 9, 30), 170, 74],
]
FY27_RATES = [
    ["FY2027 Per Diem Rates - Effective October 1, 2026"],
    ["STATE", "DESTINATION", "COUNTY/LOCATION DEFINED", "SEASON BEGIN", "SEASON END",
     "FY27 Lodging Rate", "FY27 M&IE"],
    [None, "Standard CONUS rate applies to all counties not specifically listed.",
     None, "October 1, 2026", "September 30, 2027", 113, 68],
    ["AL", "Birmingham", "Jefferson", "October 1, 2026", "September 30, 2027", 135, 80],
]


def test_parses_fy26_layout_with_seasons():
    out = bs.parse_rate_workbook(_xlsx(FY26_RATES), 2026, "t")
    assert out["standard"] == {"lodging": 110, "meals": 68}
    gs = out["destinations"][("AL", "Gulf Shores")]["months"]
    assert gs["Oct"] == 134 and gs["Apr"] == 170 and gs["Jul"] == 222 and gs["Sep"] == 170


def test_parses_fy27_layout():
    out = bs.parse_rate_workbook(_xlsx(FY27_RATES), 2027, "t")
    assert out["standard"] == {"lodging": 113, "meals": 68}
    assert set(out["destinations"][("AL", "Birmingham")]["months"].values()) == {135}


def test_header_drift_fails_loudly():
    rows = [list(r) for r in FY27_RATES]
    rows[1][1] = "LOCATION"
    with pytest.raises(bs.BuildError, match="DESTINATION"):
        bs.parse_rate_workbook(_xlsx(rows), 2027, "t")


def test_wrong_fiscal_year_header_fails():
    with pytest.raises(bs.BuildError, match="FY28"):
        bs.parse_rate_workbook(_xlsx(FY27_RATES), 2028, "t")


def test_mid_month_season_fails():
    rows = [list(r) for r in FY26_RATES]
    rows[4][4:6] = ["October 1", "February 14"]
    with pytest.raises(bs.BuildError, match="mid-month"):
        bs.parse_rate_workbook(_xlsx(rows), 2026, "t")


def test_zip_workbook_rejects_lost_leading_zero():
    hdr = ["DestinationID", "Name", "County", "LocationDefined", "State", "ZIP", "FiscalYear",
           *bs.MONTHS, "Meals"]
    rows = _xlsx([hdr, [271, "Riverhead", "Suffolk County, NY", "Suffolk", "NY", 501, 2027, *([163] * 12), 86]])
    with pytest.raises(bs.BuildError, match="leading zeros"):
        bs.parse_zip_workbook(rows, 2027, "t")


def test_zip_workbook_accepts_fy26_header_spelling():
    hdr = ["DestinationID", "Name", "County", "LocationDefined", "State", "Zip", "FiscalYear",
           *bs.MONTHS, "Meals"]
    rows = _xlsx([hdr, [271, "Riverhead", "Suffolk County, NY", "Suffolk", "NY", "00501", 2026, *([155] * 12), 86]])
    out = bs.parse_zip_workbook(rows, 2026, "t")
    assert out[0]["zip"] == "00501"


@pytest.mark.parametrize("state,text,counties", [
    ("VA", "City of Charlottesville / Albemarle", ["VA|charlottesville city", "VA|albemarle"]),
    ("VA", "City limits of Roanoke", ["VA|roanoke city"]),
    ("MO", "St. Louis / St. Louis City / St. Charles", ["MO|st louis", "MO|st louis city", "MO|st charles"]),
    ("LA", "Orleans / Jefferson Parishes", ["LA|orleans", "LA|jefferson"]),
    ("MD", "Queen Anne", ["MD|queen annes"]),
])
def test_location_definitions(state, text, counties):
    definition, unparsed = parse_location_defined(state, text)
    assert unparsed == []
    assert definition["counties"] == counties


def test_unknown_sub_county_wording_requires_a_pin():
    _, unparsed = parse_location_defined("CO", "Denver less the city of Glendale")
    assert unparsed
