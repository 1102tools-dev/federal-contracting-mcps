# Suite-wide guards added in round 11 (2026-08), ported from sam-gov-mcp.
# USASpending has no documented rate limits and no DRF throttling in its
# source, but the paced-audit etiquette applies anyway: when live tests run,
# anything named *live* waits 1-2 s first. Offline runs are unaffected.
import os
import random
import time

import pytest

LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_smoke: minimal live anchor set (run with -m live_smoke; needs "
        "USASPENDING_LIVE_TESTS=1; ~10 paced calls, keyless API)",
    )


@pytest.fixture(autouse=True)
def _pace_live_calls(request):
    if LIVE and "live" in request.node.name:
        time.sleep(random.uniform(1.0, 2.0))
    yield
