"""Ordinary subtype definition research against a saved official FAR excerpt."""
import asyncio
from pathlib import Path
import pytest
import ecfr_mcp.server as srv
from ecfr_mcp import _definitions

@pytest.mark.parametrize("term,ending", [
    ("individual surety", "entire penal amount of the bond."),
    ("corporate surety", "act as surety for others."),
    ("cosurety", "A limit of liability for each surety may be stated."),
])
def test_surety_subtype_definition_is_complete_without_false_absence(monkeypatch, term, ending):
    xml = (Path(__file__).parent / "fixtures/ecfr_xml/far-surety-20261007.xml").read_text()
    async def resolve(title):
        return "2026-10-07"
    async def get_xml(path, params):
        assert params == {"section": "2.101"}
        return xml
    async def no_fallback(*args, **kwargs):
        pytest.fail("A numbered FAR 2.101 definition must not be reported absent")
    monkeypatch.setattr(srv, "_resolve_date", resolve)
    monkeypatch.setattr(srv, "_get_xml", get_xml)
    monkeypatch.setattr(srv, "_get_json", no_fallback)
    result = asyncio.run(srv.find_far_definition(term))
    assert result["definition_count"] == 1
    match = result["matches"][0]
    assert match["kind"] == "definition"
    assert match["term"].lower() == term
    assert len(match["context"]) == 1
    assert match["context"][0].endswith(ending)
    assert "does not define" not in result["note"]


def test_whole_surety_definition_keeps_all_three_subtypes_and_mentions():
    xml = (Path(__file__).parent / "fixtures/ecfr_xml/far-surety-20261007.xml").read_text()
    paragraphs = srv._parse_xml_to_text(xml, "2026-10-07")["paragraphs"]
    result = _definitions.find(paragraphs, "surety")
    assert len(result["definitions"]) == 1
    assert result["definitions"][0]["context"] == paragraphs[:4]
    assert _definitions.find(paragraphs, "business entity")["definitions"] == []
    assert _definitions.find(paragraphs, "business entity")["mentions"]


def test_numbered_contract_conditions_are_not_named_definitions():
    paragraphs = ["*Arrangement* means a relationship satisfying these conditions:",
                  "(1) A long-term relationship is contemplated;",
                  "(2) The contractor is responsible for performance."]
    assert _definitions.find(paragraphs, "long-term relationship")["definitions"] == []
    assert _definitions.find(paragraphs, "contractor")["definitions"] == []
