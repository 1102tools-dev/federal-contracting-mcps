# Suite-wide guards added in the 2026-08 super-cycle (pattern from sam-gov r10).
# When live tests run, anything named *live* waits before each test so a full
# live pass can never burst-hammer the API or burn a keyed quota.
import os
import random
import time

import pytest

LIVE = os.environ.get("REGULATIONS_LIVE_TESTS") == "1"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_smoke: minimal live anchor set (run with -m live_smoke; needs "
        "the live gate env var and REGULATIONS_GOV_API_KEY)",
    )


@pytest.fixture(autouse=True)
def _pace_live_calls(request):
    if LIVE and "live" in request.node.name:
        time.sleep(random.uniform(1.0, 1.8))
    yield


# Each test runs in its own event loop (asyncio.run), but the server caches
# an AsyncClient bound to the first loop; reset it so every test gets a
# fresh client (same pattern as the per-file _reset_client fixtures).
import importlib

_srv = importlib.import_module("regulationsgov_mcp.server")


@pytest.fixture(autouse=True)
def _fresh_async_client():
    for attr in ("_client", "_http_client", "client"):
        if hasattr(_srv, attr):
            setattr(_srv, attr, None)
    yield
    for attr in ("_client", "_http_client", "client"):
        if hasattr(_srv, attr):
            setattr(_srv, attr, None)
