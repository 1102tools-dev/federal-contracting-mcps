"""Real reopening/source-metadata guidance without inventing controlling dates."""
import asyncio
import json
from pathlib import Path

import federal_register_mcp.server as srv
from .test_round_6 import _call, _payload

FIXTURES = Path(__file__).parent / "fixtures"


def test_empty_indexed_periods_explain_reopening_recovery(monkeypatch):
    reopening = json.loads((FIXTURES / "reopening_19895.json").read_text())
    assert reopening["comments_close_on"] == "2026-08-24"
    assert "October 29, 2026" in reopening["dates"]

    async def search(**kwargs):
        assert kwargs["agencies"] == ["coast-guard"]
        assert kwargs["term"] == "Streamlined Inspection Program"
        return {"count": 0, "results": []}

    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call(
        "open_comment_periods", agencies=["coast-guard"],
        term="Streamlined Inspection Program", limit=100)))
    assert data["complete"] is True
    assert data["total_open"] == 0
    note = data["deadline_verification_note"]
    assert "metadata" in note and "DATES" in note
    assert "reopening" in note and "search_documents" in note
    assert "get_document" in note


def test_nonempty_indexed_periods_also_qualify_controlling_dates(monkeypatch):
    source = json.loads((FIXTURES / "open_phmsa_round6.json").read_text())

    async def search(**kwargs):
        return source

    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call("open_comment_periods", limit=100)))
    assert data["total_open"] == source["count"]
    assert "controlling deadline" in data["deadline_verification_note"]
    assert "complete" in data["deadline_verification_note"]


def test_source_counts_dates_and_sorting_are_preserved(monkeypatch):
    source = json.loads((FIXTURES / "open_phmsa_round6.json").read_text())

    async def search(**kwargs):
        return source

    monkeypatch.setattr(srv, "search_documents", search)
    data = _payload(asyncio.run(_call("open_comment_periods", limit=100)))
    expected = sorted(source["results"], key=lambda d: d.get("comments_close_on") or "9999-99-99")
    assert data["documents"] == expected
    assert data["total_open"] == data["scanned"] == source["count"] == 3
    assert data["complete"] is True and data["truncated"] is False
