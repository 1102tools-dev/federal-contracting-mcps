# Round 10 regression tests: the 2026-08 paced live campaign (see
# tests/live_audit/ and testing.md "Round 10"). Offline tests replay
# live-verified shapes through the real pipeline; live_smoke tests re-stamp
# the campaign's anchors with a handful of paced calls.
import asyncio
import os

import httpx
import pytest

import sam_gov_mcp.server as server

from .test_audit_r9 import _call, _patch_get, _payload

LIVE = os.environ.get("SAM_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")


async def _expect_error(tool: str, fragment: str, **kwargs) -> None:
    try:
        await _call(tool, **kwargs)
    except Exception as e:
        assert fragment.lower() in str(e).lower(), (
            f"expected error containing {fragment!r}, got: {e}"
        )
        return
    raise AssertionError(f"{tool} accepted {kwargs!r}; expected error {fragment!r}")


# ---------------------------------------------------------------- offline

class _FakeClient:
    def __init__(self, resp: httpx.Response):
        self._resp = resp

    async def get(self, url):
        return self._resp


def test_bare_string_json_200_raises_not_silent_empty(monkeypatch):
    """Contract Awards can 200 with a bare JSON string error. Pre-r10 this
    normalized into totalRecords=0 (an error masquerading as no results)."""
    monkeypatch.setenv("SAM_API_KEY", "SAM-00000000-0000-0000-0000-000000000000")
    resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b'"Max value allowed for parameter \\"limit\\" is 100 "',
        request=httpx.Request("GET", "https://api.sam.gov/x"),
    )
    monkeypatch.setattr(server, "_get_client", lambda: _FakeClient(resp))
    asyncio.run(_expect_error(
        "search_contract_awards", "non-object JSON", fiscal_year=2024, limit=1
    ))


def test_registration_status_dead_values_rejected():
    # D and I return 0 records for every live query; the enum is now A/E only.
    for bad in ("D", "I", "A,E"):
        with pytest.raises(Exception):
            asyncio.run(_call("search_entities", registration_status=bad))


def test_fiscal_year_1970_now_accepted(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 2, "awardSummary": []}, calls)
    data = _payload(asyncio.run(_call(
        "search_contract_awards", fiscal_year=1970, limit=1)))
    assert data["totalRecords"] == 2
    assert calls and calls[-1]["params"].get("fiscalYear") == "1970"


def test_assistance_agency_code_three_digit_rejected():
    asyncio.run(_expect_error(
        "search_assistance_subawards", "four-digit", agency_code="075",
        from_date="2024-06-01", to_date="2024-06-30",
    ))


def test_assistance_agency_code_four_digit_passes(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "data": []}, calls)
    asyncio.run(_call(
        "search_assistance_subawards", agency_code=9700,
        from_date="2024-06-01", to_date="2024-06-30",
    ))
    assert calls and calls[-1]["params"].get("agencyCode") == "9700"


def test_vendor_responsibility_never_registered_but_excluded(monkeypatch):
    """Live-found edge: an actively excluded firm with NO entity registration
    in any population (samRegistered Yes or No). The check must flag both
    NOT_REGISTERED and the active exclusion. Shape mirrors a real captured
    v4 record: active = exclusionActions.listOfActions[].recordStatus."""
    entity_empty = {"totalRecords": 0, "entityData": []}
    exclusion_hit = {"totalRecords": 1, "excludedEntity": [{
        "exclusionIdentification": {"ueiSAM": "TESTUEI00001"},
        "exclusionDetails": {
            "classificationType": "Firm",
            "exclusionType": "Prohibition/Restriction",
            "exclusionProgram": "Reciprocal",
            "excludingAgencyName": "TREAS",
        },
        "exclusionActions": {"listOfActions": [{
            "recordStatus": "Active",
            "activateDate": "12-13-2006",
            "terminationDate": "12-12-2105",
            "terminationType": "Definite",
        }]},
    }]}

    async def fake_get(path, params, **kw):
        if "exclusions" in path:
            return exclusion_hit
        return entity_empty

    monkeypatch.setattr(server, "_get", fake_get)
    data = _payload(asyncio.run(_call(
        "vendor_responsibility_check", uei="TESTUEI00001")))
    assert "NOT_REGISTERED" in data["flags"]
    assert "ACTIVE_EXCLUSION_FOUND" in data["flags"]
    assert data["exclusion"]["activeCount"] == 1


def test_opportunities_offset_passthrough_documented_page_index(monkeypatch):
    # offset is a zero-based PAGE index upstream (live-verified); the tool
    # passes it through verbatim and the docstring carries the warning.
    calls: list = []
    _patch_get(monkeypatch, {"totalRecords": 0, "opportunitiesData": []}, calls)
    asyncio.run(_call(
        "search_opportunities", posted_from="05/01/2026", posted_to="06/30/2026",
        limit=2, offset=1))
    assert calls and calls[-1]["params"].get("offset") == "1"
    assert "PAGE INDEX" in server.search_opportunities.__doc__


# ---------------------------------------------------------------- live smoke

@live
@pytest.mark.live_smoke
def test_live_smoke_offset_is_page_index():
    w = {"posted_from": "05/01/2026", "posted_to": "06/30/2026"}
    sup = _payload(asyncio.run(_call("search_opportunities", limit=4, offset=0, **w)))
    pair = _payload(asyncio.run(_call("search_opportunities", limit=2, offset=1, **w)))
    sup_ids = [o.get("noticeId") for o in sup.get("opportunitiesData", [])]
    pair_ids = [o.get("noticeId") for o in pair.get("opportunitiesData", [])]
    if len(sup_ids) >= 4 and len(pair_ids) == 2:
        assert pair_ids == sup_ids[2:4], (
            "offset no longer behaves as a page index; re-verify pagination docs"
        )


@live
@pytest.mark.live_smoke
def test_live_smoke_fy1970_reachable():
    data = _payload(asyncio.run(_call(
        "search_contract_awards", fiscal_year=1970, limit=1)))
    assert data.get("totalRecords", 0) >= 1


@live
@pytest.mark.live_smoke
def test_live_smoke_sba_cert_populations():
    a6 = _payload(asyncio.run(_call(
        "search_entities", sba_business_type_code="A6", size=1)))
    xx = _payload(asyncio.run(_call(
        "search_entities", sba_business_type_code="XX", size=1)))
    # ~4,900 and ~4,600 at r10 time; tolerant floor guards against relabeling
    assert a6.get("totalRecords", 0) > 1000
    assert xx.get("totalRecords", 0) > 1000
