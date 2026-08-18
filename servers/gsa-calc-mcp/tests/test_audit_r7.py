# Round 7 (2026-08-18 super-cycle): live contract anchors, one call per test
# (the experience differential uses two calls by necessity: r10-usaspending
# lesson, flip a param and demand a difference).
import asyncio
import json
import os

import pytest

from .test_round_6 import _call, _payload

LIVE = os.environ.get("GSA_CALC_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires GSA_CALC_LIVE_TESTS=1")


def _text(data) -> str:
    return json.dumps(data, default=str)


@live
@pytest.mark.live_smoke
def test_live_smoke_keyword_search_returns_rates():
    data = _payload(asyncio.run(_call("keyword_search", keyword="engineer")))
    assert "$" in _text(data) or "rate" in _text(data).lower()


@live
@pytest.mark.live_smoke
def test_live_smoke_experience_min_is_gte_not_exact():
    # 1.0.1 wave: experience_min was exact-match instead of >=. A >= filter
    # at 5 years must return at least as many results as at 10 years.
    async def _both():
        a = await _call("filtered_browse", experience_min=5)
        b = await _call("filtered_browse", experience_min=10)
        return a, b
    lo_r, hi_r = asyncio.run(_both())
    lo, hi = _payload(lo_r), _payload(hi_r)
    def count(d):
        t = _text(d)
        import re
        m = re.search(r'"(?:total|count|totalRecords|total_records)":\s*(\d+)', t)
        return int(m.group(1)) if m else len(t)
    assert count(lo) >= count(hi)


@live
@pytest.mark.live_smoke
def test_live_smoke_live_sin_still_valid():
    data = _payload(asyncio.run(_call("sin_analysis", sin_code="54151S")))
    assert "54151" in _text(data)


@live
@pytest.mark.live_smoke
def test_live_smoke_suggest_contains_alive():
    data = _payload(asyncio.run(_call("suggest_contains", field="labor_category", term="architect")))
    assert len(_text(data)) > 50
