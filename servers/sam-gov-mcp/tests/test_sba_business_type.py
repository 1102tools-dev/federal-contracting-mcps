# SPDX-License-Identifier: MIT
"""Tests for sba_business_type_code on search_entities (added in 1.0.1).

Background: SAM.gov filters SBA certifications (8(a), HUBZone) through a
dedicated sbaBusinessTypeCode query parameter, separate from businessTypeCode.
Before 1.0.1 the server exposed only businessTypeCode and mislabeled XX as
"8(a) Certified". Per the SAM Functional Data Dictionary ("Business Types"
field), XX is SBA Certified HUBZone Firm and A6 is SBA Certified 8(a) Program
Participant. A9 (SBA-Certified WOSB) and A0 (SBA-Certified EDWOSB) postdate
the dictionary and were pinned from live entity data on 2026-08-16.

Tiers:
  1. Validation tests (offline, validators raise before any HTTP call)
  2. Mock tests (offline, monkeypatch _get to capture wire params)
  3. Live tests (SAM_LIVE_TESTS=1 + SAM_API_KEY, hit production SAM.gov;
     these re-verify the code-to-program mapping against real entity data)
"""

from __future__ import annotations

import asyncio
import os

import pytest

# A fake API key lets pre-network validation run without hitting SAM.gov.
os.environ.setdefault("SAM_API_KEY", "SAM-00000000-0000-0000-0000-000000000000")

import sam_gov_mcp.server as srv  # noqa: E402
from sam_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("SAM_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")


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


class _Mock:
    """Capture last params + return canned response."""
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params, *, base_url=None):
        self.calls.append((path, dict(params)))
        return self.response


# ===========================================================================
# TIER 1: VALIDATION (offline)
# ===========================================================================

@pytest.mark.parametrize("code", ["XX", "xx", "A6", "JT", "A4"])
def test_sba_code_on_business_type_code_redirects(code):
    """SBA certification codes on business_type_code raise a redirect error."""
    asyncio.run(_call_expect_error(
        "search_entities", "sba_business_type_code",
        business_type_code=code,
    ))


def test_sba_business_type_code_rejects_unknown_code():
    asyncio.run(_call_expect_error(
        "search_entities", "not a valid code",
        sba_business_type_code="ZZ",
    ))


def test_sba_business_type_code_rejects_general_code():
    """General self-selected codes are not valid SBA certification codes."""
    asyncio.run(_call_expect_error(
        "search_entities", "not a valid code",
        sba_business_type_code="QF",
    ))


# ===========================================================================
# TIER 2: MOCK (offline, verify wire params)
# ===========================================================================

def test_sba_code_maps_to_sba_wire_param(monkeypatch):
    """sba_business_type_code goes out as sbaBusinessTypeCode, normalized."""
    mock = _Mock({"totalRecords": 0, "entityData": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_entities", sba_business_type_code="a6"))
    _, params = mock.calls[-1]
    assert params["sbaBusinessTypeCode"] == "A6"
    assert "businessTypeCode" not in params


def test_general_and_sba_codes_combine(monkeypatch):
    """Both families can filter in one call, each on its own parameter."""
    mock = _Mock({"totalRecords": 0, "entityData": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_entities", business_type_code="QF", sba_business_type_code="XX",
    ))
    _, params = mock.calls[-1]
    assert params["businessTypeCode"] == "QF"
    assert params["sbaBusinessTypeCode"] == "XX"


# ===========================================================================
# TIER 3: LIVE (guarded; ~4 API calls)
# ===========================================================================

def _sba_entries(entity):
    bt = ((entity.get("coreData") or {}).get("businessTypes") or {})
    return [s for s in srv._as_list(bt.get("sbaBusinessTypeList")) if isinstance(s, dict)]


@live
def test_live_a6_returns_8a_certified_entities():
    """A6 filter returns entities whose SBA list carries A6 = 8(a)."""
    r = asyncio.run(_call(
        "search_entities", sba_business_type_code="A6", size=3,
        include_sections=["entityRegistration", "coreData"],
    ))
    data = _payload(r)
    assert int(data.get("totalRecords") or 0) > 0
    for e in srv._as_list(data.get("entityData")):
        entries = _sba_entries(e)
        a6 = [s for s in entries if s.get("sbaBusinessTypeCode") == "A6"]
        assert a6, f"entity missing A6 in sbaBusinessTypeList: {entries}"
        assert "8(a)" in (a6[0].get("sbaBusinessTypeDesc") or "")


@live
def test_live_xx_returns_hubzone_certified_entities():
    """XX filter returns entities whose SBA list carries XX = HUBZone."""
    r = asyncio.run(_call(
        "search_entities", sba_business_type_code="XX", size=3,
        include_sections=["entityRegistration", "coreData"],
    ))
    data = _payload(r)
    assert int(data.get("totalRecords") or 0) > 0
    for e in srv._as_list(data.get("entityData")):
        entries = _sba_entries(e)
        xx = [s for s in entries if s.get("sbaBusinessTypeCode") == "XX"]
        assert xx, f"entity missing XX in sbaBusinessTypeList: {entries}"
        assert "hubzone" in (xx[0].get("sbaBusinessTypeDesc") or "").lower()


@live
@pytest.mark.parametrize("code", ["JT", "A4", "A9", "A0"])
def test_live_remaining_sba_codes_accepted(code):
    """JT/A4/A9/A0 are accepted by the live API (no count assertion)."""
    r = asyncio.run(_call(
        "search_entities", sba_business_type_code=code, size=1,
        include_sections=["entityRegistration", "coreData"],
    ))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data
