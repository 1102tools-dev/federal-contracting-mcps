"""Dioxin MCL scientific notation and genuine footnotes from official Title40 XML."""
import asyncio
from decimal import Decimal
from pathlib import Path
import re
import ecfr_mcp.server as srv

FIXTURE = Path(__file__).parent / "fixtures/ecfr_xml/drinking-water-mcls-20261007.xml"


def read_fixture(monkeypatch):
    async def get_xml(path, params):
        assert path == "/api/versioner/v1/full/2026-10-07/title-40.xml"
        assert params == {"section": "141.61"}
        return FIXTURE.read_text()
    monkeypatch.setattr(srv, "_get_xml", get_xml)
    return asyncio.run(srv.get_cfr_content(title_number=40, section="141.61", date="2026-10-07"))


def test_dioxin_mcl_is_scientific_number_not_undefined_footnote(monkeypatch):
    result = read_fixture(monkeypatch)
    row = next(row for row in result["tables"][2]["rows"] if any("2,3,7,8-TCDD" in cell for cell in row))
    value = row[-1]
    match = re.fullmatch(r"(\d+)\s*×\s*10\^([−+-]?\d+)", value)
    assert match, f"Dioxin MCL must retain its signed exponent, got {value!r}"
    assert Decimal(match[1]) * Decimal(10) ** int(match[2].replace("−", "-")) == Decimal("0.00000003")
    assert result["tables"][2]["rows"][0][-1] == "MCL (mg/l)"


def test_drinking_water_genuine_footnotes_keep_references_and_complete_text(monkeypatch):
    result = read_fixture(monkeypatch)
    hazard = next(row for row in result["tables"][3]["rows"] if "Hazard Index PFAS" in " ".join(row))
    assert hazard[2] == "1 (unitless) [fn 1]"
    assert any(row[0].startswith("[fn 1] The PFAS Mixture Hazard Index") for row in result["tables"][3]["rows"])
    technology = next(row for row in result["tables"][5]["rows"] if "Reverse Osmosis" in " ".join(row))
    assert technology[0] == "Reverse Osmosis, Nanofiltration [fn 3]"
    assert any(row[0].startswith("[fn 3]") for row in result["tables"][5]["rows"])
    assert len(result["tables"]) == 6
    assert sum(len(table["rows"]) for table in result["tables"]) == 134


def test_unsigned_superscript_note_and_ordinal_are_unchanged():
    xml = '<DIV8 N="1.1" TYPE="SECTION"><HEAD>Control.</HEAD><P>Size standard 450<sup>8</sup>; the 1<sup>st</sup> item.</P></DIV8>'
    result = srv._parse_xml_to_text(xml, "2026-10-07")
    assert result["paragraphs"] == ["Size standard 450 [fn 8] ; the 1st item."]
