"""Captured Science-account questions disclose source scope and complete the list."""
import asyncio
import copy
import json
from pathlib import Path

import usaspending_gov_mcp.server as s
from .test_content_fixes_1013 import _call, _payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures/federal_account_program_scope_1018.json").read_text())


def mock_api(monkeypatch):
    async def get(path, params=None):
        if "fiscal_year_snapshot" in path:
            return copy.deepcopy(FIXTURE["fy_snapshot"])
        assert path == f"/api/v2/federal_accounts/{FIXTURE['account_code']}/program_activities/"
        params = params or {}
        page, limit = int(params.get("page", 1)), int(params.get("limit", 10))
        capture = next(c for c in FIXTURE["source_captures"] if c["params"] == {"page": page, "limit": limit})
        return copy.deepcopy(capture["raw"])
    monkeypatch.setattr(s, "_get", get)


def test_requested_fy2024_does_not_misrepresent_all_year_programs(monkeypatch):
    mock_api(monkeypatch)
    out = _payload(asyncio.run(_call("get_federal_account_program_activities", account_code=FIXTURE["account_code"], fiscal_year=2024)))
    # These output facts express the user's requested scope; no prose is frozen.
    assert out["requested_fiscal_year"] == "2024"
    assert out["fiscal_year_filter_applied"] is False
    assert out["program_activity_scope"] == "all_reported_fiscal_years"
    assert any(row["name"] == "AMERICAN SCIENCE CLOUD (PL 119-21)" for row in out["results"])


def test_complete_program_list_is_retrievable_without_new_schema_arguments(monkeypatch):
    mock_api(monkeypatch)
    out = _payload(asyncio.run(_call("get_federal_account_program_activities", account_code=FIXTURE["account_code"])))
    assert out["results"] == FIXTURE["full_programs"]
    assert len(out["results"]) == 25
    assert out["program_activity_list_complete"] is True
    assert out["page_metadata"]["hasNext"] is False
    assert out["page_metadata"]["total"] == 25


def test_actual_single_year_resource_followup_retains_amounts(monkeypatch):
    mock_api(monkeypatch)
    out = _payload(asyncio.run(_call("get_federal_account_fy_snapshot", account_id=FIXTURE["account_id"], fiscal_year=2024)))
    assert out == FIXTURE["fy_snapshot"]
    assert out["results"]["obligated"] == 9281790861.2
