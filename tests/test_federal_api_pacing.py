from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from federal_api_pacing import FederalApiPacer, RequestSlot  # noqa: E402


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.value = now
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


@pytest.mark.asyncio
async def test_default_interval_and_override(tmp_path: Path) -> None:
    clock = FakeClock()
    env: dict[str, str] = {}
    pacer = FederalApiPacer(
        bucket="example.gov",
        default_interval=3,
        environment=env,
        clock=clock.now,
        sleep=clock.sleep,
        pacing_dir=tmp_path,
    )
    async with pacer.request_slot():
        pass
    clock.value += 0.5
    async with pacer.request_slot():
        pass
    assert clock.sleeps == [pytest.approx(2.5)]

    env["FEDERAL_API_MIN_INTERVAL_SECONDS"] = "0"
    clock.value += 0.1
    async with pacer.request_slot():
        pass
    assert len(clock.sleeps) == 1


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "invalid"])
def test_invalid_override_fails_before_request(value: str, tmp_path: Path) -> None:
    pacer = FederalApiPacer(
        bucket="example.gov",
        default_interval=3,
        environment={"FEDERAL_API_MIN_INTERVAL_SECONDS": value},
        pacing_dir=tmp_path,
    )
    with pytest.raises(RuntimeError, match="finite, non-negative"):
        pacer.configured_interval()


def test_shared_and_distinct_lock_identities_do_not_expose_keys(tmp_path: Path) -> None:
    a = FederalApiPacer(
        bucket="api.data.gov", default_interval=4, credential="secret-a", pacing_dir=tmp_path
    )
    b = FederalApiPacer(
        bucket="api.data.gov", default_interval=4, credential="secret-a", pacing_dir=tmp_path
    )
    c = FederalApiPacer(
        bucket="api.data.gov", default_interval=4, credential="secret-b", pacing_dir=tmp_path
    )
    assert a._identity() == b._identity()
    assert a._identity() != c._identity()
    assert "secret" not in a._identity()


def test_retry_after_numeric_http_date_and_absent() -> None:
    slot = RequestSlot(now=lambda: 1_000.0)
    numeric = httpx.Response(429, headers={"Retry-After": "12", "X-RateLimit-Remaining": "0"})
    slot.observe_response(numeric)
    assert slot.cooldown_until == pytest.approx(1_012.0)
    assert slot.diagnostics["remaining"] == "0"

    slot = RequestSlot(now=lambda: 1_000.0)
    date_value = format_datetime(datetime.fromtimestamp(1_020.0, tz=timezone.utc))
    slot.observe_response(httpx.Response(429, headers={"Retry-After": date_value}))
    assert slot.cooldown_until == pytest.approx(1_020.0)

    slot = RequestSlot(now=lambda: 1_000.0)
    absent = httpx.Response(429)
    slot.observe_response(absent)
    with pytest.raises(RuntimeError, match="No undocumented lockout duration"):
        slot.raise_if_rate_limited(absent, service="Test API")


def test_cross_process_serialization(tmp_path: Path) -> None:
    output = tmp_path / "starts.jsonl"
    code = """
import asyncio, json, os, sys, time
sys.path.insert(0, sys.argv[1])
from federal_api_pacing import FederalApiPacer
async def main():
    pacer = FederalApiPacer(bucket='api.data.gov', default_interval=0.2, credential='shared')
    async with pacer.request_slot():
        with open(sys.argv[2], 'a', encoding='utf-8') as stream:
            stream.write(json.dumps({'started': time.time()}) + '\\n')
asyncio.run(main())
"""
    env = os.environ.copy()
    env["FEDERAL_API_PACING_DIR"] = str(tmp_path / "state")
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(ROOT / "shared"), str(output)],
            env=env,
        )
        for _ in range(2)
    ]
    for process in processes:
        assert process.wait(timeout=10) == 0
    starts = sorted(json.loads(line)["started"] for line in output.read_text().splitlines())
    assert starts[1] - starts[0] >= 0.18


def test_all_http_sites_are_paced_and_helpers_are_synchronized() -> None:
    expected_counts = {
        "acquisition-gov-mcp/src/acquisition_gov_mcp/server.py": 1,
        "bls-oews-mcp/src/bls_oews_mcp/server.py": 1,
        "ecfr-mcp/src/ecfr_mcp/server.py": 2,
        "federal-register-mcp/src/federal_register_mcp/server.py": 1,
        "gsa-calc-mcp/src/gsa_calc_mcp/server.py": 1,
        "gsa-perdiem-mcp/src/gsa_perdiem_mcp/server.py": 1,
        "regulations-gov-mcp/src/regulationsgov_mcp/server.py": 1,
        "sam-gov-mcp/src/sam_gov_mcp/server.py": 1,
        "usaspending-gov-mcp/src/usaspending_gov_mcp/server.py": 4,
    }
    canonical = (ROOT / "shared" / "federal_api_pacing.py").read_bytes()
    for relative, count in expected_counts.items():
        server_path = ROOT / "servers" / relative
        source = server_path.read_text(encoding="utf-8")
        assert source.count(".request_slot()") == count
        assert "await asyncio.sleep(0.3)" not in source
        assert (server_path.parent / "_pacing.py").read_bytes() == canonical
