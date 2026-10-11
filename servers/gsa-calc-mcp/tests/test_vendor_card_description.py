"""Vendor subset answers must disclose incomplete pagination."""
import asyncio

from gsa_calc_mcp.server import mcp


def test_exported_vendor_card_description_requires_complete_or_partial_answer():
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "vendor_rate_card")
    description = tool.description
    assert "fetch every page" in description
    assert "page=next_page" in description
    assert "has_more is false" in description
    assert "role-specific subset" in description
    assert "say clearly that the results are partial" in description
    assert "returned_range" in description and "total_rates" in description
    assert "Do not claim a role is absent" in description
    assert "page" in tool.model_dump(by_alias=True)["inputSchema"]["properties"]
