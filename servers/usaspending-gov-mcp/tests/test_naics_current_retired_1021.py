"""Current taxonomy status is distinct from active result truncation."""
import asyncio
import copy
import json
import re
from pathlib import Path
import usaspending_gov_mcp.server as s
FIXTURE = json.loads((Path(__file__).parent / "fixtures/naics_current_retired_1021.json").read_text())


def invoke(monkeypatch, term, limit, exclude_retired=True):
    fixture = FIXTURE["research" if term == "5417" else "construction"]
    async def data_version():
        return None
    async def send(method, path, *, params=None, body=None):
        assert method == fixture["method"]
        assert path == "/api/v2/autocomplete/naics/"
        assert body["search_text"] == term
        return json.dumps(copy.deepcopy(fixture["raw"]))
    monkeypatch.setattr(s, "_data_version", data_version)
    monkeypatch.setattr(s, "_send", send)
    response = asyncio.run(s.mcp.call_tool("autocomplete_naics", {
        "search_text": term, "limit": limit, "exclude_retired": exclude_retired,
    })).structured_content
    return response["result"] if set(response) == {"result"} else response


def test_current_codes_omitted_by_limit_are_not_described_as_retired(monkeypatch):
    out = invoke(monkeypatch, "construction", 5)
    raw = FIXTURE["construction"]["raw"]["results"]
    assert all(row["year_retired"] is None for row in raw)
    assert out["results"] == raw[:5]
    note = out["_note"]
    assert re.search(r"\b0 retired codes\b", note)
    assert re.search(r"\b10 additional current", note)
    assert "limit" in note and "Increase" in note
    recovered = invoke(monkeypatch, "construction", 15)
    assert recovered["results"] == raw
    assert any(row["naics"] == "237310" for row in recovered["results"])


def test_actual_retired_research_codes_remain_excluded_and_correctly_counted(monkeypatch):
    out = invoke(monkeypatch, "5417", 5)
    raw = FIXTURE["research"]["raw"]["results"]
    assert out["results"] == [row for row in raw if row["year_retired"] is None]
    assert re.search(r"\b3 retired codes\b", out["_note"])


def test_include_retired_preserves_source_rows_and_order(monkeypatch):
    out = invoke(monkeypatch, "5417", 15, exclude_retired=False)
    assert out == FIXTURE["research"]["raw"]
