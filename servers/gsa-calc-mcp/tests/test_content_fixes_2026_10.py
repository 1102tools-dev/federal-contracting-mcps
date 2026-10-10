# SPDX-License-Identifier: MIT
"""1.0.12: fixes from the 2026-10-10 hosted content test (findings G-1 to G-12).

Each offline test feeds a canned CALC+ body shaped like the real responses
saved during the content test and failed on 1.0.11. Live tests
(GSA_CALC_LIVE_TESTS=1) compare the tool against the CALC+ API directly.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

import gsa_calc_mcp.server as srv
from gsa_calc_mcp.server import mcp


LIVE = os.environ.get("GSA_CALC_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1 to run live API calls")

_BAH = "BOOZ ALLEN HAMILTON INC"
_API = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


class _MockGet:
    def __init__(self, body):
        self.body = body
        self.calls: list[str] = []

    async def __call__(self, qs: str):
        self.calls.append(qs)
        return self.body


def _api(qs: str) -> dict:
    """Direct CALC+ API call for live comparisons (not through the tool)."""
    r = httpx.get(_API + "?" + qs, timeout=60, headers={"User-Agent": "gsa-calc-mcp-tests"})
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# G-5: vendor_rate_card rows carry worksite
# ---------------------------------------------------------------------------

def _booz_pair_response() -> dict:
    """Same title, contract, SIN and education at two prices: the two rows
    differ only by worksite (saved Booz Allen page, GS00F008DA)."""
    common = {
        "labor_category": "ACQUISITION SPECIALIST, LEVEL I",
        "education_level": "Bachelors",
        "min_years_experience": 0,
        "sin": "541611",
        "idv_piid": "GS00F008DA",
        "business_size": "O",
        "vendor_name": _BAH,
        "contract_end": "2027-10-14",
    }
    return {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {"_source": {**common, "current_price": 148.7508, "worksite": "Customer_Facility"}},
                {"_source": {**common, "current_price": 180.6478, "worksite": "Contractor_Facility"}},
            ],
        },
        "aggregations": {
            "vendor_name": {"buckets": [{"key": _BAH, "doc_count": 2}]},
            "wage_stats": {"count": 2},
        },
    }


def test_g5_vendor_rate_card_rows_include_worksite(monkeypatch):
    monkeypatch.setattr(srv, "_get", _MockGet(_booz_pair_response()))
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="booz")))
    sites = [row.get("worksite") for row in r["rates"]]
    assert sites == ["Customer_Facility", "Contractor_Facility"], r["rates"]
    assert r["rates"][0]["contract_end"] == "2027-10-14"


@live
def test_live_g5_vendor_rate_card_worksite_matches_api():
    r = _payload(asyncio.run(_call("vendor_rate_card", vendor_name="Booz Allen", page_size=20)))
    api = _api("search=vendor_name:BOOZ+ALLEN+HAMILTON+INC&page=1&page_size=20&ordering=labor_category&sort=asc")
    api_sites = [h["_source"].get("worksite") for h in api["hits"]["hits"]]
    tool_sites = [row.get("worksite") for row in r["rates"]]
    assert tool_sites == api_sites
    assert all(tool_sites)
