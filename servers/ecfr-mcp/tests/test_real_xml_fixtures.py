"""Real eCFR XML, saved from the versioner API on 2026-10-10 (content date 2026-10-07).

The test that was missing before 1.1.0: every text node in a real eCFR
response must come out of the parser exactly once, in document order, under
the right section. Parser tests used to feed 1-3 hand-written elements, so
they never met FP-1/FP-DASH lists, notes, examples, captions, footnote marks,
multi-section subparts or pending-amendment links, and the 2026-10-10 bug
hunt found all of those dropped, fused or duplicated.

Fixture files are eCFR's own responses, byte for byte:
  /api/versioner/v1/full/2026-10-07/title-<N>.xml?section=<id> (or part/subpart/appendix)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import ecfr_mcp.server as srv

FIXTURES = Path(__file__).parent / "fixtures" / "ecfr_xml"
DATE = "2026-10-07"

FIXTURE_FILES = [
    "t48_2.101.xml",
    "t48_52.212-3.xml",
    "t48_52.219-9.xml",
    "t48_52.236-27.xml",
    "t48_subpart_15.3.xml",
    "t2_200_appendix_VIII.xml",
    "t13_121.201.xml",
    "t13_125.6.xml",
    "t48_25.504-2.xml",
    "t48_3052.225-71.xml",
]

# Text the parser reports beside the paragraphs, not in them: element -> key.
SIDE = {"CITA": "citations", "EDNOTE": "editorial_notes", "XREF": "pending_amendments",
        "AUTH": "authority", "SOURCE": "source"}
SECTION_DIVS = {"DIV8", "DIV9"}
GROUP_DIVS = {"DIV1", "DIV2", "DIV3", "DIV4", "DIV5", "DIV6", "DIV7"}
MARKER = re.compile(r"^\[See (table|note|example) (\d+)(?::.*)?\]$")


def _norm(text: str) -> str:
    """Whitespace and *italic* asterisks don't count; footnote marks keep their number."""
    text = re.sub(r"\[fn ([^\]]*)\]", r"\1", text)
    text = re.sub(r"\[fn\]", "", text)
    text = re.sub(r"\[Image: [^\]]*\]", "", text)
    return re.sub(r"[\s*]+", "", text)


def _load(name: str) -> tuple[str, ET.Element]:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return raw, ET.fromstring(raw)


def _source_texts(div: ET.Element) -> list[str]:
    """The div's text nodes in document order, without nested sections or side text."""
    out: list[str] = []

    def walk(e: ET.Element, top: bool) -> None:
        if not top and (e.tag in SECTION_DIVS or e.tag in GROUP_DIVS or e.tag in SIDE):
            return
        if e.text and e.text.strip():
            out.append(e.text)
        for child in e:
            walk(child, False)
            if child.tail and child.tail.strip():
                out.append(child.tail)

    walk(div, True)
    return out


def _side_texts(div: ET.Element, tag: str) -> list[str]:
    found: list[str] = []

    def walk(e: ET.Element, top: bool) -> None:
        if not top and (e.tag in SECTION_DIVS or e.tag in GROUP_DIVS):
            return
        if e.tag == tag:
            found.append("".join(e.itertext()))
            return
        for child in e:
            walk(child, False)

    walk(div, True)
    return found


def _stream(unit: dict) -> list[str]:
    """The unit's output in reading order, with each marker replaced by what it points to."""
    items = [unit.get("heading", "")]

    def expand(paragraphs: list[str]) -> None:
        for p in paragraphs:
            m = MARKER.match(p)
            if not m:
                items.append(p)
                continue
            kind, number = m.group(1), int(m.group(2))
            entry = next(x for x in unit[kind + "s"] if x[kind] == number)
            if kind == "table":
                items.extend([entry.get("caption", ""), entry.get("headnote", "")])
                for row in entry["rows"]:
                    items.extend(row)
                items.extend(entry.get("notes", []))
            else:
                items.append(entry.get("label", ""))
                expand(entry["paragraphs"])

    expand(unit.get("paragraphs", []))
    return items


def _check_unit(div: ET.Element, unit: dict, where: str) -> None:
    expected = "".join(_norm(t) for t in _source_texts(div))
    actual = "".join(_norm(t) for t in _stream(unit))
    if actual != expected:
        # Point at the first difference instead of dumping two 100 KB strings.
        i = next((k for k, (a, b) in enumerate(zip(actual, expected)) if a != b),
                 min(len(actual), len(expected)))
        pytest.fail(
            f"{where}: text differs at character {i} "
            f"(output {len(actual)} chars, source {len(expected)}).\n"
            f"  source: ...{expected[max(0, i - 80):i + 80]}\n"
            f"  output: ...{actual[max(0, i - 80):i + 80]}"
        )
    for tag, key in SIDE.items():
        want = sorted(_norm(t) for t in _side_texts(div, tag))
        got = unit.get(key, [])
        got = [got] if isinstance(got, str) else got
        got_norm = sorted(_norm(t) for t in got)
        if key in ("authority", "source"):
            assert "".join(want) == "".join(got_norm), f"{where}: {key} differs"
        else:
            assert want == got_norm, f"{where}: {key} differs: {got}"


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_every_text_node_appears_once_in_order(name):
    raw, root = _load(name)
    parsed = srv._parse_xml_to_text(raw, date=DATE)
    assert "extracts" not in parsed, "clause text must not be repeated in 'extracts'"
    divs = [d for d in root.iter() if d.tag in SECTION_DIVS and d is not root]
    if not divs:
        _check_unit(root, parsed, name)
        return
    # A multi-section response: the container's own text, then each section
    # under its own identifier, in document order.
    _check_unit(root, parsed, f"{name} (container)")
    sections = parsed["sections"]
    assert [s.get("section") or s.get("appendix") for s in sections] == [d.get("N") for d in divs]
    for div, section in zip(divs, sections):
        _check_unit(div, section, f"{name} section {div.get('N')}")


def _parse(name: str) -> dict:
    raw, _ = _load(name)
    return srv._parse_xml_to_text(raw, date=DATE)


def test_subpart_keeps_every_section_number_and_heading():
    r = _parse("t48_subpart_15.3.xml")
    assert r["heading"] == "Subpart 15.3—Source Selection"
    assert [(s["section"], s["heading"]) for s in r["sections"]][:3] == [
        ("15.300", "15.300 Scope of subpart."),
        ("15.301", "15.301 [Reserved]"),
        ("15.302", "15.302 Source selection objective."),
    ]
    assert r["section_count"] == 9
    by_id = {s["section"]: s for s in r["sections"]}
    assert by_id["15.305"]["heading"] == "15.305 Proposal evaluation."
    assert by_id["15.305"]["paragraphs"][0].startswith("(a) Proposal evaluation is an assessment")
    assert by_id["15.306"]["paragraphs"][0].startswith("(a) *Clarifications and award without discussions.*")


def test_flush_list_items_are_their_own_paragraphs():
    r = _parse("t2_200_appendix_VIII.xml")
    assert len(r["paragraphs"]) == 33
    assert r["paragraphs"][0] == "1. Advance Technology Institute (ATI), Charleston, South Carolina"
    assert r["paragraphs"][-1] == "33. Other nonprofit organizations as negotiated with Federal awarding agencies"


def test_fill_in_lines_do_not_swallow_the_alternate():
    r = _parse("t48_52.236-27.xml")
    p = r["paragraphs"]
    for line in ("Name:", "Address:", "Telephone:"):
        assert line in p
    assert p.count("(End of provision)") == 2
    alt = next(x for x in p if x.startswith("*Alternate I* (FEB 1995)."))
    assert p.index(alt) == p.index("Telephone:") + 2  # after "(End of provision)"
    assert "[*Insert date and time*]" in p


def test_reps_and_certs_has_no_run_on_paragraph_and_a_labeled_note():
    r = _parse("t48_52.212-3.xml")
    assert max(len(p) for p in r["paragraphs"]) < 3000
    labels = [n.get("label") for n in r.get("notes", [])]
    assert "Note to paragraphs (*c*)(9) and (10):" in labels


def test_subcontracting_plan_keeps_all_four_alternates():
    r = _parse("t48_52.219-9.xml")
    for alt in ("I", "II", "III", "IV"):
        assert any(p.startswith(f"*Alternate {alt}*") for p in r["paragraphs"]), alt
    assert r["paragraphs"][1].startswith("Small Business Subcontracting Plan (")


def test_footnote_marks_stay_apart_from_size_standards():
    r = _parse("t13_121.201.xml")
    table = r["tables"][0]
    assert table["caption"] == "Small Business Size Standards by NAICS Industry"
    row = next(row for row in table["rows"] if row[0] == "531110")
    assert row[1] == "Lessors of Residential Buildings and Dwellings [fn 9]"
    assert row[2] == "$34.0 [fn 9]"
    exception = next(row for row in table["rows"] if row[0] == "541715" and "Exception" not in row[0])
    assert any(cell == "[fn 11] 1,000" for cell in exception)
    assert "[See table 1: Small Business Size Standards by NAICS Industry]" in r["paragraphs"]


def test_limitations_on_subcontracting_examples_are_kept():
    r = _parse("t13_125.6.xml")
    examples = r["examples"]
    assert len(examples) == 10
    assert examples[0]["label"] == "Example 1 to paragraph (a)(2)."
    first_b = next(e for e in examples if e["label"].startswith("Example 1 to paragraph (b)"))
    assert "$3,000,000" in " ".join(first_b["paragraphs"])
    assert sum(p.startswith("[See example ") for p in r["paragraphs"]) == 10


def test_trade_agreements_example_keeps_its_analysis():
    r = _parse("t48_25.504-2.xml")
    assert r["paragraphs"] == ["[See example 1: Example 1.]"]
    example = r["examples"][0]
    assert example["paragraphs"][0] == "[See table 1]"
    assert "Award on the low remaining offer, Offer C" in example["paragraphs"][-1]
    assert r["tables"][0]["rows"][3][0] == "Offer D"


def test_pending_amendment_is_reported():
    r = _parse("t48_3052.225-71.xml")
    assert r["heading"] == "3052.225-71 xxx"
    assert r["pending_amendments"] == ["Link to an amendment published at 91 FR 59074, Sept. 18, 2026."]
    assert "pending_amendments" in r["warning"]


def test_hierarchy_path_carries_the_real_date():
    r = _parse("t48_2.101.xml")
    meta = r["hierarchy_metadata"][0]
    assert meta["path"] == "/on/2026-10-07/title-48/section-2.101"
    assert meta["url"] == "https://www.ecfr.gov/on/2026-10-07/title-48/section-2.101"
    assert "_SUBSTITUTE_DATE_" not in str(r)


def test_definitions_section_keeps_every_paragraph():
    r = _parse("t48_2.101.xml")
    _, root = _load("t48_2.101.xml")
    in_notes = {p for note in root.iter("EDNOTE") for p in note.iter("P")}
    source_blocks = [e for e in root.iter() if e.tag in ("P", "FP") and e not in in_notes]
    assert len(r["paragraphs"]) == len(source_blocks) == 526
    assert len(r["editorial_notes"]) == 1
    assert any(p.startswith("*Supplies* means all property") for p in r["paragraphs"])

