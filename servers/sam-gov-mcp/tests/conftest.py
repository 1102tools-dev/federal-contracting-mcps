# Suite-wide guards added in round 10 (2026-08).
#
# Pacing: the live-gated suite once fired ~400 unpaced calls in 105 seconds
# and burned a key's whole daily quota mid-run. When SAM_LIVE_TESTS=1, every
# test whose name contains "live" now waits 2-4 s first, matching the paced
# live-audit discipline (see tests/live_audit/). Offline runs are unaffected.
import os
import random
import time

import pytest

LIVE = os.environ.get("SAM_LIVE_TESTS") == "1"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_smoke: minimal live anchor set (run with -m live_smoke; needs "
        "SAM_LIVE_TESTS=1 and SAM_API_KEY; ~10 paced calls total)",
    )


@pytest.fixture(autouse=True)
def _pace_live_calls(request):
    if LIVE and "live" in request.node.name:
        time.sleep(random.uniform(2.0, 4.0))
    yield


@pytest.fixture(autouse=True)
def _disable_offline_network_pacing(monkeypatch):
    if not LIVE:
        monkeypatch.setenv("FEDERAL_API_MIN_INTERVAL_SECONDS", "0")
    yield
