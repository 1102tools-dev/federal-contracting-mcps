"""Real-user regression cases from the 2026-10-10 end-to-end audit."""
import asyncio
import copy
from datetime import date

import pytest
import usaspending_gov_mcp.server as s
from .test_content_fixes_1013 import _call, _payload

FY = dict(time_period_start="2025-10-01", time_period_end="2026-09-30")
AWD = "CONT_AWD_47QFCA22F0047_4732_GS00Q14OADU108_4732"
IDV = "CONT_IDV_GS00Q14OADU108_4732"
HASH = "7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22-P"

@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(s, "_today", lambda: date(2026, 10, 10))

def mock(monkeypatch, raw):
    async def post(path, payload): return copy.deepcopy(raw)
    async def get(path, params=None): return copy.deepcopy(raw)
    monkeypatch.setattr(s, "_post", post)
    monkeypatch.setattr(s, "_get", get)

@pytest.mark.parametrize("tool", ["spending_by_geography", "spending_by_transaction"])
@pytest.mark.parametrize("agencies", [
    {"awarding_agency": "Department of Defense"},
    {"funding_agency": "Department of Defense"},
    {"awarding_agency": "General Services Administration", "funding_agency": "Department of Defense"},
    {"awarding_agency": "Department of Defense", "funding_agency": "General Services Administration"},
    {},
])
def test_recent_geography_and_transaction_results_explain_missing_actions(monkeypatch, tool, agencies):
    raw = {"results": [{"aggregated_amount": 43914699946.74}]}
    mock(monkeypatch, raw)
    out = _payload(asyncio.run(_call(tool, award_type="contracts", **FY, **agencies)))
    assert out["results"] == raw["results"]
    assert "90 days" in out["data_note"] and "2026-07-12" in out["data_note"]

@pytest.mark.parametrize("tool", ["spending_by_geography", "spending_by_transaction"])
@pytest.mark.parametrize("args", [
    {**FY, "award_type": "grants"},
    {**FY, "award_type": "contracts", "awarding_agency": "Department of Veterans Affairs"},
    {"time_period_start": "2024-10-01", "time_period_end": "2025-09-30", "award_type": "contracts"},
])
def test_lag_caveat_not_added_to_unaffected_searches(monkeypatch, tool, args):
    mock(monkeypatch, {"results": []})
    out = _payload(asyncio.run(_call(tool, **args)))
    assert "data_note" not in out

@pytest.mark.parametrize("tool,args", [
    ("spending_by_transaction", {"awarding_agency": "Department of Defense"}),
    ("spending_by_geography", {"awarding_agency": "Department of Defense"}),
    ("search_awards", {"awarding_agency": "Department of Defense"}),
    ("spending_over_time", {"awarding_agency": "Department of Defense"}),
    ("spending_by_category", {"category": "recipient", "awarding_agency": "Department of Defense"}),
])
def test_unbounded_searches_include_recent_withheld_actions(monkeypatch, tool, args):
    mock(monkeypatch, {"results": []})
    out = _payload(asyncio.run(_call(tool, **args)))
    assert "90 days" in out["data_note"]

@pytest.mark.parametrize("agency", ["Corps of Engineers - Civil Works", "USACE", "096"])
def test_usace_public_disclosure_is_covered(agency):
    note = s._dod_lag_note("2026-09-30", agencies=(agency,))
    assert "USACE" in note and "90 days" in note

def test_usace_agency_awards_caveat(monkeypatch):
    mock(monkeypatch, {"obligations": 380016133917.28})
    out = _payload(asyncio.run(_call("get_agency_awards", toptier_code="096", fiscal_year=2026)))
    assert "USACE" in out["data_note"]
    assert out["obligations"] == 380016133917.28

@pytest.mark.parametrize("year", [None, 2026, "all", "latest"])
def test_state_profile_explains_recent_procurement_gap(monkeypatch, year):
    mock(monkeypatch, {"total_prime_amount": 96666882297.68})
    out = _payload(asyncio.run(_call("get_state_profile", state_fips="24", year=year)))
    assert out["total_prime_amount"] == 96666882297.68
    assert "90 days" in out["data_note"]

def test_old_state_year_has_no_recent_caveat(monkeypatch):
    mock(monkeypatch, {"total_prime_amount": 1})
    out = _payload(asyncio.run(_call("get_state_profile", state_fips="24", year=2024)))
    assert "data_note" not in out

@pytest.mark.parametrize("tool,args,raw", [
    ("get_award_funding_rollup", {"award_id": AWD}, {"total_transaction_obligated_amount": 778490164.54}),
    ("get_idv_funding", {"award_id": IDV}, {"results": [{"transaction_obligated_amount": 161859915.66}]}),
    ("get_idv_funding_rollup", {"award_id": IDV}, {"total_transaction_obligated_amount": 5364749829.04}),
    ("get_idv_amounts", {"award_id": IDV}, {"child_award_total_obligation": 7661073473.94, "child_total_account_obligation": 3927488534.08}),
])
def test_file_c_scope_caveat_preserves_actual_dollars(monkeypatch, tool, args, raw):
    mock(monkeypatch, raw)
    out = _payload(asyncio.run(_call(tool, **args)))
    assert all(out[k] == v for k,v in raw.items())
    assert "File C" in out["data_note"] and "partial or lagged" in out["data_note"]
    assert "amount paid" in out["data_note"]

def test_submission_calendar_is_not_agency_completion_evidence(monkeypatch):
    raw = {"available_periods": [{"submission_fiscal_year": 2026, "submission_fiscal_month": 11}]}
    mock(monkeypatch, raw)
    out = _payload(asyncio.run(_call("get_submission_periods")))
    assert out["available_periods"] == raw["available_periods"]
    assert "not records of when individual agencies actually submitted" in out["data_note"]
    assert "does not establish complete" in out["data_note"]

def test_new_award_months_are_fiscal_and_recent_counts_incomplete(monkeypatch):
    raw = {"group": "month", "results": [{"time_period": {"fiscal_year": "2026", "month": "1"}, "new_award_count_in_period": 64}]}
    mock(monkeypatch, raw)
    out = _payload(asyncio.run(_call("new_awards_over_time", recipient_id=HASH, **FY)))
    assert out["results"] == raw["results"]
    assert "month 1 is October" in out["time_period_note"]
    assert "partial year" in out["time_period_note"]
    assert "90 days" in out["data_note"]
