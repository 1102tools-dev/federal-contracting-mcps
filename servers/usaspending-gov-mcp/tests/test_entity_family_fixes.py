# SPDX-License-Identifier: MIT
"""Regression suite for the 2026-08-16 entity/agency/award-family audit fixes.

Covers, per finding:
  1.  get_recipient_children keyed by uei_or_duns (the /recipient/children/
      endpoint takes a UEI or DUNS; it 400s on hashes, so the old
      hash-validated tool could never succeed). Response array is wrapped
      as {"results": [...], "total": N}.
  2.  get_idv_activity dead sort/order params removed (the API ignores them;
      results are always obligated-amount descending), real hide_edge_cases
      param added.
  3.  get_agency_sub_agencies 'total_outlays' removed from the sort Literal
      (the API rejects it: valid values are name, total_obligations,
      transaction_count, new_award_count).
  4.  Path safety: get_award_detail validates its id (generated prefix or
      numeric internal id), and every path-interpolated id validator rejects
      '/', '..', '%', and backslash ('../references/toptier_agencies' used
      to return the agency list through get_award_detail).
  5.  Recipient hashes accepted case-insensitively, canonicalized to
      lowercase hex + uppercase -C/-R/-P suffix on the wire.
  6.  _validate_fy caps at the CURRENT fiscal year (current + 1 was a
      guaranteed API 422).
  7.  One toptier normalizer across all eight agency tools: short all-digit
      codes are zero-padded everywhere ('97' -> '097').
  8.  404 error translation hints are conditioned on the request path
      (federal-account 404s no longer tell callers to check
      generated_internal_id).
  9.  get_recipient_profile year accepts int or str.
  10. get_federal_account_object_classes documents its cumulative
      (multi-year) totals; no code change, docstring only.

Three tiers, same layout as test_v0_3_features.py:
  1. Validation tests (offline, pre-network argument parsing)
  2. Mock tests (offline, monkeypatch the HTTP plumbing)
  3. Live tests (gated on USASPENDING_LIVE_TESTS=1)
"""

from __future__ import annotations

import asyncio
import os

import httpx as _httpx
import pytest

import usaspending_gov_mcp.server as srv  # noqa: E402
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


class _MockGet:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.response


class _MockPost:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, json):
        self.calls.append((path, dict(json)))
        return self.response


def _patch_children_client(monkeypatch, json_data, status=200):
    """get_recipient_children uses _get_client() directly (array response),
    same pattern as list_states."""
    calls = []

    class _Resp:
        status_code = status

        def raise_for_status(self):
            if status >= 400:
                req = _httpx.Request("GET", "https://api.usaspending.gov" + calls[-1][0])
                resp = _httpx.Response(status, request=req)
                raise _httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)

        def json(self):
            return json_data

    class _MC:
        async def get(self, path, params=None):
            calls.append((path, dict(params or {})))
            return _Resp()

    monkeypatch.setattr(srv, "_get_client", lambda: _MC())
    return calls


LOCKHEED_UEI = "CWM4UN76ZQW8"
LOCKHEED_DUNS = "848028494"
HASH_PARENT = "d7df489c-5a15-3e1b-e7fa-0e93eb94a166-P"
HASH_CHILD = "d7df489c-5a15-3e1b-e7fa-0e93eb94a166-C"
HASH_REGULAR = "7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22-R"
IDV_ID = "CONT_IDV_W91YTZ23A0001_9700"
CONTRACT_ID = "CONT_AWD_W912QR25C0022_9700_-NONE-_-NONE-"


# ===========================================================================
# TIER 1: VALIDATION TESTS (no network)
# ===========================================================================

# --- finding 1: get_recipient_children takes UEI/DUNS, never a hash ---

@pytest.mark.parametrize("hash_value", [HASH_PARENT, HASH_CHILD, HASH_REGULAR])
def test_children_rejects_hashes(hash_value):
    asyncio.run(_call_expect_error(
        "get_recipient_children", "takes a UEI or DUNS", uei_or_duns=hash_value,
    ))


def test_children_rejects_uppercase_hash_as_hash():
    """An uppercase hash must hit the hash-specific guidance, not the
    generic not-a-UEI error."""
    asyncio.run(_call_expect_error(
        "get_recipient_children", "takes a UEI or DUNS",
        uei_or_duns=HASH_PARENT.upper(),
    ))


def test_children_hash_error_routes_to_search_recipients():
    asyncio.run(_call_expect_error(
        "get_recipient_children", "search_recipients", uei_or_duns=HASH_PARENT,
    ))


@pytest.mark.parametrize("bad", [
    "ABC",              # too short
    "CWM4UN76ZQW",      # 11 chars
    "CWM4UN76ZQW88",    # 13 chars
    "84802849",         # 8 digits (not a DUNS)
    "8480284940",       # 10 digits
    "CWM4-N76ZQW8",     # hyphen inside
])
def test_children_rejects_malformed_idents(bad):
    asyncio.run(_call_expect_error(
        "get_recipient_children", "not a 12-character UEI or 9-digit DUNS",
        uei_or_duns=bad,
    ))


def test_children_rejects_empty():
    asyncio.run(_call_expect_error("get_recipient_children", "cannot be empty", uei_or_duns=""))


def test_children_rejects_control_chars():
    asyncio.run(_call_expect_error(
        "get_recipient_children", "control character", uei_or_duns="CWM4UN76\nQW8",
    ))


# --- finding 4: path metacharacters rejected on path-interpolated ids ---

def test_award_detail_path_escape_rejected():
    """THE repro: '../references/toptier_agencies' used to return the agency
    list dressed up as award detail."""
    asyncio.run(_call_expect_error(
        "get_award_detail", "path characters",
        generated_award_id="../references/toptier_agencies",
    ))


@pytest.mark.parametrize("bad_id", [
    "CONT_AWD_../x",
    "CONT_AWD_a/b_9700",
    "CONT_AWD_%2e%2e%2fx",
    "CONT_AWD_a\\b",
    "..",
])
def test_award_detail_path_chars_rejected(bad_id):
    asyncio.run(_call_expect_error(
        "get_award_detail", "path", generated_award_id=bad_id,
    ))


def test_award_detail_bogus_prefix_still_rejected():
    asyncio.run(_call_expect_error(
        "get_award_detail", "not a valid generated award id", generated_award_id="FOO",
    ))


@pytest.mark.parametrize("tool", [
    "get_award_subaward_count",
    "get_award_federal_account_count",
    "get_award_transaction_count",
    "get_award_funding_rollup",
])
def test_count_tools_reject_path_chars(tool):
    asyncio.run(_call_expect_error(
        tool, "path characters", award_id="CONT_AWD_a/b",
    ))


def test_idv_amounts_rejects_path_chars():
    asyncio.run(_call_expect_error(
        "get_idv_amounts", "path characters", award_id="CONT_IDV_a/../b",
    ))


@pytest.mark.parametrize("bad_path", ["..", "Service/../x", "Product%2f5", "a\\b"])
def test_psc_filter_tree_rejects_traversal(bad_path):
    asyncio.run(_call_expect_error(
        "get_psc_filter_tree", "path characters", path=bad_path,
    ))


# --- finding 2: idv_activity sort/order removed ---

def test_idv_activity_rejects_sort_param():
    asyncio.run(_call_expect_error(
        "get_idv_activity", "input", award_id=IDV_ID, sort="obligated_amount",
    ))


def test_idv_activity_rejects_order_param():
    asyncio.run(_call_expect_error(
        "get_idv_activity", "input", award_id=IDV_ID, order="asc",
    ))


# --- finding 3: sub_agencies total_outlays removed from the Literal ---

def test_sub_agencies_total_outlays_rejected():
    """pydantic rejects the removed enum member and its error names the
    valid values."""
    asyncio.run(_call_expect_error(
        "get_agency_sub_agencies", "total_obligations",
        toptier_code="097", sort="total_outlays",
    ))


# --- finding 6: fiscal year capped at current FY ---

def test_fy_next_year_rejected():
    next_fy = srv._current_fiscal_year() + 1
    asyncio.run(_call_expect_error(
        "get_agency_sub_agencies", "out of range",
        toptier_code="097", fiscal_year=next_fy,
    ))


def test_fy_current_year_accepted(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "get_agency_sub_agencies",
        toptier_code="097", fiscal_year=srv._current_fiscal_year(),
    ))
    assert mock.calls[-1][1]["fiscal_year"] == str(srv._current_fiscal_year())


# --- finding 7: unified toptier normalizer ---

def test_budgetary_resources_pads_short_code(monkeypatch):
    """Pre-1.0.1 this tool rejected '97' while get_agency_overview padded it."""
    mock = _MockGet({"agency_data_by_year": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_agency_budgetary_resources", toptier_code="97"))
    assert mock.calls[-1][0] == "/api/v2/agency/097/budgetary_resources/"


def test_overview_rejects_five_digit_code():
    """The old padding helper accepted '12345'; the unified one rejects it."""
    asyncio.run(_call_expect_error(
        "get_agency_overview", "3-4 digit", toptier_code="12345",
    ))


# --- finding 5: case-insensitive recipient hashes ---

def test_hash_validator_canonicalizes_case():
    out = srv._validate_recipient_hash("D7DF489C-5A15-3E1B-E7FA-0E93EB94A166-p")
    assert out == "d7df489c-5a15-3e1b-e7fa-0e93eb94a166-P"


def test_profile_accepts_uppercase_hash(monkeypatch):
    mock = _MockGet({"name": "X"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_recipient_profile", recipient_hash=HASH_PARENT.upper()))
    assert mock.calls[-1][0] == f"/api/v2/recipient/{HASH_PARENT}/"


# --- finding 9: year accepts int ---

def test_profile_year_int_coerced(monkeypatch):
    mock = _MockGet({"name": "X"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_recipient_profile", recipient_hash=HASH_REGULAR, year=2024))
    assert mock.calls[-1][1]["year"] == "2024"


def test_profile_year_str_still_works(monkeypatch):
    mock = _MockGet({"name": "X"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_recipient_profile", recipient_hash=HASH_REGULAR, year="all"))
    assert mock.calls[-1][1]["year"] == "all"


# ===========================================================================
# TIER 2: MOCK TESTS
# ===========================================================================

# --- children plumbing ---

def test_children_uei_uppercased_on_wire(monkeypatch):
    calls = _patch_children_client(monkeypatch, [])
    asyncio.run(_call("get_recipient_children", uei_or_duns="cwm4un76zqw8"))
    assert calls[-1][0] == f"/api/v2/recipient/children/{LOCKHEED_UEI}/"


def test_children_duns_passthrough(monkeypatch):
    calls = _patch_children_client(monkeypatch, [])
    asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_DUNS))
    assert calls[-1][0] == f"/api/v2/recipient/children/{LOCKHEED_DUNS}/"


def test_children_array_wrapped(monkeypatch):
    rows = [{"recipient_id": HASH_CHILD, "name": "LOCKHEED MARTIN CORPORATION"}]
    _patch_children_client(monkeypatch, rows)
    r = asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_UEI))
    d = _payload(r)
    assert d == {"results": rows, "total": 1}


def test_children_empty_array_wrapped(monkeypatch):
    _patch_children_client(monkeypatch, [])
    r = asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_UEI))
    assert _payload(r) == {"results": [], "total": 0}


def test_children_dict_passthrough(monkeypatch):
    _patch_children_client(monkeypatch, {"results": [{"x": 1}]})
    r = asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_UEI))
    assert _payload(r)["results"][0]["x"] == 1


def test_children_year_int_coerced(monkeypatch):
    calls = _patch_children_client(monkeypatch, [])
    asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_UEI, year=2024))
    assert calls[-1][1]["year"] == "2024"


def test_children_year_omitted_when_none(monkeypatch):
    calls = _patch_children_client(monkeypatch, [])
    asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_UEI))
    assert "year" not in calls[-1][1]


def test_children_http_error_translated(monkeypatch):
    _patch_children_client(monkeypatch, [], status=404)
    try:
        asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_UEI))
    except Exception as e:
        msg = str(e)
        assert "404" in msg
        # Path-conditioned hint: recipient endpoints must not get award advice
        assert "generated_internal_id" not in msg
        return
    raise AssertionError("expected 404 error")


# --- finding 8: 404 hint conditioned on request path ---

def _status_error(path):
    req = _httpx.Request("GET", f"https://api.usaspending.gov{path}")
    resp = _httpx.Response(404, request=req, content=b'{"detail":"Not Found"}',
                           headers={"content-type": "application/json"})
    return _httpx.HTTPStatusError("HTTP 404", request=req, response=resp)


def test_404_hint_award_paths():
    msg = srv._format_http_error(_status_error("/api/v2/awards/CONT_AWD_X_9700/"))
    assert "generated_internal_id" in msg


def test_404_hint_idv_paths():
    msg = srv._format_http_error(_status_error("/api/v2/idvs/amounts/CONT_IDV_X/"))
    assert "generated_internal_id" in msg


@pytest.mark.parametrize("path", [
    "/api/v2/federal_accounts/069-X-8083/",
    "/api/v2/recipient/children/CWM4UN76ZQW8/",
    "/api/v2/agency/999/",
    "/api/v2/recipient/state/99/",
])
def test_404_hint_generic_for_non_award_paths(path):
    msg = srv._format_http_error(_status_error(path))
    assert "generated_internal_id" not in msg
    assert "resource not found" in msg


# --- finding 2: idv_activity wire payload ---

def test_idv_activity_payload_no_sort_order(monkeypatch):
    mock = _MockPost({"results": [], "page_metadata": {}})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("get_idv_activity", award_id=IDV_ID))
    _, body = mock.calls[-1]
    assert "sort" not in body and "order" not in body
    assert body["hide_edge_cases"] is False


def test_idv_activity_hide_edge_cases_sent(monkeypatch):
    mock = _MockPost({"results": [], "page_metadata": {}})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("get_idv_activity", award_id=IDV_ID, hide_edge_cases=True))
    assert mock.calls[-1][1]["hide_edge_cases"] is True


# --- finding 4: award_detail id forms ---

def test_award_detail_numeric_internal_id(monkeypatch):
    mock = _MockGet({"id": 291054800})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_award_detail", generated_award_id="291054800"))
    assert mock.calls[-1][0] == "/api/v2/awards/291054800/"


def test_award_detail_generated_id_passthrough(monkeypatch):
    mock = _MockGet({"id": 1})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_award_detail", generated_award_id=CONTRACT_ID))
    assert mock.calls[-1][0] == f"/api/v2/awards/{CONTRACT_ID}/"


def test_psc_filter_tree_legit_drilldown_still_works(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_psc_filter_tree", path="Service/R"))
    assert mock.calls[-1][0] == "/api/v2/references/filter_tree/psc/Service/R/"


# ===========================================================================
# TIER 3: LIVE TESTS (USASPENDING_LIVE_TESTS=1)
# ===========================================================================

@live
def test_live_children_by_duns():
    """DUNS keying works alongside UEI (both verified live 2026-08-16)."""
    r = asyncio.run(_call("get_recipient_children", uei_or_duns=LOCKHEED_DUNS))
    d = _payload(r)
    assert d["total"] >= 1
    assert all(str(row.get("recipient_id", "")).endswith("-C") for row in d["results"])


@live
def test_live_profile_uppercase_hash():
    """The API accepts uppercase hashes; the validator no longer blocks them."""
    r = asyncio.run(_call("get_recipient_profile", recipient_hash=HASH_PARENT.upper()))
    d = _payload(r)
    assert "LOCKHEED" in (d.get("name") or "")


@live
def test_live_idv_activity_obligated_desc():
    """Differential check: results really are obligated-amount descending
    (the fixed ordering the docstring now documents)."""
    r = asyncio.run(_call(
        "get_idv_activity", award_id="CONT_IDV_GS00Q14OADU131_4732", limit=10,
    ))
    d = _payload(r)
    amounts = [row.get("obligated_amount") or 0 for row in d.get("results") or []]
    assert amounts, "expected at least one child order"
    assert amounts == sorted(amounts, reverse=True)


@live
def test_live_award_detail_numeric_id_roundtrip():
    """The awards endpoint accepts the numeric internal id; fetching by the
    generated id and then by the returned numeric id lands on the same award.
    Both calls share one event loop so the module-level httpx client is not
    reused across closed loops."""
    async def _flow():
        r1 = await _call("get_award_detail",
                         generated_award_id="CONT_IDV_GS00Q14OADU131_4732")
        d1 = _payload(r1)
        r2 = await _call("get_award_detail", generated_award_id=str(d1["id"]))
        return d1, _payload(r2)
    d1, d2 = asyncio.run(_flow())
    assert d2["generated_unique_award_id"] == d1["generated_unique_award_id"]
