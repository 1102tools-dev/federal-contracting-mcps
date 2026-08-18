# Round 8 (2026-08-18 super-cycle): live contract anchors, one call per test.
# Re-stamps the r7 headliners: the Penasco->Taos county resolution that was
# wrongly flagged as an API error, and the OCONUS empty-success trap.
import asyncio
import json
import os

import pytest

from .test_audit_r7 import _call, _payload

LIVE = os.environ.get("MCP_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1 + PERDIEM_API_KEY")


def _text(data) -> str:
    return json.dumps(data, default=str)


@live
@pytest.mark.live_smoke
def test_live_smoke_penasco_resolves_without_false_warning():
    # r7: the API correctly resolves Penasco to Taos County; the old code
    # stamped a false WARNING on that correct answer.
    data = _payload(asyncio.run(_call("lookup_city_perdiem", city="Penasco", state="NM")))
    txt = _text(data).lower()
    assert "taos" in txt
    assert "warning" not in txt or "correct" in txt


@live
@pytest.mark.live_smoke
def test_live_smoke_standard_conus_zip_fallback():
    data = _payload(asyncio.run(_call("lookup_zip_perdiem", zip_code="78239")))
    txt = _text(data).lower()
    assert "lodging" in txt or "per diem" in txt or "rate" in txt


@live
@pytest.mark.live_smoke
def test_live_smoke_oconus_is_explicit_not_empty():
    # r7: OCONUS lookups must explain themselves, never empty-success.
    data = _payload(asyncio.run(_call("lookup_city_perdiem", city="Honolulu", state="HI")))
    txt = _text(data).lower()
    assert len(txt) > 80
    assert ("oconus" in txt or "department of defense" in txt or "dod" in txt
            or "state department" in txt or "rate" in txt)


@live
@pytest.mark.live_smoke
def test_live_smoke_mie_tier_table_alive():
    data = _payload(asyncio.run(_call("get_mie_breakdown")))
    txt = _text(data).lower()
    assert "breakfast" in txt or "dinner" in txt or "incidental" in txt
