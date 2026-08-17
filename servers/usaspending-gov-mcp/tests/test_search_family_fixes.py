# SPDX-License-Identifier: MIT
"""Regression suite for the 2026-08-16 search-family live audit fixes.

Covers, per finding:
  1.  spending_by_transaction recipient_uei sent as recipient_search_text
      (the API's recipient_id filter expects a hash and silently matched
      nothing for a UEI)
  2.  AWARD_TYPE_GROUPS includes the newer F001-F010 FABS codes
  3.  spending_by_category / spending_by_geography no-filter guards
  4.  new_awards_over_time always sends the required time_period
  5.  grants use DEFAULT_GRANT_FIELDS (CFDA Number, Award Type);
      direct_payments/other use DEFAULT_ASSISTANCE_FIELDS
  6.  def_codes exposed on all five search/aggregation tools
  7.  set_aside / extent_competed / contract_pricing codes uppercased
      (case-sensitive upstream, lowercase silently returned zero)
  8.  autocomplete_naics exclude_retired no longer starves results at 50

Three tiers, same layout as test_v0_3_features.py:
  1. Validation tests (offline, pre-network argument parsing)
  2. Mock tests (offline, monkeypatch _post to capture the wire payload)
  3. Live tests (gated on USASPENDING_LIVE_TESTS=1)
"""

from __future__ import annotations

import asyncio
import os

import pytest

import usaspending_gov_mcp.server as srv  # noqa: E402
from usaspending_gov_mcp.constants import (  # noqa: E402
    AWARD_TYPE_GROUPS,
    DEFAULT_ASSISTANCE_FIELDS,
    DEFAULT_CONTRACT_FIELDS,
    DEFAULT_GRANT_FIELDS,
)
from usaspending_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


async def _call_expect_error(name: str, match: str, **kwargs):
    try:
        await mcp.call_tool(name, kwargs)
    except Exception as e:
        assert match.lower() in str(e).lower(), f"expected {match!r} in error, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    # mcp>=2.0 returns CallToolResult; mcp 1.x returned (content, structured).
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


class _MockPost:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, json):
        self.calls.append((path, dict(json)))
        return self.response


# Real values captured via live probes (2026-08-16)
LOCKHEED_UEI = "G4KDGE4JFFK7"
LOCKHEED_HASH = "6cf5fb1b-4988-d087-5dc1-70939d8fc6c4-C"
Q1_2024 = {"time_period_start": "2024-01-01", "time_period_end": "2024-03-31"}


# ===========================================================================
# TIER 1: VALIDATION TESTS (no network)
# ===========================================================================

def test_spending_by_category_no_filters_raises():
    asyncio.run(_call_expect_error(
        "spending_by_category", "requires at least one filter", category="recipient"))


def test_spending_by_category_award_type_alone_raises():
    # award_type_codes is a scope, not a filter; alone it must still raise.
    asyncio.run(_call_expect_error(
        "spending_by_category", "requires at least one filter",
        category="naics", award_type="contracts"))


def test_spending_by_geography_no_filters_raises():
    asyncio.run(_call_expect_error(
        "spending_by_geography", "requires at least one filter"))


def test_spending_by_geography_award_type_alone_raises():
    asyncio.run(_call_expect_error(
        "spending_by_geography", "requires at least one filter",
        award_type="contracts"))


def test_new_awards_over_time_reversed_dates_raise():
    asyncio.run(_call_expect_error(
        "new_awards_over_time", "is after",
        recipient_id=LOCKHEED_HASH,
        time_period_start="2025-01-01", time_period_end="2024-01-01"))


def test_search_awards_def_codes_empty_array_raises():
    asyncio.run(_call_expect_error(
        "search_awards", "empty array", def_codes=[]))


def test_spending_by_geography_def_codes_empty_array_raises():
    asyncio.run(_call_expect_error(
        "spending_by_geography", "empty array", def_codes=[]))


def test_award_type_groups_contain_f_codes():
    assert {"F001", "F002"}.issubset(AWARD_TYPE_GROUPS["grants"])
    assert {"F003", "F004"}.issubset(AWARD_TYPE_GROUPS["loans"])
    assert {"F006", "F007"}.issubset(AWARD_TYPE_GROUPS["direct_payments"])
    assert {"F005", "F008", "F009", "F010"}.issubset(AWARD_TYPE_GROUPS["other"])


def test_assistance_field_sets_use_award_type_not_contract_award_type():
    for fields in (DEFAULT_GRANT_FIELDS, DEFAULT_ASSISTANCE_FIELDS):
        assert "Award Type" in fields
        assert "Contract Award Type" not in fields
    assert "CFDA Number" in DEFAULT_GRANT_FIELDS
    assert "CFDA Number" not in DEFAULT_ASSISTANCE_FIELDS


# ===========================================================================
# TIER 2: MOCK TESTS (monkeypatch _post, capture the wire payload)
# ===========================================================================

_EMPTY_SEARCH = {"page_metadata": {"page": 1, "hasNext": False}, "results": []}


def test_recipient_uei_sent_as_recipient_search_text(monkeypatch):
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("spending_by_transaction", recipient_uei=LOCKHEED_UEI, **Q1_2024))
    _, body = mock.calls[-1]
    filters = body["filters"]
    assert filters["recipient_search_text"] == [LOCKHEED_UEI]
    # The old bug: a UEI in recipient_id silently matches nothing.
    assert "recipient_id" not in filters


def test_recipient_uei_uppercased_on_wire(monkeypatch):
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("spending_by_transaction",
                      recipient_uei=LOCKHEED_UEI.lower(), **Q1_2024))
    _, body = mock.calls[-1]
    assert body["filters"]["recipient_search_text"] == [LOCKHEED_UEI]


def test_code_filters_uppercased_on_wire(monkeypatch):
    # Lowercase values previously returned HTTP 200 with zero results.
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(
        "search_awards",
        contract_pricing_type_codes=["j"],
        set_aside_type_codes=["8an"],
        extent_competed_type_codes=["a", "cdo"],
        **Q1_2024,
    ))
    _, body = mock.calls[-1]
    filters = body["filters"]
    assert filters["contract_pricing_type_codes"] == ["J"]
    assert filters["set_aside_type_codes"] == ["8AN"]
    assert filters["extent_competed_type_codes"] == ["A", "CDO"]


@pytest.mark.parametrize("tool,kwargs", [
    ("search_awards", {}),
    ("get_award_count", {}),
    ("spending_over_time", {}),
    ("spending_by_category", {"category": "recipient"}),
    ("spending_by_geography", {}),
])
def test_def_codes_pass_through(tool, kwargs, monkeypatch):
    # def_codes is a real filter, so it alone must satisfy the filter guards.
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(tool, def_codes=["L", 9], **kwargs))
    _, body = mock.calls[-1]
    assert body["filters"]["def_codes"] == ["L", "9"]


@pytest.mark.parametrize("award_type,expected_subset", [
    ("grants", {"02", "05", "F001", "F002"}),
    ("loans", {"07", "08", "F003", "F004"}),
    ("direct_payments", {"06", "10", "F006", "F007"}),
    ("other", {"09", "11", "-1", "F005", "F008", "F009", "F010"}),
])
def test_award_type_codes_include_f_codes_on_wire(award_type, expected_subset, monkeypatch):
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_awards", award_type=award_type, keywords=["research"]))
    _, body = mock.calls[-1]
    assert expected_subset.issubset(set(body["filters"]["award_type_codes"]))


def test_grants_fields_use_grant_field_set(monkeypatch):
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_awards", award_type="grants", keywords=["research"]))
    _, body = mock.calls[-1]
    assert "CFDA Number" in body["fields"]
    assert "Award Type" in body["fields"]
    assert "Contract Award Type" not in body["fields"]


@pytest.mark.parametrize("award_type", ["direct_payments", "other"])
def test_assistance_fields_for_direct_payments_and_other(award_type, monkeypatch):
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_awards", award_type=award_type, keywords=["research"]))
    _, body = mock.calls[-1]
    assert "Award Type" in body["fields"]
    assert "Contract Award Type" not in body["fields"]
    assert "CFDA Number" not in body["fields"]


def test_contract_fields_unchanged(monkeypatch):
    mock = _MockPost(_EMPTY_SEARCH)
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_awards", award_type="contracts", keywords=["research"]))
    _, body = mock.calls[-1]
    assert body["fields"] == list(DEFAULT_CONTRACT_FIELDS)


def test_new_awards_over_time_always_sends_time_period(monkeypatch):
    mock = _MockPost({"group": "fiscal_year", "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("new_awards_over_time", recipient_id=LOCKHEED_HASH))
    _, body = mock.calls[-1]
    assert body["filters"]["time_period"] == [
        {"start_date": "2007-10-01", "end_date": "2099-09-30"}
    ]


def test_new_awards_over_time_explicit_dates_pass_through(monkeypatch):
    mock = _MockPost({"group": "month", "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("new_awards_over_time", recipient_id=LOCKHEED_HASH,
                      time_period_start="2020-10-01", time_period_end="2021-09-30"))
    _, body = mock.calls[-1]
    assert body["filters"]["time_period"] == [
        {"start_date": "2020-10-01", "end_date": "2021-09-30"}
    ]


def test_autocomplete_naics_upstream_limit_not_starved(monkeypatch):
    # Old code capped the upstream fetch at 50, silently truncating active
    # codes below the requested limit whenever more than 50 codes matched.
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("autocomplete_naics", search_text="54", limit=100,
                      exclude_retired=True))
    _, body = mock.calls[-1]
    assert body["limit"] == 300


def test_autocomplete_naics_upstream_limit_exact_without_filter(monkeypatch):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("autocomplete_naics", search_text="54", limit=100,
                      exclude_retired=False))
    _, body = mock.calls[-1]
    assert body["limit"] == 100


# ===========================================================================
# TIER 3: LIVE TESTS (USASPENDING_LIVE_TESTS=1)
# ===========================================================================

@live
def test_live_recipient_uei_returns_rows():
    result = _payload(asyncio.run(_call(
        "spending_by_transaction", award_type="contracts",
        recipient_uei=LOCKHEED_UEI, limit=3, **Q1_2024)))
    rows = result.get("results") or []
    assert rows, "recipient_uei filter returned zero rows (regression of the recipient_id bug)"
    assert "LOCKHEED" in rows[0]["Recipient Name"].upper()


@live
def test_live_lowercase_pricing_code_returns_rows():
    result = _payload(asyncio.run(_call(
        "search_awards", contract_pricing_type_codes=["j"], limit=1, **Q1_2024)))
    assert result.get("results"), "lowercase pricing code returned zero rows"


@live
def test_live_grants_rows_carry_cfda_and_award_type():
    result = _payload(asyncio.run(_call(
        "search_awards", award_type="grants", keywords=["research"],
        limit=1, **Q1_2024)))
    rows = result.get("results") or []
    assert rows
    assert "CFDA Number" in rows[0]
    assert "Award Type" in rows[0]
    assert "Contract Award Type" not in rows[0]


@live
@pytest.mark.parametrize("award_type,keyword", [
    ("grants", "research"),
    ("loans", "disaster"),
    ("direct_payments", "housing"),
    ("other", "insurance"),
])
def test_live_mixed_f_code_families_accepted(award_type, keyword):
    # The API 422s when award_type_codes mixes families; the F-codes must be
    # accepted alongside the legacy codes of their own family.
    result = _payload(asyncio.run(_call(
        "search_awards", award_type=award_type, keywords=[keyword],
        limit=1, **Q1_2024)))
    assert "results" in result


@live
def test_live_new_awards_over_time_minimal_call():
    result = _payload(asyncio.run(_call(
        "new_awards_over_time", recipient_id=LOCKHEED_HASH, group="fiscal_year")))
    assert result.get("results"), "minimal call (no dates) should return rows"
