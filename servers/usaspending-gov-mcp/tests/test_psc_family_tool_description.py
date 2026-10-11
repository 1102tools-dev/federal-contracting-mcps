"""Keep PSC family requests on the tool that exposes the source hierarchy."""
import asyncio

from usaspending_gov_mcp.server import mcp


def test_exported_psc_autocomplete_routes_partial_families_to_hierarchy():
    tools = asyncio.run(mcp.list_tools())
    autocomplete = next(tool for tool in tools if tool.name == "autocomplete_psc")
    tree = next(tool for tool in tools if tool.name == "get_psc_filter_tree")
    description = autocomplete.description
    assert "exact four-character codes" in description
    assert "Two-character families" in description
    assert "no autocomplete matches" in description
    assert "get_psc_filter_tree()" in description
    assert "path='Service/D/D3/'" in description
    assert "Works best with code prefixes" not in description
    assert "path" in tree.model_dump(by_alias=True)["inputSchema"]["properties"]
