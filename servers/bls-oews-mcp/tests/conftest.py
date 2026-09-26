# Suite-wide guards. Every tool answers from the bundled OEWS database, so
# the offline suite must never touch the network: _no_network fails any test
# that opens a socket. Only tests marked live_parity (run with
# BLS_LIVE_TESTS=1) may reach api.bls.gov, to compare bundled values with
# the live API.
import os
import socket

import pytest

LIVE = os.environ.get("BLS_LIVE_TESTS") == "1"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_parity: compares bundled values with the live BLS API "
        "(needs BLS_LIVE_TESTS=1; no key required)",
    )


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
