# SPDX-License-Identifier: MIT
"""Regression tests for 0.2.0 hardening fixes.

Goes through the MCPServer registry (mcp.call_tool) so pydantic type coercion
runs exactly as in production. The prior stress_test.py awaited raw coroutines
and bypassed the tool pipeline, missing most of the crash and silent-wrong-data
paths fixed here.
"""

from __future__ import annotations

import asyncio

import bls_oews_mcp.server as srv  # noqa: E402
from bls_oews_mcp import snapshot  # noqa: E402
from bls_oews_mcp.constants import OEWS_CURRENT_YEAR  # noqa: E402
from bls_oews_mcp.server import mcp  # noqa: E402


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
    # mcp>=2.0 returns CallToolResult; mcp 1.x returned (content, structured).
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------------------------------
# SOC code validation (consistent across all tools)
# ---------------------------------------------------------------------------

# 0.2.2 change: SOC codes now accept BOTH '15-1252' (standard BLS format)
# and '151252' (API format). The 0.2.0 / 0.2.1 "dash-rejected" behavior
# was a usability bug caught in the 0.2.2 live audit -- users paste SOCs
# directly from BLS publications which always write them dashed.


def test_get_wage_data_soc_with_dash_now_accepted():
    """Dashed SOC must pass validation and return the same wages."""
    dashed = _payload(asyncio.run(_call("get_wage_data", occ_code="15-1252")))
    plain = _payload(asyncio.run(_call("get_wage_data", occ_code="151252")))
    assert dashed["occ_code"] == "151252"
    assert dashed["wages"] == plain["wages"]
    assert dashed["wages"]["Annual Mean Wage"]["numeric"] > 100_000


def test_compare_metros_soc_with_dash_now_accepted():
    p = _payload(asyncio.run(_call(
        "compare_metros", occ_code="15-1252", metro_codes=["47900"]
    )))
    assert p["metros"]["47900"]["numeric"] > 100_000


def test_compare_occupations_soc_with_dash_now_accepted():
    p = _payload(asyncio.run(_call("compare_occupations", occ_codes=["15-1252", "13-1082"])))
    assert set(p["occupations"]) == {
        "151252 (Software Developers)", "131082 (Project Management Specialists)",
    }
    assert all(v["numeric"] for v in p["occupations"].values())


def test_soc_letters_rejected():
    asyncio.run(_call_expect_error("get_wage_data", "soc code like", occ_code="ABCDEF"))


def test_soc_fullwidth_digits_rejected():
    """Python .isdigit() accepts fullwidth digits; our regex doesn't."""
    asyncio.run(_call_expect_error("get_wage_data", "soc code like", occ_code="1512\uff15\u0032"))


def test_soc_control_chars_rejected():
    """0.2.2 regression: control chars were slipping through strip()."""
    for ch in ("\n", "\r", "\t", "\x00"):
        asyncio.run(_call_expect_error(
            "get_wage_data", "control characters", occ_code=f"15-1252{ch}"
        ))


def test_soc_too_short_rejected():
    asyncio.run(_call_expect_error("get_wage_data", "exactly 6 digits", occ_code="12345"))


def test_soc_accepts_int():
    """Users naturally pass SOC as int; we coerce."""
    p = _payload(asyncio.run(_call("get_wage_data", occ_code=151252)))
    assert p["occ_code"] == "151252"
    assert p["wages"]["Annual Mean Wage"]["numeric"] > 100_000


# ---------------------------------------------------------------------------
# Area code validation
# ---------------------------------------------------------------------------

def test_area_code_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", scope="state", area_code="VA"
    ))


def test_area_code_7char_non_digit_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", scope="state", area_code="abcdefg"
    ))


def test_area_code_accepts_int():
    """User passes area_code=51 as int."""
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", scope="state", area_code=51))
    except Exception as e:
        assert "only ASCII digits" not in str(e)
        assert "type" not in str(e).lower() or "bool" in str(e).lower()


def test_area_code_empty_string():
    asyncio.run(_call_expect_error(
        "get_wage_data", "required",
        occ_code="151252", scope="state", area_code=""
    ))


# ---------------------------------------------------------------------------
# Industry validation
# ---------------------------------------------------------------------------

def test_industry_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", industry="54100A"
    ))


def test_industry_whitespace_stripped():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", industry="   000000   "))
    except Exception as e:
        assert "only ASCII digits" not in str(e), f"whitespace not stripped: {e}"


# ---------------------------------------------------------------------------
# Datatype validation
# ---------------------------------------------------------------------------

def test_bogus_datatype_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "not a known OEWS datatype",
        occ_code="151252", datatypes=["99"]
    ))


def test_datatype_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", datatypes=["AA"]
    ))


def test_compare_metros_bogus_datatype():
    asyncio.run(_call_expect_error(
        "compare_metros", "not a known OEWS datatype",
        occ_code="151252", metro_codes=["47900"], datatype="99"
    ))


def test_empty_datatypes_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "datatypes cannot be empty",
        occ_code="151252", datatypes=[]
    ))


def test_datatype_accepts_int():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", datatypes=[4]))
    except Exception as e:
        assert "not a known" not in str(e) and "only ASCII" not in str(e)


# ---------------------------------------------------------------------------
# Year validation
# ---------------------------------------------------------------------------

def test_year_decimal_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "4-digit year",
        occ_code="151252", year="2024.5"
    ))


def test_year_whitespace_stripped():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", year="  2024  "))
    except Exception as e:
        assert "4-digit year" not in str(e)


def test_year_leading_zero_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "4-digit year",
        occ_code="151252", year="02024"
    ))


def test_year_too_old_rejected():
    # 0.2.2: BLS public API only serves the current year; historical years
    # now raise a clear "before the current OEWS release" error pointing
    # users to bls.gov/oes/tables.htm.
    asyncio.run(_call_expect_error(
        "get_wage_data", "before the current",
        occ_code="151252", year="1990"
    ))


def test_year_too_new_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "beyond the latest",
        occ_code="151252", year=2500
    ))


def test_year_historical_gets_clear_redirect():
    """Historical years must point users to the bulk download."""
    asyncio.run(_call_expect_error(
        "get_wage_data", "bls.gov/oes/tables",
        occ_code="151252", year=2023
    ))


def test_year_accepts_int():
    # Use the current OEWS year: a superseded year is rejected as historical,
    # which would exercise the wrong code path for an int-coercion test.
    p = _payload(asyncio.run(_call("get_wage_data", occ_code="151252", year=int(srv.OEWS_CURRENT_YEAR))))
    assert p["data_year"] == srv.OEWS_CURRENT_YEAR


def test_year_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "4-digit year",
        occ_code="151252", year="abcd"
    ))


# ---------------------------------------------------------------------------
# IGCE burden validation
# ---------------------------------------------------------------------------

def test_igce_burden_low_greater_than_high():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "must be <= burden_high",
        occ_code="151252", burden_low=3.0, burden_high=1.5
    ))


def test_igce_burden_negative():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "must be positive",
        occ_code="151252", burden_low=-1.0, burden_high=2.0
    ))


def test_igce_burden_zero():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "must be positive",
        occ_code="151252", burden_low=0, burden_high=0
    ))


def test_igce_burden_extreme():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "implausibly large",
        occ_code="151252", burden_high=50.0
    ))


# ---------------------------------------------------------------------------
# Response-shape defensive parsing (crash regressions)
# ---------------------------------------------------------------------------

def test_as_list_helper():
    from bls_oews_mcp.server import _as_list
    assert _as_list(None) == []
    assert _as_list([]) == []
    assert _as_list([1, 2]) == [1, 2]
    assert _as_list({"foo": "bar"}) == [{"foo": "bar"}]
    # Non-dict/list scalars return empty list (safer than wrapping)
    assert _as_list("string") == []
    assert _as_list(42) == []


def test_parse_value_handles_none():
    from bls_oews_mcp.server import _parse_value
    out = _parse_value(None, "04")
    assert out["numeric"] is None
    assert out["suppressed"] is True


def test_parse_value_strips_whitespace_special_values():
    """Round 1 finding: '  *  ' was marked Unparseable, should be Suppressed."""
    from bls_oews_mcp.server import _parse_value
    out = _parse_value("  *  ", "04")
    assert out["suppressed"] is True


def test_parse_value_empty_string_suppressed():
    from bls_oews_mcp.server import _parse_value
    out = _parse_value("", "04")
    assert out["suppressed"] is True


def test_extract_first_data_entry():
    from bls_oews_mcp.server import _extract_first_data_entry
    assert _extract_first_data_entry(None) is None
    assert _extract_first_data_entry({"data": None}) is None
    assert _extract_first_data_entry({"data": []}) is None
    assert _extract_first_data_entry({"data": [None, None]}) is None
    assert _extract_first_data_entry({"data": {"value": "1"}}) == {"value": "1"}
    assert _extract_first_data_entry({"data": [{"value": "1"}]}) == {"value": "1"}


def test_safe_footnotes_handles_weird_shapes():
    from bls_oews_mcp.server import _safe_footnotes
    assert _safe_footnotes({"footnotes": None}) == []
    assert _safe_footnotes({"footnotes": "single string"}) == ["single string"]
    assert _safe_footnotes({"footnotes": {"text": "dict-collapse"}}) == ["dict-collapse"]
    assert _safe_footnotes({"footnotes": [{"text": "a"}, {"text": ""}, {"nope": "x"}]}) == ["a"]


def test_series_id_from_handles_int():
    """Round 5: seriesID returned as int crashed on sid[-2:]."""
    from bls_oews_mcp.server import _series_id_from
    assert _series_id_from({"seriesID": 151252}) == "151252"
    assert _series_id_from({"seriesID": None}) == ""
    assert _series_id_from({}) == ""
    assert _series_id_from(None) == ""


def test_get_wage_data_with_dict_series_doesnt_crash():
    """Integration: fake BLS returning series-as-dict (XML collapse)."""
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": {"seriesID": series_ids[0], "data": [{"value": "144570", "year": 2024, "periodName": "Annual"}]}}}

    orig = S._query_series
    S._query_series = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert isinstance(result, dict)
        assert "wages" in result
    finally:
        S._query_series = orig


def test_get_wage_data_with_missing_value_key():
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": [{"seriesID": series_ids[0], "data": [{"year": "2024", "periodName": "Annual"}]}]}}

    orig = S._query_series
    S._query_series = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        # Should not crash; value=None flows through _parse_value
        assert isinstance(result, dict)
    finally:
        S._query_series = orig


def test_get_wage_data_with_none_series_entries():
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": [None, {"seriesID": series_ids[0], "data": [{"value": "100", "year": "2024", "periodName": "Annual"}]}]}}

    orig = S._query_series
    S._query_series = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert isinstance(result, dict)
    finally:
        S._query_series = orig


def test_get_wage_data_with_footnotes_as_dict():
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": [{"seriesID": series_ids[0], "data": [{"value": "144570", "year": "2024", "periodName": "Annual", "footnotes": {"text": "cap"}}]}]}}

    orig = S._query_series
    S._query_series = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert isinstance(result, dict)
    finally:
        S._query_series = orig


# ---------------------------------------------------------------------------
# National scope + area_code interaction
# ---------------------------------------------------------------------------

def test_national_scope_area_code_flagged():
    """area_code with scope=national should at least produce a _note."""
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": []}}

    orig = S._query_series
    S._query_series = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252", scope="national", area_code="51"))
        assert "_note" in result
        assert "area_code" in result["_note"]
    finally:
        S._query_series = orig


# ---------------------------------------------------------------------------
# Dedup across compare tools
# ---------------------------------------------------------------------------

def test_compare_metros_dedup():
    """Passing the same metro twice should only produce one series query."""
    import bls_oews_mcp.server as S

    captured: list[list[str]] = []
    async def capture_query(series_ids, start_year=None, end_year=None):
        captured.append(list(series_ids))
        return {"Results": {"series": []}}

    orig = S._query_series
    S._query_series = capture_query
    try:
        asyncio.run(S.compare_metros(occ_code="151252", metro_codes=["47900", "47900", "47900"]))
        assert len(captured) == 1
        assert len(captured[0]) == 1, f"expected dedup to 1 series, got {len(captured[0])}"
    finally:
        S._query_series = orig


def test_compare_occupations_dedup():
    import bls_oews_mcp.server as S

    captured: list[list[str]] = []
    async def capture_query(series_ids, start_year=None, end_year=None):
        captured.append(list(series_ids))
        return {"Results": {"series": []}}

    orig = S._query_series
    S._query_series = capture_query
    try:
        asyncio.run(S.compare_occupations(occ_codes=["151252", "151252", "151252"]))
        assert len(captured[0]) == 1, f"expected dedup, got {len(captured[0])}"
    finally:
        S._query_series = orig


# ---------------------------------------------------------------------------
# USER_AGENT
# ---------------------------------------------------------------------------

def test_user_agent_matches_version():
    from bls_oews_mcp.constants import USER_AGENT
    # Derived from package metadata so it cannot silently drift.
    from importlib.metadata import version as _pkg_version
    _expected = _pkg_version("bls-oews-mcp")
    assert USER_AGENT.endswith(f"/{_expected}"), (
        f"USER_AGENT {USER_AGENT!r} does not match packaged version {_expected!r}"
    )


# ---------------------------------------------------------------------------
# Datatype label map (round 7 finding: the round-1 "empirical" relabel was
# itself the bug). Official mapping live-verified 2026-08 by cross-footing
# hourly x 2080 against the annual percentiles: 06=$15.00 x 2080 = $31,200 =
# dt11 annual 10th; 08=$24.51 x 2080 = $50,980 = dt13 annual median.
# ---------------------------------------------------------------------------

def test_datatype_hourly_percentile_labels_official():
    from bls_oews_mcp.constants import DATATYPE_LABELS
    assert DATATYPE_LABELS["06"] == "Hourly 10th Percentile"
    assert DATATYPE_LABELS["07"] == "Hourly 25th Percentile"
    assert DATATYPE_LABELS["08"] == "Hourly Median"
    assert DATATYPE_LABELS["09"] == "Hourly 75th Percentile"
    assert DATATYPE_LABELS["10"] == "Hourly 90th Percentile"


def test_datatype_annual_percentile_labels_official():
    from bls_oews_mcp.constants import DATATYPE_LABELS
    assert DATATYPE_LABELS["11"] == "Annual 10th Percentile"
    assert DATATYPE_LABELS["12"] == "Annual 25th Percentile"
    assert DATATYPE_LABELS["13"] == "Annual Median"
    assert DATATYPE_LABELS["14"] == "Annual 75th Percentile"
    assert DATATYPE_LABELS["15"] == "Annual 90th Percentile"


def test_datatype_labels_have_all_hourly_codes():
    from bls_oews_mcp.constants import DATATYPE_LABELS, HOURLY_DATATYPES
    for code in ["03", "06", "07", "08", "09", "10"]:
        assert code in DATATYPE_LABELS, f"missing label for datatype {code}"
        assert code in HOURLY_DATATYPES, f"datatype {code} not routed as hourly"


def test_datatype_16_17_are_ratios_not_dollars():
    from bls_oews_mcp.constants import DATATYPE_LABELS, RATIO_DATATYPES
    from bls_oews_mcp.server import _parse_value
    assert DATATYPE_LABELS["16"] == "Employment per 1,000 Jobs"
    assert DATATYPE_LABELS["17"] == "Location Quotient"
    assert RATIO_DATATYPES == {"16", "17"}
    parsed = _parse_value("21.484", "16")
    assert parsed["numeric"] == 21.484
    assert "$" not in parsed["formatted"]


# ---------------------------------------------------------------------------
# Real values from the bundled release
# ---------------------------------------------------------------------------

_SOFTWARE_DEV_MEAN = "OEUN000000000000015125204"


def test_software_developers_national():
    payload = _payload(asyncio.run(_call("get_wage_data", occ_code="151252")))
    bundled = snapshot.lookup([_SOFTWARE_DEV_MEAN])[_SOFTWARE_DEV_MEAN][0]
    assert payload["wages"]["Annual Mean Wage"]["numeric"] == int(bundled)
    assert payload["data_year"] == OEWS_CURRENT_YEAR
    assert payload["source"]["kind"] == "bundled_bls_oews_files"


def test_igce_benchmark_software_devs():
    payload = _payload(asyncio.run(_call("igce_wage_benchmark", occ_code="151252")))
    assert payload["occ_title"] == "Software Developers"
    bundled = snapshot.lookup([_SOFTWARE_DEV_MEAN])[_SOFTWARE_DEV_MEAN][0]
    assert payload["benchmarks"]["Annual Mean Wage"]["numeric_annual"] == int(bundled)


# ---------------------------------------------------------------------------
# 0.2.1: extra='forbid' applied to every tool
# ---------------------------------------------------------------------------

def test_unknown_param_rejected():
    """Typo'd param names must raise, not silently drop.
    The default is extra='ignore' which lets silent-wrong-data through."""
    async def _run():
        try:
            await mcp.call_tool(
                "get_wage_data", {"occ_code": "15-1252", "bogus_typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 0.2.2: silent-wrong-data and single-digit FIPS fixes
# ---------------------------------------------------------------------------

def test_no_data_flag_on_fake_soc():
    """0.2.2: nonexistent SOC used to return 4 'suppressed' fields silently."""
    p = _payload(asyncio.run(_call("get_wage_data", occ_code="99-9999")))
    assert p.get("no_data") is True
    assert "SOC" in p["no_data_reason"]
    assert "not an occupation" in p["no_data_reason"]


def test_no_data_flag_on_fake_state():
    asyncio.run(_call_expect_error(
        "get_wage_data", "not a state/territory",
        occ_code="15-1252", scope="state", area_code="99",
    ))


def test_single_digit_state_fips_auto_padded():
    """CA FIPS = 6 (not 06). 0.2.2: auto-pad single-digit state FIPS."""
    p = _payload(asyncio.run(_call(
        "get_wage_data", occ_code="15-1252", scope="state", area_code="6",
    )))
    assert p["area_name"] == "California"
    assert p["wages"]["Annual Mean Wage"]["numeric"] > 100_000


def test_compare_metros_rejects_state_fips():
    """0.2.2: compare_metros must reject 2-digit state FIPS mixed in."""
    asyncio.run(_call_expect_error(
        "compare_metros", "state fips",
        occ_code="15-1252", metro_codes=["14460", "25"],
    ))


def test_igce_flags_unknown_soc_title():
    """0.2.2: igce must warn when the SOC isn't an OEWS occupation."""
    p = _payload(asyncio.run(_call("igce_wage_benchmark", occ_code="99-9999")))
    assert p.get("no_data") is True
    assert p.get("_title_warning")
