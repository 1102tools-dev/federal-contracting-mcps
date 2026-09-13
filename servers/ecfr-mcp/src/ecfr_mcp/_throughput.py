"""eCFR-only, cross-process rolling budget and concurrent request pacing.

All clients sharing a pacing directory share the budget. State counts attempts,
not successful responses. File locks are held across I/O only for the two
concurrency slots; the state lock is released before sleeping or network I/O.
"""
from __future__ import annotations

import asyncio
import json
import math
from contextlib import asynccontextmanager

from filelock import FileLock, Timeout as FileLockTimeout

from ._pacing import FederalApiPacer, RequestSlot, _process_lock


class EcfrPacer(FederalApiPacer):
    MAX_REQUESTS = 500
    WINDOW_SECONDS = 300.0
    MAX_IN_FLIGHT = 2

    def __init__(self, **kwargs):
        super().__init__(bucket="www.ecfr.gov", default_interval=0.6, **kwargs)

    @asynccontextmanager
    async def _state_lock(self):
        root = self._root()
        key = f"{root.resolve()}::{self._identity()}"
        async with _process_lock(key):
            lock = FileLock(str(root / f"{self._identity()}.lock"), mode=0o600)
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except FileLockTimeout:
                    await asyncio.sleep(0.01)
            try:
                yield root / f"{self._identity()}.json"
            finally:
                lock.release()

    def _budget_state(self, path):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as exc:
            # Losing history could silently reset the budget: fail closed.
            raise RuntimeError("eCFR pacing state is unreadable") from exc
        if not isinstance(state, dict):
            raise RuntimeError("eCFR pacing state is invalid")
        for key in ("last_completed", "last_started", "cooldown_until"):
            value = state.get(key, 0)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise RuntimeError("eCFR pacing timestamp is invalid")
        starts = state.get("starts", [])
        if not isinstance(starts, list) or any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
            for v in starts
        ):
            raise RuntimeError("eCFR pacing history is invalid")
        return state

    @asynccontextmanager
    async def _concurrency_slot(self):
        root = self._root()
        # OS locks recover automatically after process termination. Same-loop
        # locks prevent filelock's same-thread ownership from bypassing the cap.
        while True:
            for number in range(self.MAX_IN_FLIGHT):
                path = root / f"{self._identity()}.slot-{number}.lock"
                local = _process_lock(str(path.resolve()))
                if local.locked():
                    continue
                await local.acquire()
                lock = FileLock(str(path), mode=0o600)
                try:
                    lock.acquire(timeout=0)
                except FileLockTimeout:
                    local.release()
                    continue
                except BaseException:
                    local.release()
                    raise
                try:
                    yield
                finally:
                    lock.release()
                    local.release()
                return
            await asyncio.sleep(0.01)

    async def _reserve(self, interval):
        while True:
            async with self._state_lock() as path:
                state = self._budget_state(path)
                now = self.clock()
                starts = sorted(t for t in state.get("starts", []) if t > now - self.WINDOW_SECONDS)
                ready = max(state.get("last_started", 0) + interval,
                            state.get("cooldown_until", 0))
                # Respect a recent request recorded by the previous pacer.
                if "last_started" not in state:
                    ready = max(ready, state.get("last_completed", 0) + 3.0)
                if len(starts) >= self.MAX_REQUESTS:
                    ready = max(ready, starts[-self.MAX_REQUESTS] + self.WINDOW_SECONDS)
                delay = ready - now
                if delay <= 0:
                    state.update(starts=starts + [now], last_started=now)
                    self._write_state(path, state)
                    return
            await self.sleep(delay)

    async def _record_cooldown(self, slot):
        if not slot.cooldown_until:
            return
        async with self._state_lock() as path:
            state = self._budget_state(path)
            state['cooldown_until'] = max(state.get('cooldown_until', 0), slot.cooldown_until)
            self._write_state(path, state)

    @asynccontextmanager
    async def request_slot(self):
        interval = self.configured_interval()
        # Explicit existing opt-out is retained for offline tests and callers
        # who manage pacing externally. Hosted configuration never uses zero.
        if interval == 0:
            yield RequestSlot(now=self.clock)
            return
        # A positive override may slow this provider, never exceed our policy.
        interval = max(0.6, interval)
        async with self._concurrency_slot():
            await self._reserve(interval)
            slot = RequestSlot(now=self.clock)
            try:
                yield slot
            finally:
                # Persist Retry-After even when a caller cancels after observing
                # the response. No token is refunded on error or cancellation.
                task = asyncio.create_task(self._record_cooldown(slot))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise


class EcfrXmlPacer(FederalApiPacer):
    """Keep XML misses serialized; JSON work need not wait behind this lane."""
    def __init__(self, **kwargs):
        super().__init__(bucket="www.ecfr.gov:xml", default_interval=3.0, **kwargs)

    def configured_interval(self):
        interval = super().configured_interval()
        return 0 if interval == 0 else max(3.0, interval)
