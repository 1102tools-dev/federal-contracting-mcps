# SPDX-License-Identifier: MIT
"""Round 9 regression tests (the suite-wide round-7 audit wave).

Headline finding: get_entity_reps_and_certs read the wrong JSON key casings
('farResponses' instead of the API's documented 'fARResponses', and
architectEngineerResponses from certifications instead of qualifications), so
the default summary mode returned empty clause lists for every entity. These
tests replay the documented Entity API response shape through the real tool
pipeline and pin the case-insensitive key resolution, plus the set-aside and
business-type code expansions, Z1-Z5, the bracketed-date rejection, zip/CGAC
zero-padding, and the PIID modification sort.

All offline (srv._get mocked). The five findings that need live SAM quota
(exclusion size cap, PSC searchBy casing, 364-day boundary, FY floor,
registration_status D/I) are exercised in the live suites once quota allows.
"""

from __future__ import annotations

import asyncio

import pytest

import sam_gov_mcp.server as srv
from sam_gov_mcp import __version__
from sam_gov_mcp.server import mcp


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


def _patch_get(monkeypatch, response, calls: list | None = None):
    async def fake_get(path, params, *, base_url=None):
        if calls is not None:
            calls.append({"path": path, "params": dict(params)})
        return response(path, dict(params)) if callable(response) else dict(response)

    monkeypatch.setattr(srv, "_get", fake_get)


# ---------------------------------------------------------------------------
# Finding 1: reps and certs key casing (documented API shape replay)
# ---------------------------------------------------------------------------

_DOCUMENTED_REPS_SHAPE = {
    "totalRecords": 1,
    "entityData": [
        {
            "entityRegistration": {"ueiSAM": "XRVFU3YRA2U5", "legalBusinessName": "Test Co"},
            "repsAndCerts": {
                "certifications": {
                    "fARResponses": [
                        {"provisionId": "FAR 52.212-3", "listOfAnswers": [{"a": 1}, {"a": 2}]},
                        {"provisionId": "FAR 52.219-1", "listOfAnswers": [{"a": 1}]},
                    ],
                    "dFARResponses": [
                        {"provisionId": "DFARS 252.204-7016", "listOfAnswers": [{"a": 1}]},
                    ],
                },
                "qualifications": {
                    "architectEngineerResponses": [
                        {"provisionId": "SF330 PART II", "listOfAnswers": [{"a": 1}]},
                    ],
                },
            },
        }
    ],
}


def test_reps_summary_reads_documented_mixed_case_keys(monkeypatch):
    _patch_get(monkeypatch, _DOCUMENTED_REPS_SHAPE)
    data = _payload(asyncio.run(_call(
        "get_entity_reps_and_certs", uei="XRVFU3YRA2U5")))
    rc = data["entityData"][0]["repsAndCerts"]["certifications"]
    assert [r["provisionId"] for r in rc["farResponses"]] == [
        "FAR 52.212-3", "FAR 52.219-1",
    ], "documented fARResponses casing must resolve"
    assert rc["farResponses"][0]["answerCount"] == 2
    assert [r["provisionId"] for r in rc["dfarsResponses"]] == ["DFARS 252.204-7016"]
    assert [r["provisionId"] for r in rc["architectEngineerResponses"]] == [
        "SF330 PART II",
    ], "architectEngineerResponses must be found under qualifications"


def test_reps_summary_tolerates_lowercase_keys_too(monkeypatch):
    shape = {
        "totalRecords": 1,
        "entityData": [{
            "repsAndCerts": {
                "certifications": {
                    "farResponses": [{"provisionId": "FAR 52.204-26", "listOfAnswers": []}],
                    "dfarsResponses": [],
                },
            },
        }],
    }
    _patch_get(monkeypatch, shape)
    data = _payload(asyncio.run(_call(
        "get_entity_reps_and_certs", uei="XRVFU3YRA2U5")))
    rc = data["entityData"][0]["repsAndCerts"]["certifications"]
    assert [r["provisionId"] for r in rc["farResponses"]] == ["FAR 52.204-26"]


def test_reps_clause_filter_matches_in_summary_mode(monkeypatch):
    _patch_get(monkeypatch, _DOCUMENTED_REPS_SHAPE)
    data = _payload(asyncio.run(_call(
        "get_entity_reps_and_certs", uei="XRVFU3YRA2U5",
        clause_filter=["52.219-1"])))
    rc = data["entityData"][0]["repsAndCerts"]["certifications"]
    assert [r["provisionId"] for r in rc["farResponses"]] == ["FAR 52.219-1"]
    assert rc["dfarsResponses"] == []


# ---------------------------------------------------------------------------
# Finding 2: set-aside codes
# ---------------------------------------------------------------------------

def test_buy_indian_and_las_set_asides_accepted(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "opportunitiesData": []}, calls)
    for code, wire in (("LAS", "LAS"), ("IEE", "IEE"), ("ISBEE", "ISBEE"),
                       ("BICiv", "BICiv"), ("biciv", "BICiv")):
        calls.clear()
        asyncio.run(_call(
            "search_opportunities",
            posted_from="01/01/2026", posted_to="06/01/2026",
            set_aside=code,
        ))
        assert calls[0]["params"]["typeOfSetAside"] == wire, (
            f"{code} should reach the wire as {wire}"
        )


def test_bogus_set_aside_still_rejected():
    asyncio.run(_call_expect_error(
        "search_opportunities", "not a valid code",
        posted_from="01/01/2026", posted_to="06/01/2026", set_aside="XYZ",
    ))


# ---------------------------------------------------------------------------
# Finding 3: business type pass-through
# ---------------------------------------------------------------------------

def test_fdd_business_types_pass_through(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "entityData": []}, calls)
    for code in ("NB", "A3", "1E", "A7", "M8", "nb"):
        calls.clear()
        asyncio.run(_call("search_entities", business_type_code=code))
        assert calls[0]["params"]["businessTypeCode"] == code.upper()


def test_sba_codes_still_redirect():
    asyncio.run(_call_expect_error(
        "search_entities", "sba_business_type_code",
        business_type_code="XX",
    ))


def test_malformed_business_type_rejected():
    for bad in ("Z", "ZZZ", "%%"):
        asyncio.run(_call_expect_error(
            "search_entities", "2-character", business_type_code=bad,
        ))


# ---------------------------------------------------------------------------
# Finding 4: purpose_of_registration Z1-Z5
# ---------------------------------------------------------------------------

def test_purpose_z3_z4_accepted(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "entityData": []}, calls)
    for code in ("Z3", "Z4"):
        calls.clear()
        asyncio.run(_call("search_entities", purpose_of_registration=code))
        assert calls[0]["params"]["purposeOfRegistrationCode"] == code


# ---------------------------------------------------------------------------
# Finding 7: bracketed ranges on single-date opportunity params
# ---------------------------------------------------------------------------

def test_bracketed_posted_from_rejected_cleanly():
    asyncio.run(_call_expect_error(
        "search_opportunities", "single MM/DD/YYYY",
        posted_from="[01/01/2025,06/01/2025]", posted_to="06/30/2025",
    ))


def test_bracketed_rdl_rejected_cleanly():
    asyncio.run(_call_expect_error(
        "search_opportunities", "single MM/DD/YYYY",
        posted_from="01/01/2026", posted_to="06/01/2026",
        response_deadline_from="[01/01/2026,02/01/2026]",
    ))


def test_bracketed_range_still_allowed_where_supported(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "awardSummary": []}, calls)
    asyncio.run(_call(
        "search_contract_awards",
        date_signed="[01/01/2025,06/01/2025]", limit=1,
    ))
    assert calls[0]["params"]["dateSigned"] == "[01/01/2025,06/01/2025]"


# ---------------------------------------------------------------------------
# Finding 12: leading-zero preservation
# ---------------------------------------------------------------------------

def test_int_zip_zero_padded(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "opportunitiesData": []}, calls)
    asyncio.run(_call(
        "search_opportunities",
        posted_from="01/01/2026", posted_to="06/01/2026", zip_code=6511,
    ))
    assert calls[0]["params"]["zip"] == "06511"


def test_int_cgac_zero_padded(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalrecords": 0, "orglist": []}, calls)
    asyncio.run(_call("search_federal_organizations", cgac=75))
    assert calls[0]["params"]["cgac"] == "075"


# ---------------------------------------------------------------------------
# Finding 10: PIID modification sort + truncation note
# ---------------------------------------------------------------------------

def test_piid_lookup_sorts_mods_and_flags_truncation(monkeypatch):
    response = {
        "totalRecords": 250,
        "awardSummary": [
            {"contractId": {"piid": "X", "modificationNumber": "P00002"}},
            {"contractId": {"piid": "X", "modificationNumber": "10"}},
            {"contractId": {"piid": "X", "modificationNumber": "2"}},
            {"contractId": {"piid": "X", "modificationNumber": "P00001"}},
        ],
    }
    _patch_get(monkeypatch, response)
    data = _payload(asyncio.run(_call("lookup_award_by_piid", piid="W912BV22P0112")))
    mods = [i["contractId"]["modificationNumber"] for i in data["awardSummary"]]
    assert mods == ["2", "10", "P00001", "P00002"], "numeric mods first, in numeric order"
    assert "_note" in data
    assert "250" in data["_note"]


def test_piid_lookup_no_note_when_complete(monkeypatch):
    response = {
        "totalRecords": 1,
        "awardSummary": [{"contractId": {"piid": "X", "modificationNumber": "0"}}],
    }
    _patch_get(monkeypatch, response)
    data = _payload(asyncio.run(_call("lookup_award_by_piid", piid="W912BV22P0112")))
    assert "_note" not in data


# ---------------------------------------------------------------------------
# Finding 11: version sync
# ---------------------------------------------------------------------------

def test_server_reports_package_version():
    assert mcp.version == __version__
    assert __version__ != ""
