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

import federal_api_pacing as pacing_module  # noqa: E402
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


@pytest.mark.asyncio
async def test_same_process_concurrent_requests_serialize_before_file_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OverlapRejectingFileLock:
        active = False

        def __init__(self, *_args, **_kwargs) -> None:
            self.held = False

        def acquire(self, **_kwargs) -> None:
            if type(self).active:
                raise RuntimeError("overlapping same-process file-lock acquisition")
            type(self).active = True
            self.held = True

        def release(self) -> None:
            if self.held:
                type(self).active = False
                self.held = False

    monkeypatch.setattr(pacing_module, "FileLock", OverlapRejectingFileLock)
    entered = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []
    first_pacer = FederalApiPacer(bucket="example.gov", default_interval=0.01, pacing_dir=tmp_path)
    second_pacer = FederalApiPacer(bucket="example.gov", default_interval=0.01, pacing_dir=tmp_path)

    async def first() -> None:
        async with first_pacer.request_slot():
            order.append("first")
            entered.set()
            await release_first.wait()

    async def second() -> None:
        await entered.wait()
        async with second_pacer.request_slot():
            order.append("second")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await entered.wait()
    await asyncio.sleep(0.02)
    assert order == ["first"]
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert order == ["first", "second"]


def test_all_http_sites_are_paced_and_helpers_are_synchronized() -> None:
    expected_counts = {
        "acquisition-gov-mcp/src/acquisition_gov_mcp/server.py": 1,
        "bls-oews-mcp/src/bls_oews_mcp/server.py": 1,
        "ecfr-mcp/src/ecfr_mcp/server.py": 3,  # JSON + shared/XML-specific gates
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


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["normal", "request_error", "cancelled", "state_error"])
async def test_request_slot_releases_lock_across_executor_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_mode: str
) -> None:
    """Real file locks must release even when to_thread switches workers."""
    from concurrent.futures import ThreadPoolExecutor
    from functools import partial
    import threading

    from filelock import FileLock

    loop = asyncio.get_running_loop()
    locks = []
    threads: dict[str, set[int]] = {}
    real_write_state = FederalApiPacer._write_state

    def tracked_lock(*args, **kwargs):
        lock = FileLock(*args, **kwargs)
        locks.append(lock)
        return lock

    clock = FakeClock()
    pacer = FederalApiPacer(
        bucket="thread-switch.gov", default_interval=0.01,
        environment={}, pacing_dir=tmp_path, clock=clock.now, sleep=clock.sleep,
    )
    monkeypatch.setattr(pacing_module, "FileLock", tracked_lock)

    with ThreadPoolExecutor(max_workers=1) as acquire_pool, ThreadPoolExecutor(max_workers=1) as other_pool:
        async def forced_to_thread(func, /, *args, **kwargs):
            name = getattr(func, "__name__", "other")
            def invoke():
                threads.setdefault(name, set()).add(threading.get_ident())
                return func(*args, **kwargs)
            pool = acquire_pool if name == "acquire" else other_pool
            return await loop.run_in_executor(pool, invoke)

        monkeypatch.setattr(pacing_module.asyncio, "to_thread", forced_to_thread)
        try:
            for _ in range(3):
                def broken_write(*args):
                    raise OSError("simulated state write failure")
                if exit_mode == "state_error":
                    monkeypatch.setattr(pacer, "_write_state", broken_write)

                async def request():
                    async with pacer.request_slot():
                        if exit_mode == "request_error":
                            raise ValueError("simulated upstream failure")
                        if exit_mode == "cancelled":
                            asyncio.current_task().cancel()
                            await asyncio.sleep(0)

                expected = {"request_error": ValueError, "cancelled": asyncio.CancelledError,
                            "state_error": OSError}.get(exit_mode)
                if expected:
                    with pytest.raises(expected):
                        await asyncio.create_task(request())
                else:
                    await asyncio.create_task(request())

                # A fresh instance must acquire the actual OS lock after every exit.
                # This catches the old silent release no-op without a hanging test.
                probe = FileLock(str(tmp_path / f"{pacer._identity()}.lock"))
                with probe.acquire(timeout=0.2):
                    pass
                monkeypatch.setattr(pacer, "_write_state", real_write_state)
            # Blocking state writes still run off-loop; lock operations do not.
            assert "acquire" not in threads
            assert "release" not in threads
        finally:
            # Also release a leaked pre-fix lock on its original acquiring thread.
            for lock in locks:
                await loop.run_in_executor(acquire_pool, partial(lock.release, force=True))


@pytest.mark.asyncio
async def test_cancel_waiting_for_file_lock_does_not_leave_an_orphan_acquire(tmp_path: Path) -> None:
    from filelock import FileLock

    pacer = FederalApiPacer(bucket="busy.gov", default_interval=0.01, environment={}, pacing_dir=tmp_path)
    holder = FileLock(str(tmp_path / f"{pacer._identity()}.lock"))
    entered = asyncio.Event()

    async def request():
        async with pacer.request_slot():
            entered.set()

    with holder.acquire(timeout=0):
        task = asyncio.create_task(request())
        await asyncio.sleep(0.08)
        assert not task.done()
        assert not entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.wait_for(request(), timeout=2)
    assert entered.is_set()
    with FileLock(holder.lock_file).acquire(timeout=0.2):
        pass
