# Suite-wide guards. Every tool answers from the bundled OEWS database, so
# the offline suite must never touch the network: _no_network fails any test
# that opens a socket. Only tests marked live_parity (run with
# BLS_LIVE_TESTS=1) may reach api.bls.gov, to compare bundled values with
# the live API.
import os
import socket

import pytest

LIVE = os.environ.get("BLS_LIVE_TESTS") == "1"

# Release whose exact values the golden tests pin. A newer bundled release
# skips them; tests/test_live_parity.py checks that release against BLS.
GOLDEN_RELEASE = "2025A01"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_parity: compares bundled values with the live BLS API "
        "(needs BLS_LIVE_TESTS=1; no key required)",
    )
    config.addinivalue_line(
        "markers",
        f"golden: pins exact values from the {GOLDEN_RELEASE} release; skipped "
        "when a newer release is bundled",
    )


def pytest_collection_modifyitems(config, items):
    from bls_oews_mcp import snapshot

    bundled = snapshot.manifest()["release"]["code"]
    if bundled == GOLDEN_RELEASE:
        return
    skip = pytest.mark.skip(
        reason=f"golden values are from {GOLDEN_RELEASE}; bundled {bundled} is checked by live parity"
    )
    for item in items:
        if item.get_closest_marker("golden"):
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory):
    """Decompress the bundled database into a per-run directory, never the
    user's cache."""
    os.environ["BLS_OEWS_DATA_DIR"] = str(tmp_path_factory.mktemp("oews-data"))
    yield


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("live_parity"):
        if not LIVE:
            pytest.skip("requires BLS_LIVE_TESTS=1")
        yield
        return

    def _blocked(*args, **kwargs):
        raise AssertionError(f"offline test opened a network connection: {args[:1]}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield
