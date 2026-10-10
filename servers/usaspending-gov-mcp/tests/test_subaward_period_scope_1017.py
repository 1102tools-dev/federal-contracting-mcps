"""Captured ordinary FY2025 research must separate cumulative and dated reports."""
import asyncio
import copy
import json
from decimal import Decimal
from pathlib import Path

import usaspending_gov_mcp.server as s
from .test_content_fixes_1013 import _call, _payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures/subaward_period_scope_1017.json").read_text())


def mock_api(monkeypatch):
    async def post(path, payload):
        for record in FIXTURE["wire"] + FIXTURE["followup_wire"]:
            if record["url"].endswith(path) and record["body"] == payload:
                return copy.deepcopy(record["raw"])
        raise AssertionError((path, payload))
    monkeypatch.setattr(s, "_post", post)


def test_original_fiscal_question_exposes_requested_dates_and_scope_guidance(monkeypatch):
    mock_api(monkeypatch)
    out = _payload(asyncio.run(_call("spending_by_subaward_grouped", **FIXTURE["args"])))
    # Dates make the warning specific to the user's actual fiscal question;
    # exact prose and catalog-description wording are intentionally not frozen.
    note = out["data_note"]
    assert FIXTURE["args"]["time_period_start"] in note
    assert FIXTURE["args"]["time_period_end"] in note
    assert "search_subawards" in note
    assert "action_date" in note


def test_cumulative_counts_amounts_identifiers_and_pagination_are_preserved(monkeypatch):
    mock_api(monkeypatch)
    out = _payload(asyncio.run(_call("spending_by_subaward_grouped", **FIXTURE["args"])))
    assert {key: value for key, value in out.items() if key != "data_note"} == FIXTURE["original_output"]


def test_dated_recovery_completes_the_prime_and_correctly_reports_no_fy2025_subawards(monkeypatch):
    mock_api(monkeypatch)
    out = _payload(asyncio.run(_call("search_subawards", **FIXTURE["followup_args"])))
    assert out == FIXTURE["followup_output"]
    assert out["page_metadata"]["hasNext"] is False
    rows = out["results"]
    prime = FIXTURE["original_output"]["results"][0]
    assert len(rows) == prime["subaward_count"] == 18
    assert sum(Decimal(str(row["amount"])) for row in rows) == Decimal(str(prime["subaward_obligation"]))
    window = [row for row in rows if FIXTURE["args"]["time_period_start"] <= row["action_date"] <= FIXTURE["args"]["time_period_end"]]
    assert len(window) == 0
    assert sum(Decimal(str(row["amount"])) for row in window) == 0
