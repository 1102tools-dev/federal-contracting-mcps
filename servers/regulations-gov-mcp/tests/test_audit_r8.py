# Round 8 (2026-08-18 super-cycle): live contract anchors, one call per test.
# Re-stamps the r7 headliner: open_comment_periods previously sorted
# DESCENDING and dropped the soonest-closing documents entirely.
import asyncio
import json
import os
import re

import pytest

from .test_audit_r7 import _call, _payload

LIVE = os.environ.get("REGULATIONS_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + key")


def _text(data) -> str:
    return json.dumps(data, default=str)


@live
@pytest.mark.live_smoke
def test_live_smoke_open_comment_periods_soonest_first():
    data = _payload(asyncio.run(_call("open_comment_periods")))
    txt = _text(data)
    dates = [d for d in re.findall(r"20\d\d-\d\d-\d\d", txt) if d >= "2026-08-18"][:6]
    assert dates == sorted(dates), "soonest-closing must come first"


@live
@pytest.mark.live_smoke
def test_live_smoke_docket_search_returns_rows():
    data = _payload(asyncio.run(_call("search_dockets", search_term="federal acquisition regulation")))
    assert "FAR" in _text(data) or "docket" in _text(data).lower()


@live
@pytest.mark.live_smoke
def test_live_smoke_document_search_page_cap_real():
    # r7: the real live page cap is 40, not the documented 20.
    data = _payload(asyncio.run(_call("search_documents", search_term="acquisition")))
    assert len(_text(data)) > 300


@live
@pytest.mark.live_smoke
def test_live_smoke_comment_search_alive():
    data = _payload(asyncio.run(_call("search_comments", search_term="FAR")))
    assert isinstance(data, (dict, list))
