"""Tool-selection guidance must describe the actual upstream datasets."""
import asyncio
from usaspending_gov_mcp.server import mcp

def descriptions():
    return {t.name: " ".join(t.description.split()) for t in asyncio.run(mcp.list_tools())}

def test_submission_calendar_does_not_advertise_agency_completion():
    text = descriptions()["get_submission_periods"]
    assert "reporting calendar" in text
    assert "not records of when individual agencies actually submitted" in text
    assert "does not establish complete agency data coverage" in text
    assert "when each agency last submitted" not in text

def test_idv_file_c_does_not_advertise_complete_child_order_records():
    text = descriptions()["get_idv_funding"]
    assert "File C funding records associated with an IDV" in text
    assert "not a complete list of child orders" in text
    assert "get_idv_amounts()" in text and "get_idv_children()" in text
    assert "for an IDV's child orders" not in text
