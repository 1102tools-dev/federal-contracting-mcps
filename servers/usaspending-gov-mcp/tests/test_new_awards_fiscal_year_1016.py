"""Real published API samples reveal annual calendar buckets in a fiscal request."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
import usaspending_gov_mcp.server as s
from .test_content_fixes_1013 import _call, _payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures/new_awards_fiscal_year_1016.json").read_text())


def mock_api(monkeypatch, sample):
    async def post(path, payload):
        assert path == "/api/v2/search/new_awards_over_time/"
        assert payload["filters"]["time_period"] == [{
            "start_date": sample["args"]["time_period_start"],
            "end_date": sample["args"]["time_period_end"],
        }]
        return copy.deepcopy(sample["raw"][payload["group"]])
    monkeypatch.setattr(s, "_post", post)


@pytest.mark.parametrize("key,expected", [
    ("full_fy", {"2025": 23992}),
    ("partial_cross_fy", {"2024": 2574, "2025": 2190}),
])
def test_fiscal_year_answer_places_new_awards_in_the_correct_federal_year(monkeypatch, key, expected):
    sample = FIXTURE[key]
    mock_api(monkeypatch, sample)
    out = _payload(asyncio.run(_call("new_awards_over_time", group="fiscal_year", **sample["args"])))
    assert out["group"] == "fiscal_year"
    assert {r["time_period"]["fiscal_year"]: r["new_award_count_in_period"] for r in out["results"]} == expected
    assert all(set(r["time_period"]) == {"fiscal_year"} for r in out["results"])
    assert out["messages"] == sample["raw"]["quarter"]["messages"]
    assert sum(r["new_award_count_in_period"] for r in out["results"]) == sum(
        r["new_award_count_in_period"] for r in sample["raw"]["month"]["results"]
    )


@pytest.mark.parametrize("key", ["full_fy", "partial_cross_fy"])
@pytest.mark.parametrize("group", ["quarter", "month"])
def test_quarter_and_month_source_counts_and_periods_are_unchanged(monkeypatch, key, group):
    sample = FIXTURE[key]
    mock_api(monkeypatch, sample)
    out = _payload(asyncio.run(_call("new_awards_over_time", group=group, **sample["args"])))
    assert {k: v for k, v in out.items() if k not in {"data_note", "time_period_note"}} == sample["raw"][group]
