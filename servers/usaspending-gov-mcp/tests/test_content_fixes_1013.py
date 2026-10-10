# SPDX-License-Identifier: MIT
"""Regression suite for the 2026-10-10 content test fixes (1.0.13).

Each test names the finding it covers (findings-usaspending.md, U1-U13) and
fails on 1.0.12. Offline: the HTTP plumbing is replaced with recorders that
return trimmed copies of the live API answers seen on 2026-10-10.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import usaspending_gov_mcp.server as srv
from usaspending_gov_mcp.server import mcp


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


@pytest.fixture
def fy2027(monkeypatch):
    """Pin 'today' to the content test date: FY2027 began ten days ago."""
    monkeypatch.setattr(srv, "_current_fiscal_year", lambda: 2027)
    return 2027


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


def _payload(result):
    if hasattr(result, "structured_content"):
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return result[1] if isinstance(result, tuple) else result


class _MockGet:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        r = self.response(path, params) if callable(self.response) else self.response
        return __import__("copy").deepcopy(r)


class _MockPost:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, json):
        self.calls.append((path, __import__("copy").deepcopy(json)))
        r = self.response(path, json) if callable(self.response) else self.response
        return __import__("copy").deepcopy(r)


# ===========================================================================
# U12 (P1): agency tools default to the last completed fiscal year
# ===========================================================================

# API answer for GET agency/097/obligations_by_award_category/ with no
# fiscal_year on 2026-10-10 (FY2027 to date): no year field at all.
DOD_OBLIGATIONS_FY2026 = {
    "total_aggregated_amount": 389671359952.77,
    "results": [{"category": "contracts", "aggregated_amount": 380016133917.28}],
}


def test_u12_obligations_by_award_category_defaults_to_last_completed_fy(monkeypatch, fy2027):
    mock = _MockGet(DOD_OBLIGATIONS_FY2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_agency_obligations_by_award_category", toptier_code="097")))
    assert mock.calls[-1][1].get("fiscal_year") == "2026"
    assert out["fiscal_year"] == 2026
    assert "last completed" in out["fiscal_year_note"]


def test_u12_obligations_by_award_category_echoes_explicit_year(monkeypatch, fy2027):
    mock = _MockGet(DOD_OBLIGATIONS_FY2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call(
        "get_agency_obligations_by_award_category", toptier_code="097", fiscal_year=2025,
    )))
    assert mock.calls[-1][1]["fiscal_year"] == "2025"
    assert out["fiscal_year"] == 2025
    assert "fiscal_year_note" not in out


@pytest.mark.parametrize("tool,endpoint", [
    ("get_agency_overview", "/api/v2/agency/097/"),
    ("get_agency_awards", "/api/v2/agency/097/awards/"),
    ("get_agency_sub_agencies", "/api/v2/agency/097/sub_agency/"),
    ("get_agency_federal_accounts", "/api/v2/agency/097/federal_account/"),
    ("get_agency_object_classes", "/api/v2/agency/097/object_class/"),
    ("get_agency_program_activities", "/api/v2/agency/097/program_activity/"),
    ("get_agency_obligations_by_award_category", "/api/v2/agency/097/obligations_by_award_category/"),
])
def test_u12_every_agency_tool_defaults_to_last_completed_fy(monkeypatch, fy2027, tool, endpoint):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call(tool, toptier_code="097")))
    path, params = mock.calls[-1]
    assert path == endpoint
    assert params.get("fiscal_year") == "2026", f"{tool} sent {params}"
    assert out["fiscal_year"] == 2026


def test_u12_current_fy_still_reachable(monkeypatch, fy2027):
    mock = _MockGet({"fiscal_year": 2027, "obligations": 1000000.0})
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_agency_awards", toptier_code="097", fiscal_year=2027)))
    assert mock.calls[-1][1]["fiscal_year"] == "2027"
    assert out["fiscal_year"] == 2027


def test_u12_docstrings_say_the_default():
    for name in (
        "get_agency_overview", "get_agency_awards", "get_agency_sub_agencies",
        "get_agency_federal_accounts", "get_agency_object_classes",
        "get_agency_program_activities", "get_agency_obligations_by_award_category",
    ):
        doc = " ".join(getattr(srv, name).__doc__.split())
        assert "last completed fiscal year" in doc, name


# ===========================================================================
# U11 (P1): get_state_profile gets a year, defaults to last completed FY
# ===========================================================================

# API answer for recipient/state/24/?year=2026 (trimmed): no year field.
MD_2026 = {
    "name": "Maryland", "code": "MD", "fips": "24", "type": "state",
    "total_prime_amount": 96666882297.68, "total_prime_awards": 117372,
}


def test_u11_state_profile_defaults_to_last_completed_fy(monkeypatch, fy2027):
    mock = _MockGet(MD_2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_state_profile", state_fips="24")))
    assert mock.calls[-1] == ("/api/v2/recipient/state/24/", {"year": "2026"})
    assert out["fiscal_year"] == 2026
    assert "year=2027" in out["fiscal_year_note"]


@pytest.mark.parametrize("year,sent,echo", [
    (2025, "2025", 2025), ("2024", "2024", 2024), ("all", "all", "all"), ("latest", "latest", "latest"),
])
def test_u11_state_profile_year_param(monkeypatch, fy2027, year, sent, echo):
    mock = _MockGet(MD_2026)
    monkeypatch.setattr(srv, "_get", mock)
    out = _payload(asyncio.run(_call("get_state_profile", state_fips="24", year=year)))
    assert mock.calls[-1][1] == {"year": sent}
    assert out["fiscal_year"] == echo
    assert "fiscal_year_note" not in out


@pytest.mark.parametrize("bad", ["2007", "2028", "last", "20x6"])
def test_u11_state_profile_rejects_bad_year(fy2027, bad):
    with pytest.raises(Exception):
        asyncio.run(_call("get_state_profile", state_fips="24", year=bad))


def test_u11_state_profile_docstring_no_longer_promises_breakdowns():
    doc = " ".join(srv.get_state_profile.__doc__.split())
    assert "top agencies, top recipients" not in doc
    assert "last completed fiscal year" in doc


@live
@pytest.mark.live_smoke
def test_live_u11_u12_defaults_return_full_year():
    """Live: the no-year answers are the full last-completed-FY figures."""
    fy = srv._last_completed_fiscal_year()

    async def both():
        a = await _call("get_agency_obligations_by_award_category", toptier_code="097")
        b = await _call("get_state_profile", state_fips="24")
        return _payload(a), _payload(b)

    out, st = asyncio.run(both())
    assert out["fiscal_year"] == fy
    assert out["total_aggregated_amount"] > 100e9
    assert st["fiscal_year"] == fy
    assert st["total_prime_amount"] > 10e9
