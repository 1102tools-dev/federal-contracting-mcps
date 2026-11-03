# SPDX-License-Identifier: MIT
"""1.1.15: get_cfr_content and lookup_far_clause correct two common slips (offline).

- A date past the title's latest available date (today's, say) used to be
  eCFR's 404. The latest text is returned instead, with a note.
- A clause alternate after the number ('52.219-14 Alt I') used to be a 404.
  The basic clause is returned, with a note that the alternate is inside it
  (or that the clause's text has no such alternate).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import ecfr_mcp.server as srv

FIXTURES = Path(__file__).parent / "fixtures" / "ecfr_xml"
LATEST = "2026-10-30"


def _inside(alternate: str) -> str:
    return (
        f"eCFR has no separate section for 52.219-9 {alternate}, so this is the basic clause 52.219-9, "
        f"with {alternate} printed inside it: a paragraph headed {alternate} and its date, then the changes it makes."
    )


@pytest.fixture
def ecfr(monkeypatch):
    """eCFR stand-in: the latest date is LATEST, and XML comes from a saved clause."""
    calls: list[tuple[str, dict]] = []
    resolved: list[int] = []

    async def get_xml(path, params=None):
        calls.append((path, dict(params or {})))
        return (FIXTURES / "t48_52.219-9.xml").read_text(encoding="utf-8")

    async def resolve(title_number):
        resolved.append(title_number)
        return LATEST

    monkeypatch.setattr(srv, "_get_xml", get_xml)
    monkeypatch.setattr(srv, "_resolve_date", resolve)
    return {"calls": calls, "resolved": resolved}


def _run(coro):
    return asyncio.run(coro)


# --- a date past the latest ---------------------------------------------------

def test_todays_date_reads_the_latest_text_with_a_note(ecfr):
    r = _run(srv.get_cfr_content(section="52.219-9", date="2026-11-03"))
    assert ecfr["calls"][0][0] == f"/api/versioner/v1/full/{LATEST}/title-48.xml"
    assert r["date"] == LATEST
    assert r["note"] == (
        f"eCFR's latest text for title 48 is dated {LATEST} (eCFR runs a few days behind), "
        f"so this is the text as of {LATEST}, not 2026-11-03."
    )
    assert r["paragraphs"]


@pytest.mark.parametrize("date", [LATEST, "2026-10-01", None])
def test_the_latest_or_an_earlier_date_is_unchanged(ecfr, date):
    r = _run(srv.get_cfr_content(section="52.219-9", date=date))
    assert r["date"] == (date or LATEST)
    assert "note" not in r


def test_lookup_far_clause_moves_a_later_date_and_resolves_once(ecfr):
    r = _run(srv.lookup_far_clause("52.219-9", date="2026-11-03"))
    assert r["date"] == LATEST and "not 2026-11-03" in r["note"]
    assert ecfr["calls"][0][1] == {"chapter": "1", "section": "52.219-9"}
    assert ecfr["resolved"] == [48]


def test_raw_xml_says_which_date_it_is(ecfr):
    r = _run(srv.get_cfr_content(section="52.219-9", date="2027-01-01", raw_xml=True))
    assert r["date"] == LATEST and "not 2027-01-01" in r["note"]


@pytest.mark.parametrize("date,message", [
    ("2026-11-31", "not a valid calendar date"),
    ("11/03/2026", "YYYY-MM-DD"),
    ("2026-11-03T00:00:00", "YYYY-MM-DD"),
    ("today", "YYYY-MM-DD"),
    ("current", "not accepted"),
])
def test_invalid_dates_are_still_errors(ecfr, date, message):
    for call in (srv.get_cfr_content(section="52.219-9", date=date), srv.lookup_far_clause("52.219-9", date=date)):
        with pytest.raises(ValueError, match=message):
            _run(call)
    assert ecfr["calls"] == [] and ecfr["resolved"] == []


def test_a_later_date_through_the_mcp_pipeline(ecfr):
    result = _run(srv.mcp.call_tool("lookup_far_clause", {"section_id": "52.219-9 Alt I", "date": "2026-11-03"}))
    data = json.loads(result.content[0].text)
    assert data == result.structured_content
    assert data["date"] == LATEST and data["section"] == "52.219-9"
    assert "not 2026-11-03." in data["note"] and "Alternate I printed inside it" in data["note"]


# --- clause alternates ----------------------------------------------------------

@pytest.mark.parametrize("raw,alternate", [
    ("52.219-9 Alt I", "Alternate I"),
    ("52.219-9 Alt. II", "Alternate II"),
    ("52.219-9 Alternate III", "Alternate III"),
    ("52.219-9 ALT IV", "Alternate IV"),
    ("52.219-9 (Alt I)", "Alternate I"),
    ("52.219-9 (Alternate II)", "Alternate II"),
    ("FAR 52.219-9, Alternate II", "Alternate II"),
    ("52.219-9 alt iii", "Alternate III"),
    ("52.219-9 Alt 2", "Alternate II"),
    ("§ 52.219-9(c) Alt I", "Alternate I"),
])
def test_alternates_return_the_basic_clause(ecfr, raw, alternate):
    for call in (srv.lookup_far_clause(raw), srv.get_cfr_content(section=raw)):
        r = _run(call)
        assert ecfr["calls"][-1][1]["section"] == "52.219-9"
        assert r["section"] == "52.219-9"
        assert r["note"] == _inside(alternate)
        assert any(p.startswith(f"*{alternate}* (") for p in r["paragraphs"])


def test_an_alternate_the_clause_lacks_is_named(ecfr):
    # 52.219-9 has Alternates I-IV; 52.219-14 has none in eCFR's text as of 2026-10-30.
    for call in (srv.lookup_far_clause("48 CFR 52.219–9 Alt V"), srv.get_cfr_content(section="52.219-9 Alt 5")):
        r = _run(call)
        assert r["section"] == "52.219-9"
        assert r["note"] == (
            "eCFR has no separate section for 52.219-9 Alternate V, so this is the basic clause 52.219-9. "
            f"Its text on {LATEST} has no paragraph headed Alternate V."
        )


def test_a_paged_clause_finds_its_alternate_on_any_page(monkeypatch):
    body = "".join(f"<P>({n}) {'Long clause text. ' * 50}</P>" for n in range(100))
    xml = (f'<DIV8 N="52.299-1" TYPE="SECTION"><HEAD>52.299-1 Test clause.</HEAD>{body}'
           '<P><E T="04">Alternate I</E> (JAN 2026). Substitute the following paragraph (a).</P></DIV8>')

    async def get_xml(path, params=None):
        return xml

    async def resolve(title_number):
        return LATEST

    monkeypatch.setattr(srv, "_get_xml", get_xml)
    monkeypatch.setattr(srv, "_resolve_date", resolve)
    first = _run(srv.lookup_far_clause("52.299-1 Alt I"))
    assert first["total_pages"] > 1 and "with Alternate I printed inside it" in first["note"]
    assert not any(p.startswith("*Alternate I* (") for p in first["paragraphs"])  # it is on the last page
    last = _run(srv.lookup_far_clause("52.299-1 Alt I", page=first["total_pages"]))
    assert last["paragraphs"][-1].startswith("*Alternate I* (JAN 2026)") and last["note"] == first["note"]


def test_raw_xml_cannot_check_for_the_alternate(ecfr):
    r = _run(srv.get_cfr_content(section="52.219-9 Alt I", raw_xml=True))
    assert r["note"] == (
        "eCFR has no separate section for 52.219-9 Alternate I, so this is the basic clause 52.219-9. "
        "If it has an Alternate I, it is printed inside its text: a paragraph headed Alternate I and its date, "
        "then the changes it makes."
    )


def test_a_later_date_and_an_alternate_get_both_notes(ecfr):
    for call in (srv.lookup_far_clause("52.219-9 Alt I", date="2026-11-03"),
                 srv.get_cfr_content(section="52.219-9 Alt I", date="2026-11-03")):
        r = _run(call)
        assert r["note"].startswith(f"eCFR's latest text for title 48 is dated {LATEST}")
        assert r["note"].endswith("then the changes it makes.")


@pytest.mark.parametrize("raw,expected", [
    ("52.219-9 Alt VI", "52.219-9 Alt VI"),     # FAR alternates stop at V
    ("52.219-9Alt I", "52.219-9Alt I"),         # no separator: not an alternate
    ("Alt I", "Alt I"),
    ("(Alt I)", None),
    ("15.305(a)(2)", "15.305"),
    ("FAR 52.212-5(b) Alt II", "52.212-5"),
    ("DFARS 252.204-7012", "252.204-7012"),
    ("§ 9.104-1", "9.104-1"),
    ("48 CFR 15.305", "15.305"),
])
def test_alternate_stripping_keeps_the_other_cleanups(raw, expected):
    assert srv._coerce_cfr_str(raw, field="section", strip_prefixes=True, strip_cites=True, strip_alternates=True) == expected


def test_parts_and_subparts_are_not_touched(ecfr):
    assert srv._coerce_cfr_str("52 Alt I", field="part", strip_prefixes=True) == "52 Alt I"
    assert srv._alternate_named(52) is None and srv._alternate_named("52.219-9") is None
