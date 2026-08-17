# SPDX-License-Identifier: MIT
"""Round 7 regression tests: the audit that fixed the datatype label shift.

Offline tests mock _query_bls and go through mcp.call_tool so pydantic
coercion runs as in production. Live tests (BLS_LIVE_TESTS=1 + BLS_API_KEY)
pin the official datatype semantics against production BLS data via the
2080 cross-foot invariant: each hourly percentile x 2080 must equal the
matching annual percentile. If BLS ever remaps datatype codes, the live
canary fails loudly instead of letting labels drift again.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import bls_oews_mcp.server as srv
from bls_oews_mcp.server import mcp

LIVE = os.environ.get("BLS_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires BLS_LIVE_TESTS=1 + BLS_API_KEY")


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


async def _call_expect_error(name: str, match: str, **kwargs):
    try:
        await mcp.call_tool(name, kwargs)
    except Exception as e:
        assert match.lower() in str(e).lower(), f"expected {match!r} in error, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


def _series(sid: str, value, year: str = "2025", footnotes: list[str] | None = None):
    entry = {
        "year": year,
        "period": "A01",
        "periodName": "Annual",
        "value": value,
        "footnotes": [{"text": t} for t in footnotes] if footnotes else [{}],
    }
    return {"seriesID": sid, "data": [entry]}


def _canned(series: list, messages: list | None = None):
    return {
        "status": "REQUEST_SUCCEEDED",
        "message": messages or [],
        "Results": {"series": series},
    }


def _patch_query(monkeypatch, response=None, capture: list | None = None):
    async def fake_query(series_ids, start_year=None, end_year=None, *, latest=False):
        if capture is not None:
            capture.append(
                {"series_ids": list(series_ids), "start_year": start_year, "latest": latest}
            )
        out = response(series_ids) if callable(response) else response
        if out is None:
            out = _canned([])
        # Mirror the real _query_bls: surface REQUEST_SUCCEEDED diagnostics.
        msgs = [str(m) for m in out.get("message", []) if m]
        if msgs and out.get("status") == "REQUEST_SUCCEEDED":
            out["_messages"] = msgs
        return out

    monkeypatch.setattr(srv, "_query_bls", fake_query)


def _echo_all(value: str = "50.00"):
    def build(series_ids):
        return _canned([_series(sid, value) for sid in series_ids])

    return build


# ---------------------------------------------------------------------------
# Datatype semantics (findings 1-3)
# ---------------------------------------------------------------------------

def test_datatype_06_requestable(monkeypatch):
    _patch_query(monkeypatch, response=_echo_all("15.00"))
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="151252", datatypes=["06"])))
    entry = data["wages"]["Hourly 10th Percentile"]
    assert entry["numeric"] == 15.00
    assert entry["formatted"] == "$15.00/hr"


def test_datatype_08_routes_as_hourly_median(monkeypatch):
    _patch_query(monkeypatch, response=_echo_all("24.51"))
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="151252", datatypes=["08"])))
    entry = data["wages"]["Hourly Median"]
    assert entry["numeric"] == 24.51
    assert entry["formatted"] == "$24.51/hr"


def test_datatype_16_formats_as_ratio(monkeypatch):
    _patch_query(monkeypatch, response=_echo_all("21.484"))
    data = _payload(
        asyncio.run(
            _call(
                "get_wage_data",
                occ_code="151252",
                scope="state",
                area_code="51",
                datatypes=["16"],
            )
        )
    )
    entry = data["wages"]["Employment per 1,000 Jobs"]
    assert entry["numeric"] == 21.484
    assert "$" not in entry["formatted"]


# ---------------------------------------------------------------------------
# Suppression formatting (finding 5)
# ---------------------------------------------------------------------------

def test_unpublished_cell_not_labeled_capped(monkeypatch):
    note = "Wages for some occupations that do not generally work year-round"

    def build(series_ids):
        return _canned([_series(sid, "-", footnotes=[note]) for sid in series_ids])

    _patch_query(monkeypatch, response=build)
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="532011", datatypes=["03"])))
    formatted = data["wages"]["Hourly Mean Wage"]["formatted"]
    assert formatted.startswith("[Not published]")
    assert note in formatted
    assert "Capped" not in formatted


# ---------------------------------------------------------------------------
# Response shape (findings 10-11): top-level year/period, seeded gaps
# ---------------------------------------------------------------------------

def test_data_year_and_period_top_level(monkeypatch):
    _patch_query(monkeypatch, response=_echo_all())
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="151252")))
    assert data["data_year"] == "2025"
    assert data["period"] == "Annual"
    assert "_data_year" not in data["wages"]
    assert "_period" not in data["wages"]


def test_missing_series_seeded_as_no_data(monkeypatch):
    def build(series_ids):
        # BLS omits every series except the first from the response.
        return _canned([_series(series_ids[0], "104000")])

    _patch_query(monkeypatch, response=build)
    data = _payload(
        asyncio.run(_call("get_wage_data", occ_code="151252", datatypes=["04", "13"]))
    )
    assert data["wages"]["Annual Mean Wage"]["numeric"] == 104000
    assert data["wages"]["Annual Median"]["formatted"] == "No data"
    assert "no_data" not in data


def test_fully_empty_response_flags_no_data(monkeypatch):
    _patch_query(monkeypatch, response=_canned([]))
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="151252")))
    assert data.get("no_data") is True
    assert "no_data_reason" in data


def test_api_messages_surfaced(monkeypatch):
    msg = "Series does not exist for Series OEUN000000000000099999904"
    _patch_query(monkeypatch, response=_canned([], messages=[msg]))
    data = _payload(asyncio.run(_call("get_wage_data", occ_code="999999")))
    assert data.get("_api_messages") == [msg]


# ---------------------------------------------------------------------------
# Normalized dedup (finding 7)
# ---------------------------------------------------------------------------

def test_compare_metros_collapses_normalized_dupes(monkeypatch):
    capture: list = []
    _patch_query(monkeypatch, response=_echo_all("60.00"), capture=capture)
    data = _payload(
        asyncio.run(
            _call(
                "compare_metros",
                occ_code="151252",
                metro_codes=["47900", "0047900", "12580"],
            )
        )
    )
    assert len(capture[0]["series_ids"]) == 2, "duplicate series should not be requested"
    assert "47900" in data["metros"], "first spelling wins the label"
    assert "0047900" not in data["metros"]
    assert "12580" in data["metros"]
    assert "0047900" in data.get("_note", "")


def test_compare_occupations_collapses_dashed_dupes(monkeypatch):
    capture: list = []
    _patch_query(monkeypatch, response=_echo_all("60.00"), capture=capture)
    data = _payload(
        asyncio.run(
            _call("compare_occupations", occ_codes=["151252", "15-1252", "131082"])
        )
    )
    assert len(capture[0]["series_ids"]) == 2
    assert "15-1252" in data.get("_note", "")
    assert len(data["occupations"]) == 2


# ---------------------------------------------------------------------------
# compare_occupations no_data flag (finding 6)
# ---------------------------------------------------------------------------

def test_compare_occupations_flags_all_no_data(monkeypatch):
    def build(series_ids):
        return _canned([_series(sid, "-") for sid in series_ids])

    _patch_query(monkeypatch, response=build)
    data = _payload(
        asyncio.run(_call("compare_occupations", occ_codes=["999998", "999999"]))
    )
    assert data.get("no_data") is True
    assert "no_data_reason" in data


# ---------------------------------------------------------------------------
# IGCE annual-only detection (finding 4)
# ---------------------------------------------------------------------------

def test_igce_requests_hourly_mean_and_flags_annual_only(monkeypatch):
    note = "Wages for some occupations that do not generally work year-round"
    annuals = {"04": "239200", "11": "137840", "13": "226600", "15": "473000"}

    def build(series_ids):
        out = []
        for sid in series_ids:
            dt = sid[-2:]
            if dt == "03":
                out.append(_series(sid, "-", footnotes=[note]))
            else:
                out.append(_series(sid, annuals.get(dt, "100000")))
        return _canned(out)

    capture: list = []
    _patch_query(monkeypatch, response=build, capture=capture)
    data = _payload(asyncio.run(_call("igce_wage_benchmark", occ_code="532011")))
    assert any(sid.endswith("03") for sid in capture[0]["series_ids"])
    assert data.get("annual_only") is True
    assert "_hourly_warning" in data
    assert data["benchmarks"]["Annual Mean Wage"]["numeric_annual"] == 239200


def test_igce_no_annual_only_flag_for_normal_occupation(monkeypatch):
    _patch_query(monkeypatch, response=_echo_all("104000"))
    data = _payload(asyncio.run(_call("igce_wage_benchmark", occ_code="151252")))
    assert "annual_only" not in data
    assert "_hourly_warning" not in data


# ---------------------------------------------------------------------------
# detect_latest_year via latest=true (finding 9)
# ---------------------------------------------------------------------------

def test_detect_latest_year_sends_latest_flag(monkeypatch):
    capture: list = []
    _patch_query(
        monkeypatch,
        response=_canned([_series("OEUN000000000000000000004", "83500", year="2025")]),
        capture=capture,
    )
    data = _payload(asyncio.run(_call("detect_latest_year")))
    assert capture[0]["latest"] is True
    assert capture[0]["start_year"] is None
    assert data["latest_year"] == "2025"
    assert data["newer_data_available"] is False
    assert "api_key" in data


def test_detect_latest_year_reports_newer(monkeypatch):
    _patch_query(
        monkeypatch,
        response=_canned([_series("OEUN000000000000000000004", "86000", year="2026")]),
    )
    data = _payload(asyncio.run(_call("detect_latest_year")))
    assert data["latest_year"] == "2026"
    assert data["newer_data_available"] is True


def test_detect_latest_year_reports_stale_default(monkeypatch):
    _patch_query(
        monkeypatch,
        response=_canned([_series("OEUN000000000000000000004", "80000", year="2024")]),
    )
    data = _payload(asyncio.run(_call("detect_latest_year")))
    assert data["latest_year"] == "2024"
    assert data["newer_data_available"] is False
    assert "OLDER" in data["message"]


# ---------------------------------------------------------------------------
# Geographic scope validation (finding 12)
# ---------------------------------------------------------------------------

def test_state_scope_rejects_bogus_fips():
    asyncio.run(
        _call_expect_error(
            "get_wage_data",
            "not a state/territory",
            occ_code="151252",
            scope="state",
            area_code="99",
        )
    )


def test_metro_scope_rejects_state_fips():
    asyncio.run(
        _call_expect_error(
            "get_wage_data",
            "looks like a 2-digit state FIPS",
            occ_code="151252",
            scope="metro",
            area_code="51",
        )
    )


def test_state_scope_rejects_msa_code():
    asyncio.run(
        _call_expect_error(
            "get_wage_data",
            "does not look like a state FIPS",
            occ_code="151252",
            scope="state",
            area_code="47900",
        )
    )


def test_compare_occupations_validates_state_fips():
    asyncio.run(
        _call_expect_error(
            "compare_occupations",
            "not a state/territory",
            occ_codes=["151252"],
            scope="state",
            area_code="99",
        )
    )


def test_territory_fips_accepted(monkeypatch):
    _patch_query(monkeypatch, response=_echo_all("30000"))
    data = _payload(
        asyncio.run(
            _call("get_wage_data", occ_code="151252", scope="state", area_code="72")
        )
    )
    assert "no_data" not in data


# ---------------------------------------------------------------------------
# Live canaries (the drift guards this audit wishes had existed earlier)
# ---------------------------------------------------------------------------

@live
def test_live_cross_foot_invariant():
    """Each hourly percentile x 2080 must equal its annual counterpart.

    This is the invariant that exposed the round-1 mislabeling: dt08 x 2080
    matched dt13 (annual median), proving dt08 is the hourly median.
    """
    data = _payload(
        asyncio.run(
            _call(
                "get_wage_data",
                occ_code="000000",
                datatypes=["06", "07", "08", "09", "10", "11", "12", "13", "14", "15"],
            )
        )
    )
    wages = data["wages"]
    pairs = [
        ("Hourly 10th Percentile", "Annual 10th Percentile"),
        ("Hourly 25th Percentile", "Annual 25th Percentile"),
        ("Hourly Median", "Annual Median"),
        ("Hourly 75th Percentile", "Annual 75th Percentile"),
        ("Hourly 90th Percentile", "Annual 90th Percentile"),
    ]
    for hourly_label, annual_label in pairs:
        hourly = wages[hourly_label]["numeric"]
        annual = wages[annual_label]["numeric"]
        assert hourly is not None and annual is not None
        assert abs(hourly * 2080 - annual) <= max(0.01 * annual, 25), (
            f"{hourly_label} x 2080 = {hourly * 2080} does not match "
            f"{annual_label} = {annual}; BLS datatype mapping may have moved"
        )


@live
def test_live_detect_latest_year_returns_real_year():
    data = _payload(asyncio.run(_call("detect_latest_year")))
    assert data["latest_year"].isdigit() and len(data["latest_year"]) == 4
    assert int(data["latest_year"]) >= 2025
