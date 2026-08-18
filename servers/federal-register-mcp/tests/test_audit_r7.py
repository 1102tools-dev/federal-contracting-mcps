# Round 7 (2026-08-18 super-cycle): live contract anchors, one call per test.
# Re-stamps the 1.0.1-wave headliners (pre-2011 lockout, soonest-closing
# comment periods, FAR case completeness) through the real tool pipeline.
import asyncio
import json
import os

import pytest

from .test_round_6 import _call, _payload

LIVE = os.environ.get("FR_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")


def _text(data) -> str:
    return json.dumps(data, default=str)


@live
@pytest.mark.live_smoke
def test_live_smoke_far_case_2017_016_completeness():
    # Post-release verification anchor: this case went from 1 to 19 documents
    # after the 1.0.1 fix. Tolerant floor: it can only grow.
    data = _payload(asyncio.run(_call("far_case_history", docket_id="FAR Case 2017-016")))
    assert _text(data).count("document_number") >= 15 or _text(data).count("2017-016") >= 15


@live
@pytest.mark.live_smoke
def test_live_smoke_pre2011_documents_reachable():
    # 1.0.1 wave: pre-2011 document numbers were rejected (17-year lockout).
    data = _payload(asyncio.run(_call(
        "search_documents", term="federal acquisition regulation",
        pub_date_gte="2005-01-01", pub_date_lte="2005-12-31")))
    assert len(_text(data)) > 300


@live
@pytest.mark.live_smoke
def test_live_smoke_open_comment_periods_soonest_first():
    # 1.0.1 wave: this tool sorted descending and DROPPED the soonest-closing
    # documents. Closing dates must now come back ascending.
    data = _payload(asyncio.run(_call("open_comment_periods", term="acquisition")))
    txt = _text(data)
    import re
    dates = re.findall(r"20\d\d-\d\d-\d\d", txt)
    close_like = [d for d in dates if d >= "2026-08-18"][:5]
    assert close_like == sorted(close_like), "comment close dates not ascending"


@live
@pytest.mark.live_smoke
def test_live_smoke_agencies_reference_alive():
    data = _payload(asyncio.run(_call("list_agencies")))
    assert "defense" in _text(data).lower()
