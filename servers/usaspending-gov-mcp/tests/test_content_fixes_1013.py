# SPDX-License-Identifier: MIT
"""Regression suite for the 2026-10-10 content test fixes (1.0.13).

Each test names the finding it covers (findings-usaspending.md, U1-U13) and
pins behavior changed in 1.0.13. Offline: the HTTP plumbing is replaced with recorders that
return trimmed copies of the live API answers seen on 2026-10-10.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import usaspending_gov_mcp.server as srv
from usaspending_gov_mcp.server import mcp


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


@pytest.fixture
def fy2027(monkeypatch):
    """Pin 'today' to the content test date: FY2027 began ten days ago."""
    monkeypatch.setattr(srv, "_current_fiscal_year", lambda: 2027)
    return 2027


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


def _payload(result):
    if hasattr(result, "structured_content"):
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return result[1] if isinstance(result, tuple) else result


class _MockGet:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        r = self.response(path, params) if callable(self.response) else self.response
        return __import__("copy").deepcopy(r)


class _MockPost:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, json):
        self.calls.append((path, __import__("copy").deepcopy(json)))
        r = self.response(path, json) if callable(self.response) else self.response
        return __import__("copy").deepcopy(r)


# ===========================================================================
# U12 (P1): agency tools default to the last completed fiscal year
# ===========================================================================

# API answer for GET agency/097/obligations_by_award_category/ with no
# fiscal_year on 2026-10-10 (FY2027 to date): no year field at all.
DOD_OBLIGATIONS_FY2026 = {
    "total_aggregated_amount": 389671359952.77,
    "results": [{"category": "contracts", "aggregated_amount": 380016133917.28}],
}


def test_u12_obligations_by_award_category_defaults_to_last_completed_fy(monkeypatch, fy2027):
    mock = _MockGet(DOD_OBLIGATIONS_FY2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_agency_obligations_by_award_category", toptier_code="097")))
    assert mock.calls[-1][1].get("fiscal_year") == "2026"
    assert out["fiscal_year"] == 2026
    assert "last completed" in out["fiscal_year_note"]


def test_u12_obligations_by_award_category_echoes_explicit_year(monkeypatch, fy2027):
    mock = _MockGet(DOD_OBLIGATIONS_FY2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call(
        "get_agency_obligations_by_award_category", toptier_code="097", fiscal_year=2025,
    )))
    assert mock.calls[-1][1]["fiscal_year"] == "2025"
    assert out["fiscal_year"] == 2025
    assert "fiscal_year_note" not in out


@pytest.mark.parametrize("tool,endpoint", [
    ("get_agency_overview", "/api/v2/agency/097/"),
    ("get_agency_awards", "/api/v2/agency/097/awards/"),
    ("get_agency_sub_agencies", "/api/v2/agency/097/sub_agency/"),
    ("get_agency_federal_accounts", "/api/v2/agency/097/federal_account/"),
    ("get_agency_object_classes", "/api/v2/agency/097/object_class/"),
    ("get_agency_program_activities", "/api/v2/agency/097/program_activity/"),
    ("get_agency_obligations_by_award_category", "/api/v2/agency/097/obligations_by_award_category/"),
])
def test_u12_every_agency_tool_defaults_to_last_completed_fy(monkeypatch, fy2027, tool, endpoint):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call(tool, toptier_code="097")))
    path, params = mock.calls[-1]
    assert path == endpoint
    assert params.get("fiscal_year") == "2026", f"{tool} sent {params}"
    assert out["fiscal_year"] == 2026


def test_u12_current_fy_still_reachable(monkeypatch, fy2027):
    mock = _MockGet({"fiscal_year": 2027, "obligations": 1000000.0})
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_agency_awards", toptier_code="097", fiscal_year=2027)))
    assert mock.calls[-1][1]["fiscal_year"] == "2027"
    assert out["fiscal_year"] == 2027


def test_u12_docstrings_say_the_default():
    for name in (
        "get_agency_overview", "get_agency_awards", "get_agency_sub_agencies",
        "get_agency_federal_accounts", "get_agency_object_classes",
        "get_agency_program_activities", "get_agency_obligations_by_award_category",
    ):
        doc = " ".join(getattr(srv, name).__doc__.split())
        assert "last completed fiscal year" in doc, name


# ===========================================================================
# U11 (P1): get_state_profile gets a year, defaults to last completed FY
# ===========================================================================

# API answer for recipient/state/24/?year=2026 (trimmed): no year field.
MD_2026 = {
    "name": "Maryland", "code": "MD", "fips": "24", "type": "state",
    "total_prime_amount": 96666882297.68, "total_prime_awards": 117372,
}


def test_u11_state_profile_defaults_to_last_completed_fy(monkeypatch, fy2027):
    mock = _MockGet(MD_2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_state_profile", state_fips="24")))
    assert mock.calls[-1] == ("/api/v2/recipient/state/24/", {"year": "2026"})
    assert out["fiscal_year"] == 2026
    assert "year=2027" in out["fiscal_year_note"]


@pytest.mark.parametrize("year,sent,echo", [
    (2025, "2025", 2025), ("2024", "2024", 2024), ("all", "all", "all"), ("latest", "latest", "latest"),
])
def test_u11_state_profile_year_param(monkeypatch, fy2027, year, sent, echo):
    mock = _MockGet(MD_2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_state_profile", state_fips="24", year=year)))
    assert mock.calls[-1][1] == {"year": sent}
    assert out["fiscal_year"] == echo
    assert "fiscal_year_note" not in out


@pytest.mark.parametrize("bad", ["2007", "2028", "last", "20x6"])
def test_u11_state_profile_rejects_bad_year(fy2027, bad):
    with pytest.raises(Exception):
        asyncio.run(_call("get_state_profile", state_fips="24", year=bad))


def test_u11_state_profile_docstring_no_longer_promises_breakdowns():
    doc = " ".join(srv.get_state_profile.__doc__.split())
    assert "top agencies, top recipients" not in doc
    assert "last completed fiscal year" in doc


@live
@pytest.mark.live_smoke
def test_live_u11_u12_defaults_return_full_year():
    """Live: the no-year answers are the full last-completed-FY figures."""
    fy = srv._last_completed_fiscal_year()

    async def both():
        a = await _call("get_agency_obligations_by_award_category", toptier_code="097")
        b = await _call("get_state_profile", state_fips="24")
        return _payload(a), _payload(b)

    out, st = asyncio.run(both())
    assert out["fiscal_year"] == fy
    assert out["total_aggregated_amount"] > 100e9
    assert st["fiscal_year"] == fy
    assert st["total_prime_amount"] > 10e9


# ===========================================================================
# U2 (P2): lookup_piid is an exact PIID lookup across contracts and IDVs
# ===========================================================================

def _piid_api(exact: dict[str, dict], keyword_rows: dict[str, list]):
    """Fake USAspending: exact[PIID] = {'contracts': [...], 'idvs': [...]} rows
    for the award_ids filter; keyword_rows[group] = rows for keyword search."""
    def respond(path, body):
        f = body.get("filters", {})
        if path.endswith("spending_by_award_count/"):
            hits = {"contracts": 0, "idvs": 0}
            for pid in f.get("award_ids", []):
                for g in hits:
                    hits[g] += len(exact.get(pid, {}).get(g, []))
            return {"results": {**hits, "grants": 0, "loans": 0, "direct_payments": 0, "other": 0}}
        group = "idvs" if f["award_type_codes"][0].startswith("IDV") else "contracts"
        if "award_ids" in f:
            rows = [r for pid in f["award_ids"] for r in exact.get(pid, {}).get(group, [])]
        else:
            rows = keyword_rows.get(group, [])
        lim = body["limit"]
        return {"results": rows[:lim], "page_metadata": {"page": 1, "hasNext": len(rows) > lim}}
    return respond


OASIS_IDV = {"Award ID": "GS00Q14OADU108", "Recipient Name": "BOOZ ALLEN HAMILTON INC",
             "Award Amount": 0.0, "generated_internal_id": "CONT_IDV_GS00Q14OADU108_4732"}
CG_ORDER = {"Award ID": "70Z02319FADW01000", "Award Amount": 5.6e6,
            "generated_internal_id": "CONT_AWD_70Z02319FADW01000_7008_GS00Q14OADU108_4732"}


def test_u2_idv_piid_returns_the_idv_not_keyword_hits(monkeypatch):
    mock = _MockPost(_piid_api({"GS00Q14OADU108": {"idvs": [OASIS_IDV]}}, {"contracts": [CG_ORDER]}))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("lookup_piid", piid="GS00Q14OADU108")))
    assert out["match"] == "exact"
    assert out["award_type"] == "idv"
    assert [r["generated_internal_id"] for r in out["results"]] == ["CONT_IDV_GS00Q14OADU108_4732"]
    assert out["ambiguous"] is False
    # keyword search never ran
    assert not any("keywords" in b.get("filters", {}) for _, b in mock.calls)


def test_u2_lowercase_piid_is_matched_exactly(monkeypatch):
    mock = _MockPost(_piid_api({"GS00Q14OADU108": {"idvs": [OASIS_IDV]}}, {}))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("lookup_piid", piid="gs00q14oadu108")))
    assert out["match"] == "exact" and out["results"][0]["Award ID"] == "GS00Q14OADU108"


def test_u2_repeated_piid_is_flagged_ambiguous(monkeypatch):
    rows = [
        {"Award ID": "0001", "Recipient Name": "THE BOEING COMPANY", "Award Amount": 3.68e9,
         "Awarding Agency": "Department of Defense",
         "generated_internal_id": "CONT_AWD_0001_9700_FA852612D0001_9700"},
        {"Award ID": "0001", "Recipient Name": "V2X SYSTEMS LLC", "Award Amount": 1.22e9,
         "Awarding Agency": "Department of Defense",
         "generated_internal_id": "CONT_AWD_0001_9700_W52P1J05D0003_9700"},
    ] * 4
    mock = _MockPost(_piid_api({"0001": {"contracts": rows}}, {"contracts": [CG_ORDER]}))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("lookup_piid", piid="0001")))
    assert out["match"] == "exact"
    assert out["ambiguous"] is True
    assert out["exact_match_count"]["contracts"] == 8
    assert "Ambiguous" in out["note"]
    assert out["results"][0]["parent_idv_piid"] == "FA852612D0001"
    assert all(r["Award ID"] == "0001" for r in out["results"])
    assert out["page_metadata"]["hasNext"] is True


def test_u2_contract_and_idv_both_checked(monkeypatch):
    order = {"Award ID": "X1234", "generated_internal_id":
             "CONT_AWD_X1234_4732_GS00Q14OADU108_4732"}
    idv = {**OASIS_IDV, "Award ID": "X1234", "generated_internal_id": "CONT_IDV_X1234_4732"}
    mock = _MockPost(_piid_api({"X1234": {"contracts": [order], "idvs": [idv]}}, {}))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("lookup_piid", piid="X1234")))
    assert out["award_type"] == "contract_and_idv"
    assert {r["award_type"] for r in out["results"]} == {"contract", "idv"}
    assert out["ambiguous"] is True


def test_u2_keyword_fallback_is_labeled_fuzzy(monkeypatch):
    mock = _MockPost(_piid_api({}, {"contracts": [CG_ORDER]}))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("lookup_piid", piid="47QTCK18D00")))
    assert out["match"] == "fuzzy"
    assert "keyword" in out["note"].lower()
    assert out["results"][0]["award_type"] == "contract"
    assert out["results"][0]["parent_idv_piid"] == "GS00Q14OADU108"


def test_u2_no_match(monkeypatch):
    mock = _MockPost(_piid_api({}, {}))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("lookup_piid", piid="ZZZ999")))
    assert out["match"] == "none" and out["results"] == []


def test_u2_parent_idv_parser():
    assert srv._parent_idv_piid("CONT_AWD_0001_9700_W52P1J05D0003_9700") == "W52P1J05D0003"
    assert srv._parent_idv_piid("CONT_AWD_N0002417C2100_9700_-NONE-_-NONE-") is None
    assert srv._parent_idv_piid("CONT_IDV_GS00Q14OADU108_4732") is None
    assert srv._parent_idv_piid(None) is None


@live
def test_live_u2_oasis_idv_and_0001():
    async def both():
        a = await _call("lookup_piid", piid="GS00Q14OADU108")
        b = await _call("lookup_piid", piid="0001")
        return _payload(a), _payload(b)

    oasis, dup = asyncio.run(both())
    assert oasis["match"] == "exact" and oasis["award_type"] == "idv"
    assert oasis["results"][0]["generated_internal_id"] == "CONT_IDV_GS00Q14OADU108_4732"
    assert dup["ambiguous"] is True and dup["exact_match_count"]["contracts"] > 1000
    assert all(r["Award ID"] == "0001" for r in dup["results"])


# ===========================================================================
# U3 (P2): date_type (new_awards_only) on the search and aggregation tools
# ===========================================================================

VA_SDVOSB = dict(
    awarding_agency="Department of Veterans Affairs",
    set_aside_type_codes=["SDVOSBC", "SDVOSBS"],
    time_period_start="2025-10-01", time_period_end="2026-09-30",
)

U3_TOOLS = [
    ("get_award_count", {}),
    ("search_awards", {}),
    ("spending_by_category", {"category": "awarding_agency", "award_type": "contracts"}),
    ("spending_over_time", {"award_type": "contracts"}),
]


@pytest.mark.parametrize("tool,extra", U3_TOOLS)
def test_u3_new_awards_only_reaches_the_time_period(monkeypatch, tool, extra):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    kwargs = {**VA_SDVOSB, **extra}
    if tool == "spending_over_time":
        kwargs.pop("set_aside_type_codes")
    asyncio.run(_call(tool, date_type="new_awards_only", **kwargs))
    period = mock.calls[-1][1]["filters"]["time_period"]
    assert period == [{"start_date": "2025-10-01", "end_date": "2026-09-30", "date_type": "new_awards_only"}]


@pytest.mark.parametrize("tool,extra", U3_TOOLS)
def test_u3_default_window_unchanged(monkeypatch, tool, extra):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    kwargs = {**VA_SDVOSB, **extra}
    if tool == "spending_over_time":
        kwargs.pop("set_aside_type_codes")
    asyncio.run(_call(tool, **kwargs))
    assert mock.calls[-1][1]["filters"]["time_period"] == [
        {"start_date": "2025-10-01", "end_date": "2026-09-30"}]


def test_u3_date_type_needs_a_window():
    with pytest.raises(Exception, match="time window"):
        asyncio.run(_call("get_award_count", awarding_agency="Department of Veterans Affairs",
                          date_type="new_awards_only"))


def test_u3_bad_date_type_rejected():
    with pytest.raises(Exception):
        asyncio.run(_call("get_award_count", date_type="signed", **VA_SDVOSB))


@live
def test_live_u3_new_awards_only_is_smaller():
    async def both():
        a = await _call("get_award_count", **VA_SDVOSB)
        b = await _call("get_award_count", date_type="new_awards_only", **VA_SDVOSB)
        return _payload(a), _payload(b)

    any_action, new_only = asyncio.run(both())
    assert 0 < new_only["results"]["contracts"] < any_action["results"]["contracts"]


# ===========================================================================
# U4 (P2): spending_by_subaward_grouped works out hasNext itself
# ===========================================================================

def _grouped_api(total_rows: int):
    """Fake grouped endpoint holding total_rows primes; like the real one, it
    always reports hasNext false."""
    def respond(path, body):
        start = (body["page"] - 1) * body["limit"]
        n = max(0, min(body["limit"], total_rows - start))
        rows = [{"award_id": f"P{start + i}", "subaward_count": 1} for i in range(n)]
        return {"limit": body["limit"], "results": rows,
                "page_metadata": {"page": body["page"], "hasNext": False}}
    return respond


DHS_GROUPED = dict(awarding_agency="Department of Homeland Security",
                   award_type_codes=["A", "B", "C", "D"],
                   time_period_start="2025-10-01", time_period_end="2026-09-30")


def test_u4_full_page_with_more_rows_says_hasnext(monkeypatch):
    mock = _MockPost(_grouped_api(12))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("spending_by_subaward_grouped", limit=5, **DHS_GROUPED)))
    assert len(out["results"]) == 5
    assert out["page_metadata"]["hasNext"] is True
    # the probe asked for exactly the next row
    assert mock.calls[-1][1]["limit"] == 1 and mock.calls[-1][1]["page"] == 6


def test_u4_last_full_page_says_no_more(monkeypatch):
    mock = _MockPost(_grouped_api(10))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("spending_by_subaward_grouped", limit=5, page=2, **DHS_GROUPED)))
    assert len(out["results"]) == 5
    assert out["page_metadata"] == {"page": 2, "hasNext": False}


def test_u4_short_page_needs_no_probe(monkeypatch):
    mock = _MockPost(_grouped_api(3))
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("spending_by_subaward_grouped", limit=5, **DHS_GROUPED)))
    assert out["page_metadata"]["hasNext"] is False
    assert len(mock.calls) == 1


@live
def test_live_u4_dhs_grouped_has_next():
    out = _payload(asyncio.run(_call("spending_by_subaward_grouped", limit=5,
                                     sort="subaward_obligation", **DHS_GROUPED)))
    assert len(out["results"]) == 5 and out["page_metadata"]["hasNext"] is True


# ===========================================================================
# U1 (P2): DoD 90-day publication delay is flagged on recent DoD answers
# ===========================================================================

@pytest.fixture
def oct10(monkeypatch):
    import datetime as _dt
    monkeypatch.setattr(srv, "_today", lambda: _dt.date(2026, 10, 10), raising=False)
    monkeypatch.setattr(srv, "_current_fiscal_year", lambda: 2027)


FY26 = dict(time_period_start="2025-10-01", time_period_end="2026-09-30")


def test_u1_spending_over_time_dod_recent_window_has_note(monkeypatch, oct10):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    out = _payload(asyncio.run(_call("spending_over_time", group="month", award_type="contracts",
                                     awarding_agency="Department of Defense", **FY26)))
    assert "90 days" in out["data_note"] and "2026-07-12" in out["data_note"]


def test_u1_agency_obligations_dod_fy2026_has_note(monkeypatch, oct10):
    mock = _MockGet(DOD_OBLIGATIONS_FY2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_agency_obligations_by_award_category", toptier_code="097")))
    assert "90 days" in out["data_note"]


@pytest.mark.parametrize("tool,kwargs", [
    ("get_agency_awards", {"toptier_code": "097", "fiscal_year": 2026}),
    ("get_agency_sub_agencies", {"toptier_code": "097"}),
    ("spending_by_category", {"category": "awarding_subagency", "awarding_agency": "Department of Defense", **FY26}),
    ("get_award_count", {"awarding_agency": "Department of Defense", **FY26}),
    ("search_awards", {"awarding_agency": "Department of Defense", **FY26}),
    ("spending_over_time", {"award_type": "contracts", **FY26}),  # government-wide includes DoD
])
def test_u1_note_on_other_dod_answers(monkeypatch, oct10, tool, kwargs):
    monkeypatch.setattr(srv, "_get", _MockGet({"results": []}))
    monkeypatch.setattr(srv, "_post", _MockPost({"results": []}))
    out = _payload(asyncio.run(_call(tool, **kwargs)))
    assert "data_note" in out, tool


@pytest.mark.parametrize("tool,kwargs", [
    ("get_agency_obligations_by_award_category", {"toptier_code": "097", "fiscal_year": 2025}),
    ("get_agency_obligations_by_award_category", {"toptier_code": "036"}),
    ("spending_over_time", {"award_type": "contracts", "awarding_agency": "Department of Defense",
                            "time_period_start": "2024-10-01", "time_period_end": "2025-09-30"}),
    ("spending_over_time", {"award_type": "contracts", "awarding_agency": "Department of Veterans Affairs", **FY26}),
    ("spending_over_time", {"award_type": "grants", "awarding_agency": "Department of Defense", **FY26}),
])
def test_u1_no_note_when_dod_lag_does_not_apply(monkeypatch, oct10, tool, kwargs):
    monkeypatch.setattr(srv, "_get", _MockGet({"results": []}))
    monkeypatch.setattr(srv, "_post", _MockPost({"results": []}))
    out = _payload(asyncio.run(_call(tool, **kwargs)))
    assert "data_note" not in out, tool

@pytest.mark.parametrize('tool,extra', [('spending_over_time', {}), ('spending_by_category', {'category': 'awarding_agency'})])
def test_u13_aggregation_filters_reach_upstream(monkeypatch, tool, extra):
    mock = _MockPost({'results': []})
    monkeypatch.setattr(srv, '_post', mock)
    out = _payload(asyncio.run(_call(tool, funding_agency='Department of Defense',
        recipient_name='Lockheed Martin', extent_competed_type_codes=['B', 'C', 'G'],
        contract_pricing_type_codes=['Y', 'Z'], **FY26, **extra)))
    filters = mock.calls[0][1]['filters']
    assert filters['extent_competed_type_codes'] == ['B', 'C', 'G']
    assert filters['contract_pricing_type_codes'] == ['Y', 'Z']
    assert filters['recipient_search_text'] == ['Lockheed Martin']
    assert {'type': 'funding', 'tier': 'toptier', 'name': 'Department of Defense'} in filters['agencies']
    assert '90 days' in out['data_note']


def test_u6_recipient_search_labels_overlap_and_period(monkeypatch):
    monkeypatch.setattr(srv, '_post', _MockPost({'results': [{'id': 'parent-P', 'amount': 123}]}))
    out = _payload(asyncio.run(_call('search_recipients', keyword='Leidos')))
    assert out['results'][0]['amount'] == 123
    assert 'trailing 12 months' in out['data_note'] and 'do not sum' in out['data_note']


def test_u8_detail_preserves_amounts_and_warns_file_c(monkeypatch):
    monkeypatch.setattr(srv, '_get', _MockGet({'total_outlay': -5684.70, 'total_obligation': 1291222928.24}))
    out = _payload(asyncio.run(_call('get_award_detail', generated_award_id='123')))
    assert out['total_outlay'] == -5684.70
    assert 'File C' in out['data_note'] and 'amount paid' in out['data_note']


def test_u8_funding_warns_incomplete_coverage(monkeypatch):
    monkeypatch.setattr(srv, '_post', _MockPost({'results': []}))
    out = _payload(asyncio.run(_call('get_award_funding', generated_award_id='123')))
    assert 'partial or lagged' in out['data_note']


@pytest.mark.parametrize("tool,phrases", [
    ("get_agency_awards", ["all award types", "get_agency_obligations_by_award_category"]),
    ("get_agency_overview", ["no dollar figures"]),
    ("search_awards", ["lifetime", "End Date"]),
    ("spending_over_time", ["FISCAL periods", "clipped", "October"]),
])
def test_u5_u7_u9_u10_descriptions_explain_scope(tool, phrases):
    tools = asyncio.run(mcp.list_tools())
    description = next(t.description for t in tools if t.name == tool)
    for phrase in phrases:
        assert phrase.lower() in description.lower()


@pytest.mark.parametrize("tool,extra", [
    ("search_awards", {}), ("get_award_count", {}),
    ("spending_over_time", {}), ("spending_by_category", {"category": "recipient"}),
])
@pytest.mark.parametrize("awarding,funding", [
    ("Department of Defense", "National Aeronautics and Space Administration"),
    ("General Services Administration", "Department of Defense"),
])
def test_u1_mixed_agency_roles_keep_dod_lag(monkeypatch, oct10, tool, extra, awarding, funding):
    monkeypatch.setattr(srv, "_post", _MockPost({"results": []}))
    out = _payload(asyncio.run(_call(tool, awarding_agency=awarding,
        funding_agency=funding, award_type="contracts", **FY26, **extra)))
    assert "90 days" in out["data_note"]
