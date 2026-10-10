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


# --- find_far_definition: whole definitions, found by the names people type -

def _definition_terms(r):
    return [m["term"] for m in r["matches"] if m["kind"] == "definition"]


@pytest.mark.parametrize("term,expected", [
    ("service-disabled veteran-owned small business concern",
     "Service-disabled veteran-owned small business (SDVOSB) concern"),
    ("SDVOSB concern", "Service-disabled veteran-owned small business (SDVOSB) concern"),
    ("commercially available off-the-shelf item", "Commercially available off-the-shelf (COTS) item"),
    ("COTS", "Commercially available off-the-shelf (COTS) item"),
    ("commercial services", "Commercial service"),
    ("contract means", "Contract"),
    ("Micro-purchase threshold means", "Micro-purchase threshold"),
    ("micropurchase threshold", "Micro-purchase threshold"),
    ("non-developmental item", "Nondevelopmental item"),
    ("sole-source acquisition", "Sole source acquisition"),
    ("offerors", "Offeror"),
    ("SAT", "Simplified acquisition threshold"),
    ("G&A expense", "General and administrative (G&A) expense"),
    ("head of the agency", "Head of the agency"),
    ("database", "Computer database"),
])
def test_definition_found_by_natural_name(mock_xml, term, expected):
    mock_xml(lambda path, params: _fixture("t48_2.101.xml"))
    r = _run(srv.find_far_definition(term))
    assert _definition_terms(r)[0] == expected
    assert r["matches"][0]["kind"] == "definition"


@pytest.mark.parametrize("term", ["supplies", "United States", "contract"])
def test_definition_comes_before_mentions(mock_xml, term):
    mock_xml(lambda path, params: _fixture("t48_2.101.xml"))
    r = _run(srv.find_far_definition(term))
    first = r["matches"][0]
    assert first["kind"] == "definition"
    assert first["term"].lower() == term.lower()
    assert all(m["kind"] == "mention" and m.get("term") for m in r["matches"][1:])


def test_whole_definition_block_is_returned(mock_xml):
    mock_xml(lambda path, params: _fixture("t48_2.101.xml"))
    r = _run(srv.find_far_definition("inherently governmental function"))
    block = r["matches"][0]["context"]
    text = " ".join(block)
    # The hunt saw (1)(iii) and (iv) go missing from the middle.
    assert "Significantly affect the life, liberty, or property of private persons" in text
    assert "Commission, appoint, direct, or control officers or employees of the United States" in text
    assert block[0].startswith("*Inherently governmental function* means")
    r = _run(srv.find_far_definition("commercial product"))
    assert len(r["matches"][0]["context"]) == 11
    assert r["truncated"] is False


def test_whole_words_only(mock_xml):
    calls = mock_xml(lambda path, params: _fixture("t48_2.101.xml"))

    async def nothing(path, params=None, timeout=None):
        return {"results": []}

    srv._get_json, saved = nothing, srv._get_json
    try:
        r = _run(srv.find_far_definition("allowable cost"))
    finally:
        srv._get_json = saved
    assert r["definition_count"] == 0
    assert all("Unallowable" not in " ".join(m["context"]) for m in r["matches"])
    assert "Unallowable cost" in r["did_you_mean"]
    assert "does not define" in r["note"]
    assert len(calls.calls) == 1


_DEFS_19 = """<DIV8 N="19.001" TYPE="SECTION"><HEAD>19.001 Definitions.</HEAD>
<P>As used in this part—</P>
<P><I>Concern</I> means any business entity.</P>
<P><I>Similarly situated entity</I> means a first-tier subcontractor, including an independent contractor, that—</P>
<P>(1) Has the same small business program status as that which qualified the prime contractor; and</P>
<P>(2) Is small for the NAICS code that the prime contractor assigned to the subcontract.</P>
<P><I>Subcontract</I> means something else.</P></DIV8>"""
_CLAUSE = """<DIV8 N="19.307" TYPE="SECTION"><HEAD>19.307 Protesting.</HEAD>
<P>(a) A subcontractor that is not a similarly situated entity, as defined in 13 CFR 125.1, means trouble.</P></DIV8>"""


def test_term_defined_outside_2_101_is_found(mock_xml, monkeypatch):
    def answers(path, params):
        return {"2.101": _fixture("t48_2.101.xml"), "19.001": _DEFS_19, "19.307": _CLAUSE}[params["section"]]
    mock_xml(answers)
    searched = []

    async def search(path, params=None, timeout=None):
        searched.append(params)
        return {"results": [
            {"hierarchy": {"section": "19.307"}, "headings": {"section": "Protesting."}, "starts_on": "2024-08-29"},
            {"hierarchy": {"section": "19.001"}, "headings": {"section": "Definitions."}, "starts_on": "2021-09-10"},
            {"hierarchy": {"section": "19.001"}, "headings": {"section": "Definitions."}, "starts_on": "2017-01-01"},
        ]}
    monkeypatch.setattr(srv, "_get_json", search)
    r = _run(srv.find_far_definition("similarly situated entities"))
    assert searched[0]["query"] == '"similarly situated entities" means'
    assert searched[0]["hierarchy[chapter]"] == "1" and searched[0]["date"] == DATE
    first, second = r["defined_elsewhere"]
    assert first["section"] == "19.001"
    assert first["definition"] == [
        "*Similarly situated entity* means a first-tier subcontractor, including an independent contractor, that—",
        "(1) Has the same small business program status as that which qualified the prime contractor; and",
        "(2) Is small for the NAICS code that the prime contractor assigned to the subcontract.",
    ]
    assert second["section"] == "19.307" and "definition" not in second
    assert "defined elsewhere" in r["note"]


# --- search_cfr current_only and find_recent_changes: the version history decides

def _row(section, part, starts):
    return {"hierarchy": {"title": "48", "part": part, "section": section}, "starts_on": starts, "ends_on": None}


def _versions(*rows):
    return {"content_versions": [
        {"identifier": i, "part": p, "date": d, "amendment_date": d, "issue_date": d,
         "substantive": True, "removed": r, "name": f"{i}   Name.", "type": "section", "subpart": None}
        for i, p, d, r in rows
    ], "meta": {"total_pages": "1"}}


def test_search_drops_old_copies_and_reports_replaced_and_removed(monkeypatch):
    histories = {
        "52": _versions(("52.212-5", "52", "2025-08-27", False), ("52.212-5", "52", "2026-03-13", False)),
        "9903": _versions(("9903.201-5", "9903", "2014-10-17", False), ("9903.201-5", "9903", "2026-10-01", False)),
        "9904": _versions(("9904.409", "9904", "2014-10-17", False), ("9904.409", "9904", "2026-08-07", True)),
    }
    calls = []

    async def fake(path, params=None, timeout=None):
        calls.append((path, params))
        if path == "/api/search/v1/results":
            return {"results": [
                _row("52.212-5", "52", "2025-08-27"), _row("52.212-5", "52", "2026-03-13"),
                _row("9903.201-5", "9903", "2014-10-17"), _row("9904.409", "9904", "2014-10-17"),
            ], "meta": {"total_count": 4}}
        return histories[params["part"]]

    monkeypatch.setattr(srv, "_get_json", fake)
    r = _run(srv.search_cfr("anything", title=48))
    assert [(x["hierarchy"]["section"], x["starts_on"]) for x in r["results"]] == [("52.212-5", "2026-03-13")]
    check = r["current_check"]
    assert check["older_copies_dropped"] == 1
    assert check["superseded"] == [{"section": "9903.201-5", "matched_text_from": "2014-10-17",
                                    "current_version_from": "2026-10-01"}]
    assert check["removed"][0]["section"] == "9904.409" and check["removed"][0]["removed_on"] == "2026-08-07"
    # Every version is read; current_only=False skips the check entirely.
    calls.clear()
    r = _run(srv.search_cfr("anything", title=48, current_only=False))
    assert len(r["results"]) == 4 and "current_check" not in r and len(calls) == 1


def test_recent_changes_include_removals_and_page(monkeypatch):
    pages = {
        None: {"content_versions": [
            {"identifier": "9904.407", "part": "9904", "date": "2026-10-01", "issue_date": "2026-10-01",
             "substantive": True, "removed": True, "name": "9904.407   Standard."},
            {"identifier": "9903.201-5", "part": "9903", "date": "2026-10-01", "issue_date": "2026-10-01",
             "substantive": True, "removed": False, "name": "9903.201-5   Waiver."},
        ], "meta": {"total_pages": "2"}},
        "2": {"content_versions": [
            {"identifier": "3052.225-71", "part": "3052", "date": "2026-09-18", "issue_date": "2026-09-18",
             "substantive": True, "removed": False, "name": "3052.225-71   xxx"},
            {"identifier": "52.212-5", "part": "52", "date": "2025-08-27", "issue_date": "2026-09-20",
             "substantive": False, "removed": False, "name": "52.212-5   Terms."},
        ], "meta": {"total_pages": "2"}},
    }

    async def fake(path, params=None, timeout=None):
        assert path == "/api/versioner/v1/versions/title-48"
        assert params["issue_date[gte]"] == "2026-09-10"
        return pages[params.get("page")]

    monkeypatch.setattr(srv, "_get_json", fake)
    r = _run(srv.find_recent_changes("2026-09-10"))
    assert r["total_count"] == 4
    assert r["summary"] == {"amended": 2, "removed": 1, "re-issued, no text change": 1}
    assert r["changes"][0]["identifier"] == "9904.407" or r["changes"][0]["issue_date"] == "2026-10-01"
    assert any(c["identifier"] == "9904.407" and c["change"] == "removed" for c in r["changes"])
    assert r["changes"][-1]["name"] == "3052.225-71 xxx"
    far = _run(srv.find_recent_changes("2026-09-10", chapter=1))
    assert [c["identifier"] for c in far["changes"]] == ["52.212-5"]
    cas = _run(srv.find_recent_changes("2026-09-10", chapter="99", per_page=1, page=2))
    assert cas["total_pages"] == 2 and len(cas["changes"]) == 1 and "page=3" not in cas.get("note", "")
    with pytest.raises(ValueError, match="does not exist"):
        _run(srv.find_recent_changes("2026-09-10", chapter="99", per_page=1, page=3))


# --- no silent caps or empty answers ---------------------------------------

def _version(ident, date, **extra):
    return {"identifier": ident, "date": date, "amendment_date": date, "issue_date": date,
            "name": f"{ident}   Name.", "substantive": True, "removed": False, "title": "48", **extra}


def test_version_history_reads_every_page_and_pages_its_answer(monkeypatch):
    pages = {None: [_version(f"52.{n}", "2017-01-01") for n in range(1000)],
             "2": [_version(f"52.{n}", "2020-01-01") for n in range(1000, 2000)],
             "3": [_version("52.240-1", "2026-03-13")]}

    async def fake(path, params=None, timeout=None):
        return {"content_versions": pages[params.get("page")],
                "meta": {"total_pages": "3", "latest_amendment_date": "2026-03-13"}}

    monkeypatch.setattr(srv, "_get_json", fake)
    r = _run(srv.get_version_history(part="52"))
    assert r["total_count"] == 2001 and r["total_pages"] == 11 and len(r["content_versions"]) == 200
    assert "page=2" in r["note"] and "title" not in r["content_versions"][0]
    assert r["content_versions"][0]["name"] == "52.0 Name."
    last = _run(srv.get_version_history(part="52", page=11))
    assert last["content_versions"][-1]["identifier"] == "52.240-1"
    recent = _run(srv.get_version_history(part="52", since_date="2026-01-01"))
    assert [v["identifier"] for v in recent["content_versions"]] == ["52.240-1"]
    assert recent["total_before_date_filter"] == 2001


def test_version_history_of_a_section_not_in_the_title_is_an_error(monkeypatch):
    async def fake(path, params=None, timeout=None):
        return {"content_versions": [], "meta": {"result_count": "0"}}
    monkeypatch.setattr(srv, "_get_json", fake)
    with pytest.raises(ValueError, match="not in this title"):
        _run(srv.get_version_history(section="200.318"))


def test_corrections_newest_first_and_filtered(monkeypatch):
    def corr(day, section, part):
        return {"error_corrected": day, "position": 1, "year": int(day[:4]),
                "cfr_references": [{"hierarchy": {"part": part, "section": section}}]}

    async def fake(path, params=None, timeout=None):
        return {"ecfr_corrections": [corr("2005-09-27", "52.204-1", "52"), corr("2025-03-07", "252.242-7005", "252"),
                                     corr("2019-01-01", "52.204-21", "52")]}
    monkeypatch.setattr(srv, "_get_json", fake)
    r = _run(srv.get_corrections(limit=2))
    assert [c["error_corrected"] for c in r["corrections"]] == ["2025-03-07", "2019-01-01"]
    assert r["truncated"] is True
    assert _run(srv.get_corrections(section="52.204-21"))["count_filtered"] == 1
    assert _run(srv.get_corrections(part="52"))["count_filtered"] == 2


def test_unknown_agency_slug_is_an_error_with_a_suggestion(monkeypatch):
    async def fake(path, params=None, timeout=None):
        assert path == "/api/admin/v1/agencies.json", "search must not run"
        return {"agencies": [{"slug": "veterans-affairs-department", "name": "Veterans Affairs",
                              "short_name": "VA", "children": []}]}
    monkeypatch.setattr(srv, "_get_json", fake)
    with pytest.raises(ValueError, match="Did you mean: veterans-affairs-department"):
        _run(srv.search_cfr("prompt payment", title=48, agency_slugs="va"))


_PART_200 = {"type": "title", "identifier": "2", "children": [
    {"type": "chapter", "identifier": "II", "children": [
        {"type": "part", "identifier": "200", "children": [
            {"type": "subpart", "identifier": "A", "label_description": "Acronyms and Definitions", "children": [
                {"type": "section", "identifier": "200.0", "label_description": "Acronyms.", "label": "§ 200.0 Acronyms."},
                {"type": "section", "identifier": "200.2", "label_description": "[Reserved]", "reserved": True},
            ]},
            {"type": "appendix", "identifier": "Appendix II to Part 200",
             "label_description": "Contract Provisions for Non-Federal Entity Contracts"},
        ]},
    ]},
]}


def test_section_list_has_appendices_subparts_and_the_real_chapter(monkeypatch):
    async def fake(path, params=None, timeout=None):
        assert "chapter" not in params
        return _PART_200
    monkeypatch.setattr(srv, "_get_json", fake)
    r = _run(srv.list_sections_in_part(200, title_number=2, date=DATE))
    assert r["chapter"] == "II" and r["section_count"] == 2 and r["appendix_count"] == 1
    assert r["sections"][0] == {"identifier": "200.0", "heading": "Acronyms."}
    assert r["sections"][1]["reserved"] is True
    assert r["sections"][2]["type"] == "appendix"
    assert r["subparts"] == [{"identifier": "A", "heading": "Acronyms and Definitions", "section_count": 2,
                              "first_section": "200.0", "last_section": "200.2"}]
    assert _run(srv.list_sections_in_part(200, title_number=2, date=DATE, detail=True))["sections"][0]["label"]


def test_structure_too_large_is_cut_with_a_note(monkeypatch):
    big = {"type": "chapter", "identifier": "1", "children": [
        {"type": "part", "identifier": str(n), "label_description": "P", "children": [
            {"type": "section", "identifier": f"{n}.{k}", "label_description": "x" * 200} for k in range(40)
        ]} for n in range(1, 30)
    ]}

    async def fake(path, params=None, timeout=None):
        return big
    monkeypatch.setattr(srv, "_get_json", fake)
    r = _run(srv.get_cfr_structure(chapter="1", date=DATE))
    assert "too long to send at once" in r["note"]
    assert r["children"][0]["children_omitted"] == 40
    assert r["date"] == DATE
    small = _run(srv.get_cfr_structure(chapter="1", date=DATE, depth=1))
    assert small["children"][0]["children_omitted"] == 40 and "note" not in small
    with pytest.raises(ValueError, match="needs chapter"):
        _run(srv.get_cfr_structure(subchapter="H", date=DATE))
