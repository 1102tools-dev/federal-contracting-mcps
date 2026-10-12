"""Assistance listing (CFDA) filter on the award search tools."""
import asyncio

import pytest

import usaspending_gov_mcp.server as srv
from usaspending_gov_mcp.server import UserInputError, _build_filters, mcp

FILTER_TOOLS = {
    "search_awards", "get_award_count", "spending_over_time", "spending_by_category",
    "spending_by_subaward_grouped", "spending_by_transaction", "spending_by_geography",
}


def test_program_numbers_exposed_on_filter_tools():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert len(tools) == 55
    for name in FILTER_TOOLS:
        schema = tools[name].model_dump(by_alias=True)["inputSchema"]
        assert "program_numbers" in schema["properties"], name
        assert "program_numbers" not in schema.get("required", []), name
        assert "autocomplete_cfda()" in tools[name].description, name


def test_dotted_and_undotted_numbers_normalize():
    filters = _build_filters(award_type_codes=["02"], program_numbers=["93.778", 10557, " 84027 "])
    assert filters["program_numbers"] == ["93.778", "10.557", "84.027"]


@pytest.mark.parametrize("bad", ["93", "93.77", "9377", "93-778", "93.778.1", "abc"])
def test_malformed_numbers_rejected(bad):
    with pytest.raises(UserInputError, match="NN.NNN"):
        _build_filters(award_type_codes=["02"], program_numbers=[bad])


@pytest.mark.parametrize("group", ["contracts", "idvs"])
def test_procurement_award_types_rejected(group):
    with pytest.raises(UserInputError, match="financial assistance"):
        _build_filters(award_type_codes=srv.AWARD_TYPE_GROUPS[group], program_numbers=["93.778"])


def test_no_award_type_scope_is_allowed():
    assert _build_filters(program_numbers=["93.778"]) == {"program_numbers": ["93.778"]}


def test_search_awards_sends_program_numbers(monkeypatch):
    calls = []

    async def fake_post(path, body):
        calls.append((path, body))
        return {"results": [], "page_metadata": {"page": 1, "hasNext": False}}

    monkeypatch.setattr(srv, "_post", fake_post)
    asyncio.run(mcp.call_tool("search_awards", {"award_type": "grants", "program_numbers": ["93778"]}))
    assert calls and calls[0][1]["filters"]["program_numbers"] == ["93.778"]
