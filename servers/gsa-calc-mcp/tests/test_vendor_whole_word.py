# SPDX-License-Identifier: MIT
"""1.0.23: vendor_rate_card and GSA's substring vendor discovery.

suggest-contains matches inside words, so 'SAIC' found 'SAICAM CORPORATION,
INC.' (an electrical contractor) and returned its card as SAIC's.
"""
from __future__ import annotations

import asyncio

import pytest

import gsa_calc_mcp.server as srv
from gsa_calc_mcp.server import mcp


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


def _rates(vendor: str) -> dict:
    row = {"labor_category": "Analyst", "current_price": 100.0, "vendor_name": vendor}
    return {"hits": {"total": {"value": 1, "relation": "eq"}, "hits": [{"_source": row}]},
            "aggregations": {"labor_category": {"buckets": [{"key": "Analyst", "doc_count": 1}],
                                                "sum_other_doc_count": 0}}}


class _Gsa:
    """Answers suggest-contains with the given vendors, then a one-row card."""

    def __init__(self, vendors: list[tuple[str, int]]):
        self.vendors = vendors
        self.searched: list[str] = []

    async def __call__(self, qs: str):
        if "suggest-contains=" in qs:
            buckets = [{"key": k, "doc_count": c} for k, c in self.vendors]
            return {"hits": {"total": {"value": 0}, "hits": []},
                    "aggregations": {"vendor_name": {"buckets": buckets, "sum_other_doc_count": 0}}}
        self.searched.append(qs)
        return _rates("x")


def _card(monkeypatch, vendors, name):
    gsa = _Gsa(vendors)
    monkeypatch.setattr(srv, "_get", gsa)
    return gsa, _payload(asyncio.run(mcp.call_tool("vendor_rate_card", {"vendor_name": name})))


def test_acronym_inside_a_longer_name_is_not_that_vendor(monkeypatch):
    gsa, r = _card(monkeypatch, [("SAICAM CORPORATION, INC.", 2)], "SAIC")
    assert "No vendor named 'SAIC'" in r["error"]
    assert "SAICAM CORPORATION, INC." in r["error"]
    assert "Science Applications" in r["error"]
    assert r["_candidates"] == [{"value": "SAICAM CORPORATION, INC.", "count": 2}]
    assert "rates" not in r and gsa.searched == []


def test_whole_word_match_wins_over_a_bigger_substring_match(monkeypatch):
    vendors = [("SAICAM CORPORATION, INC.", 50), ("SAIC GEMINI, INC.", 3)]
    gsa, r = _card(monkeypatch, vendors, "SAIC")
    assert r["vendor"] == "SAIC GEMINI, INC."
    assert "among names with it as a whole word" in r["_note"]
    assert "_match_note" not in r


def test_lowercase_partial_name_still_returns_a_card_with_a_note(monkeypatch):
    gsa, r = _card(monkeypatch, [("LOCKHEED MARTIN CORPORATION", 40)], "lockh")
    assert r["vendor"] == "LOCKHEED MARTIN CORPORATION"
    assert "matched only inside the longer name" in r["_match_note"]


def test_partial_name_that_is_a_whole_word_is_unchanged(monkeypatch):
    gsa, r = _card(monkeypatch, [("BOOZ ALLEN HAMILTON INC", 1900)], "booz")
    assert r["vendor"] == "BOOZ ALLEN HAMILTON INC"
    assert "_match_note" not in r and "_note" not in r
    assert "error" not in r


def test_full_name_with_suffix_inside_a_longer_name_is_not_that_vendor(monkeypatch):
    vendors = [("REEL IMPACT, INC.", 27), ("INFOPACT, INC.", 5)]
    gsa, r = _card(monkeypatch, vendors, "PACT, INC.")
    assert "No vendor named 'PACT, INC.'" in r["error"]
    assert "REEL IMPACT, INC." in r["error"]
    assert "rates" not in r and gsa.searched == []
