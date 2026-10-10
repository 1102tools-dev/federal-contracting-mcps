# SPDX-License-Identifier: MIT
"""1.1.0 fix wave: the 2026-10-10 bug hunt (offline; eCFR calls are mocked).

The parser itself is covered against real eCFR XML in
test_real_xml_fixtures.py. These tests cover the tools around it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import ecfr_mcp.server as srv

FIXTURES = Path(__file__).parent / "fixtures" / "ecfr_xml"
DATE = "2026-10-07"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _Xml:
    """Stands in for _get_xml: answers from saved responses and records calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        answer = self.answers(path, params or {})
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def mock_xml(monkeypatch):
    def install(answers):
        fake = _Xml(answers)
        monkeypatch.setattr(srv, "_get_xml", fake)
        async def resolve(title_number):
            return DATE
        monkeypatch.setattr(srv, "_resolve_date", resolve)
        return fake
    return install


def _run(coro):
    return asyncio.run(coro)


# --- get_cfr_content / lookup_far_clause: one object per section, pages -----

def test_subpart_answer_lists_each_section(mock_xml):
    mock_xml(lambda path, params: _fixture("t48_subpart_15.3.xml"))
    r = _run(srv.get_cfr_content(subpart="15.3"))
    assert [s["section"] for s in r["sections"]][:2] == ["15.300", "15.301"]
    assert r["date"] == DATE and r["subpart"] == "15.3"
    assert "page" not in r


def test_clause_comes_back_once(mock_xml):
    mock_xml(lambda path, params: _fixture("t48_52.236-27.xml"))
    r = _run(srv.lookup_far_clause("52.236-27"))
    assert "extracts" not in r
    assert r["paragraphs"].count("(End of provision)") == 2


def test_definitions_section_comes_in_two_pages(mock_xml):
    mock_xml(lambda path, params: _fixture("t48_2.101.xml"))
    first = _run(srv.get_cfr_content(section="2.101"))
    assert (first["page"], first["total_pages"]) == (1, 2)
    assert "find_far_definition" in first["page_note"]
    assert first["paragraphs"][0].startswith("A word or a term, defined in this section")
    second = _run(srv.lookup_far_clause("2.101", page=2))
    assert second["page"] == 2 and second["continued_from_previous_page"] is True
    assert second["citations"]
    with pytest.raises(ValueError, match="has 2 pages"):
        _run(srv.get_cfr_content(section="2.101", page=3))


def test_page_must_be_positive():
    with pytest.raises(ValueError, match="page must be >= 1"):
        _run(srv.get_cfr_content(section="15.305", page=0))


# --- compare_versions: the changes, not just two texts ----------------------

_BEFORE = """<DIV8 N="1.1" TYPE="SECTION"><HEAD>1.1 Test.</HEAD>
<P>(a) Keep this.</P><P>(b) The limit is $15 million.</P><P>(c) Gone later.</P></DIV8>"""
_AFTER = """<DIV8 N="1.1" TYPE="SECTION"><HEAD>1.1 Test.</HEAD>
<P>(a) Keep this.</P><P>(b) The limit is $100 million.</P><P>(d) New.</P>
<XREF>Link to an amendment published at 91 FR 1, Jan. 2, 2026.</XREF></DIV8>"""


def test_compare_versions_lists_what_changed(mock_xml):
    mock_xml(lambda path, params: _BEFORE if "2026-09-01" in path else _AFTER)
    r = _run(srv.compare_versions("1.1", "2026-09-01", "2026-10-07"))
    assert r["identical"] is False
    changed = r["changes"][0]
    assert changed["change"] == "changed"
    assert changed["before"] == ["(b) The limit is $15 million.", "(c) Gone later."]
    assert changed["after"] == ["(b) The limit is $100 million.", "(d) New."]
    assert r["changes"][-1]["change"] == "pending amendment link"
    assert r["before"]["paragraphs"][0] == "(a) Keep this."


def test_compare_versions_says_when_nothing_changed(mock_xml):
    mock_xml(lambda path, params: _BEFORE)
    r = _run(srv.compare_versions("1.1", "2026-09-01", "2026-10-07"))
    assert r["identical"] is True and r["changes"] == []
    assert "same" in r["note"]


def test_compare_versions_drops_full_texts_when_too_long(mock_xml):
    big = _fixture("t48_2.101.xml")
    smaller = big.replace("<P><I>Supplies</I> means", "<P><I>Supplies</I> now means", 1)
    mock_xml(lambda path, params: big if "2026-09-01" in path else smaller)
    r = _run(srv.compare_versions("2.101", "2026-09-01", "2026-10-07"))
    assert r["texts_omitted"] is True
    assert "paragraphs" not in r["before"] and "paragraphs" not in r["after"]
    assert r["change_count"] == 1
    assert r["changes"][0]["after"][0].startswith("*Supplies* now means")
