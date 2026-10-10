"""User-workflow regressions from the October 10 end-to-end audit."""
import asyncio
import pytest
import ecfr_mcp.server as srv


@pytest.fixture
def comparison_source(monkeypatch):
    calls = []
    async def latest(title):
        return "2026-10-07"
    async def xml(path, params=None):
        calls.append(path)
        if "2026-10-01" not in path:
            raise RuntimeError("HTTP 404: Resource not found.")
        return '<DIV8 N="15.305" TYPE="SECTION"><HEAD>15.305 Proposal evaluation.</HEAD><P>Evaluate proposals.</P></DIV8>'
    monkeypatch.setattr(srv, "_resolve_date", latest)
    monkeypatch.setattr(srv, "_get_xml", xml)
    return calls


@pytest.mark.parametrize("after", ["2026-10-10", "2099-01-01"])
def test_unavailable_snapshot_cannot_mean_section_removed(comparison_source, after):
    # Route through MCP's actual validation/handler pipeline.
    with pytest.raises(Exception, match="latest available.*2026-10-07"):
        asyncio.run(srv.mcp.call_tool("compare_versions", {
            "section_id": "15.305", "date_before": "2026-10-01",
            "date_after": after, "changes_only": True,
        }))
    assert comparison_source == []


@pytest.mark.parametrize("missing", ["before", "after"])
def test_changes_only_omits_text_for_added_and_removed_sections(monkeypatch, missing):
    async def latest(title):
        return "2026-10-07"
    async def xml(path, params=None):
        is_before = "2026-10-01" in path
        if is_before == (missing == "before"):
            raise RuntimeError("HTTP 404: Resource not found.")
        return '<DIV8 N="15.305" TYPE="SECTION"><HEAD>15.305 Proposal evaluation.</HEAD><P>Evaluate proposals.</P></DIV8>'
    monkeypatch.setattr(srv, "_resolve_date", latest)
    monkeypatch.setattr(srv, "_get_xml", xml)
    r = asyncio.run(srv.mcp.call_tool("compare_versions", {
        "section_id": "15.305", "date_before": "2026-10-01",
        "date_after": "2026-10-07", "changes_only": True,
    })).structured_content
    assert r["texts_omitted"] is True
    assert "paragraphs" not in r["before"] and "paragraphs" not in r["after"]
    assert r["changes"][0]["change"] == ("section added" if missing == "before" else "section removed")


@pytest.mark.parametrize("tool,args", [
    ("get_cfr_structure", {"part": "2 CFR 200"}),
    ("get_cfr_structure", {"subpart": "2 CFR 200.3"}),
    ("list_sections_in_part", {"part_number": "2 CFR 200"}),
    ("list_sections_in_part", {"part_number": "200", "subpart": "2 CFR 200.3"}),
    ("get_ancestry", {"subpart": "2 CFR 200.3"}),
    ("find_recent_changes", {"since_date": "2026-09-01", "part": "2 CFR 200"}),
])
def test_explicit_citation_title_is_never_silently_discarded(monkeypatch, tool, args):
    async def unexpected(*args, **kwargs):
        raise AssertionError("citation conflict must fail before any upstream lookup")
    monkeypatch.setattr(srv, "_get_json", unexpected)
    monkeypatch.setattr(srv, "_resolve_date", unexpected)
    with pytest.raises(Exception, match="title_number=2"):
        asyncio.run(srv.mcp.call_tool(tool, args))
