# Round 11 (2026-08-18): paced live campaign, ~95 calls, zero throttle events,
# ZERO new defects. These tests pin the API contracts the server depends on
# (discovered or re-stamped live) plus the deprecation posture the server
# deliberately holds. Campaign narrative: testing.md "Round 11".
import asyncio
import json
import os

import httpx
import pytest

import usaspending_gov_mcp.server as srv

from .test_entity_family_fixes import _call, _payload

LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
BASE = "https://api.usaspending.gov"
FY24 = {"time_period": [{"start_date": "2023-10-01", "end_date": "2024-09-30"}]}
CONTRACTS = ["A", "B", "C", "D"]


def _post(path, body):
    with httpx.Client(timeout=60, headers={"User-Agent": "usaspending-mcp-tests/r11"}) as c:
        return c.post(BASE + path, json=body)


# ---------------------------------------------------------------- offline

def test_search_payload_pins_subawards_flag(monkeypatch):
    """Upstream has signaled `subawards` will be superseded by
    `spending_level` (responses already stamp spending_level and the
    subaward-grouped endpoint accepts the param, live-verified r11). The
    server still sends subawards=False deliberately; this test exists so the
    eventual migration is a conscious change, not silent drift."""
    seen = {}

    async def fake_post(path, payload):
        seen["path"] = path
        seen["payload"] = payload
        return {"results": [], "page_metadata": {}}

    monkeypatch.setattr(srv, "_post", fake_post)
    asyncio.run(_call(
        "search_awards", time_period_start="2023-10-01", time_period_end="2024-09-30"))
    assert seen["payload"]["subawards"] is False
    assert "spending_level" not in seen["payload"]


def test_search_returns_upstream_response_unmodified(monkeypatch):
    """search_awards passes the API response through raw, which means the
    API's `messages` advisories (e.g. the 2007-10-01 search floor) reach the
    caller. Pinned so a future normalizer does not silently strip them."""
    upstream = {"results": [{"Award ID": "X"}], "page_metadata": {"page": 1},
                "messages": ["For searches, time period start and end dates are "
                             "currently limited to an earliest date of 2007-10-01."]}

    async def fake_post(path, payload):
        return upstream

    monkeypatch.setattr(srv, "_post", fake_post)
    data = _payload(asyncio.run(_call(
        "search_awards", time_period_start="2023-10-01", time_period_end="2024-09-30")))
    assert data.get("messages"), "upstream messages must survive to the caller"


# ---------------------------------------------------------------- live smoke

@live
@pytest.mark.live_smoke
def test_live_smoke_f_codes_valid_in_award_type_filter():
    # r10 added F001/F002 to the grants group; r11 live-verified the API
    # accepts them (8,542 F-code awards alone in FY24 at campaign time).
    r = _post("/api/v2/search/spending_by_award_count/",
              {"filters": {**FY24, "award_type_codes": ["F001", "F002"]}})
    assert r.status_code == 200
    assert r.json()["results"]["grants"] >= 0


@live
@pytest.mark.live_smoke
def test_live_smoke_page_semantics_one_based_records():
    body = {"filters": {**FY24, "award_type_codes": CONTRACTS},
            "fields": ["Award ID", "Recipient Name", "Award Amount"],
            "sort": "Award Amount", "order": "desc"}
    sup = _post("/api/v2/search/spending_by_award/", {**body, "limit": 4, "page": 1}).json()
    pair = _post("/api/v2/search/spending_by_award/", {**body, "limit": 2, "page": 2}).json()
    sup_ids = [x.get("generated_internal_id") for x in sup.get("results", [])]
    pair_ids = [x.get("generated_internal_id") for x in pair.get("results", [])]
    if len(sup_ids) >= 4 and len(pair_ids) == 2:
        assert pair_ids == sup_ids[2:4], "page semantics changed upstream"


@live
@pytest.mark.live_smoke
def test_live_smoke_past_end_page_is_honest():
    # Contrast with SAM Opportunities (returns phantom rows past the end):
    # USASpending returns an empty page with hasNext=False. r11-verified.
    r = _post("/api/v2/search/spending_by_award/",
              {"filters": {**FY24, "award_type_codes": CONTRACTS,
                           "recipient_search_text": ["KM99JJBNQ9M5"]},
               "fields": ["Award ID", "Award Amount"], "limit": 50, "page": 500,
               "sort": "Award Amount", "order": "desc"}).json()
    # Past-end pages OMIT the results key entirely (None) or send an empty
    # list; both are honest-empty. hasNext goes False either way.
    assert not r.get("results")
    assert r.get("page_metadata", {}).get("hasNext") is False


@live
@pytest.mark.live_smoke
def test_live_smoke_months_partition_fiscal_year():
    m = _post("/api/v2/search/spending_over_time/",
              {"group": "month", "filters": {**FY24, "award_type_codes": CONTRACTS}}).json()
    y = _post("/api/v2/search/spending_over_time/",
              {"group": "fiscal_year", "filters": {**FY24, "award_type_codes": CONTRACTS}}).json()
    ms = sum(float(x.get("aggregated_amount") or 0) for x in m.get("results", []))
    ys = sum(float(x.get("aggregated_amount") or 0) for x in y.get("results", []))
    if ys:
        assert abs(ms - ys) / ys < 0.001, "monthly buckets no longer partition the FY"


@live
@pytest.mark.live_smoke
def test_live_smoke_search_floor_fails_loud():
    # Below the upstream 2007-10-01 search floor the API 422s; it does NOT
    # silently clamp. If this ever flips to 200, re-audit for clamping.
    r = _post("/api/v2/search/spending_by_award_count/",
              {"filters": {"time_period": [{"start_date": "2004-10-01",
                                            "end_date": "2005-09-30"}],
                           "award_type_codes": CONTRACTS}})
    assert r.status_code == 422


@live
@pytest.mark.live_smoke
def test_live_smoke_sub_agency_sort_enum_exact():
    # The API enumerates its valid sorts in the 400 body; the tool's Literal
    # must stay equal to that list (r10 lesson: sweep enums against live).
    with httpx.Client(timeout=60) as c:
        r = c.get(BASE + "/api/v2/agency/097/sub_agency/?sort=bogus_field")
    assert r.status_code == 400
    valid = set(json.loads(r.text)["detail"].split("[")[1].split("]")[0]
                .replace("'", "").replace(" ", "").split(","))
    assert valid == {"name", "total_obligations", "transaction_count", "new_award_count"}


@live
@pytest.mark.live_smoke
def test_live_smoke_recipient_children_still_works():
    # r10's never-worked tool, re-stamped: 217 children for the sample UEI
    # at campaign time. Any 4xx here means the rekeyed endpoint regressed.
    with httpx.Client(timeout=60) as c:
        r = c.get(BASE + "/api/v2/recipient/children/ZFN2JJXBLZT3/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
