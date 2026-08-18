# Round 7 (2026-08-18 super-cycle): live contract anchors, one call per test.
# Re-stamps the 1.0.2-wave headliners against production through the real
# tool pipeline. Gated + paced by conftest.
import asyncio
import json
import os

import pytest

from .test_1_0_2_audit import _call, _payload

LIVE = os.environ.get("ECFR_LIVE_TESTS") == "1" or os.environ.get("MCP_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires ECFR_LIVE_TESTS=1")


def _text(data) -> str:
    return json.dumps(data, default=str)


@live
@pytest.mark.live_smoke
def test_live_smoke_title48_structure_has_hsar_chapters():
    # 1.0.2 wave: the chapter whitelist was missing 9 chapters (HSAR etc.).
    # Chapter 99 (CAS) must be visible in the live Title 48 structure.
    data = _payload(asyncio.run(_call("get_cfr_structure", title_number=48)))
    assert '"99"' in _text(data) or "chapter 99" in _text(data).lower()


@live
@pytest.mark.live_smoke
def test_live_smoke_far_clause_lookup_flagship():
    data = _payload(asyncio.run(_call("lookup_far_clause", section_id="52.212-3")))
    assert "52.212-3" in _text(data)


@live
@pytest.mark.live_smoke
def test_live_smoke_search_returns_rows():
    data = _payload(asyncio.run(_call("search_cfr", query="simplified acquisition threshold")))
    assert _text(data).count("48") >= 1 and len(_text(data)) > 200


@live
@pytest.mark.live_smoke
def test_live_smoke_latest_date_is_current():
    data = _payload(asyncio.run(_call("get_latest_date")))
    assert "2026" in _text(data) or "2025" in _text(data)


@live
@pytest.mark.live_smoke
def test_live_smoke_corrections_endpoint_alive():
    data = _payload(asyncio.run(_call("get_corrections", title_number=48)))
    assert isinstance(data, (dict, list))
