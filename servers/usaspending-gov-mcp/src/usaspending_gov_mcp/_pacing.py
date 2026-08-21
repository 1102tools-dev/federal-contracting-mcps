# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Cross-process anti-burst pacing for 1102tools federal API clients."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from filelock import FileLock
from platformdirs import user_cache_path

MIN_INTERVAL_ENV = "FEDERAL_API_MIN_INTERVAL_SECONDS"
PACING_DIR_ENV = "FEDERAL_API_PACING_DIR"


def _finite_non_negative(raw: str, *, variable: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{variable} must be a finite, non-negative number of seconds."
        ) from exc
    if not math.isfinite(value) or value < 0:
        raise RuntimeError(
            f"{variable} must be a finite, non-negative number of seconds."
        )
    return value


def _retry_after_epoch(value: str | None, now: float) -> float | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    try:
        seconds = _finite_non_negative(cleaned, variable="Retry-After")
        return now + seconds
    except RuntimeError:
        pass
    try:
        parsed = parsedate_to_datetime(cleaned)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(now, parsed.timestamp())


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    wanted = {
        "retry-after": "retry_after",
        "x-ratelimit-limit": "limit",
        "x-ratelimit-remaining": "remaining",
        "x-ratelimit-reset": "reset",
        "ratelimit-limit": "limit",
        "ratelimit-remaining": "remaining",
        "ratelimit-reset": "reset",
    }
    result: dict[str, str] = {}
    for name, value in headers.items():
        target = wanted.get(name.lower())
        if target and target not in result:
            result[target] = str(value)[:200]
    return result


@dataclass
class RequestSlot:
    """State for one paced upstream request while its process lock is held."""

    now: Callable[[], float]
    cooldown_until: float = 0.0
    diagnostics: dict[str, str] = field(default_factory=dict)

    def observe_response(self, response: Any) -> None:
        headers = getattr(response, "headers", {}) or {}
        self.diagnostics = _safe_headers(headers)
        if getattr(response, "status_code", None) != 429:
            return
        retry_at = _retry_after_epoch(self.diagnostics.get("retry_after"), self.now())
        if retry_at is not None:
            self.cooldown_until = max(self.cooldown_until, retry_at)

    def raise_if_rate_limited(
        self,
        response: Any,
        *,
        service: str,
        guidance: str | None = None,
    ) -> None:
        if getattr(response, "status_code", None) != 429:
            return
        details: list[str] = []
        if guidance:
            details.append(guidance)
        retry_after = self.diagnostics.get("retry_after")
        if retry_after:
            details.append(
                f"The provider returned Retry-After={retry_after!r}; "
                "the shared local cooldown has been recorded."
            )
        else:
            details.append(
                "The provider did not return Retry-After. No undocumented "
                "lockout duration was assumed and no automatic retry was attempted."
            )
        visible = {
            key: value for key, value in self.diagnostics.items() if key != "retry_after"
        }
        if visible:
            details.append(f"Rate-limit diagnostics: {visible}.")
        raise RuntimeError(f"{service} rate limited the request. {' '.join(details)}")


class FederalApiPacer:
    """Coordinate minimum intervals and provider cooldowns across processes."""

    def __init__(
        self,
        *,
        bucket: str,
        default_interval: float,
        credential: str | None = None,
        environment: MutableMapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        pacing_dir: Path | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("bucket must not be empty")
        if not math.isfinite(default_interval) or default_interval < 0:
            raise ValueError("default_interval must be finite and non-negative")
        self.bucket = bucket.strip().lower()
        self.default_interval = float(default_interval)
        self.credential = credential.strip() if credential else None
        self.environment = environment if environment is not None else os.environ
        self.clock = clock
        self.sleep = sleep
        self._pacing_dir = pacing_dir

    def configured_interval(self) -> float:
        raw = self.environment.get(MIN_INTERVAL_ENV)
        if raw is None or not raw.strip():
            return self.default_interval
        return _finite_non_negative(raw.strip(), variable=MIN_INTERVAL_ENV)

    def _root(self) -> Path:
        if self._pacing_dir is not None:
            root = self._pacing_dir
        else:
            override = self.environment.get(PACING_DIR_ENV, "").strip()
            root = Path(override).expanduser() if override else (
                user_cache_path("1102tools") / "federal-api-pacing"
            )
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return root

    def _identity(self) -> str:
        secret_fingerprint = "public"
        if self.credential:
            secret_fingerprint = hashlib.sha256(
                self.credential.encode("utf-8")
            ).hexdigest()
        material = f"{self.bucket}\0{secret_fingerprint}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:32]

    @staticmethod
    def _read_state(path: Path) -> dict[str, float]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {}
        state: dict[str, float] = {}
        for key in ("last_completed", "cooldown_until"):
            value = data.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                state[key] = float(value)
        return state

    @staticmethod
    def _write_state(path: Path, state: Mapping[str, float]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=path.name, dir=path.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(dict(state), stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @asynccontextmanager
    async def request_slot(self) -> AsyncIterator[RequestSlot]:
        interval = self.configured_interval()
        if interval == 0:
            yield RequestSlot(now=self.clock)
            return
        root = self._root()
        identity = self._identity()
        lock = FileLock(str(root / f"{identity}.lock"), mode=0o600)
        state_path = root / f"{identity}.json"

        await asyncio.to_thread(lock.acquire)
        slot = RequestSlot(now=self.clock)
        state: dict[str, float] = {}
        try:
            state = self._read_state(state_path)
            now = self.clock()
            ready_at = max(
                state.get("last_completed", 0.0) + interval,
                state.get("cooldown_until", 0.0),
            )
            if ready_at > now:
                await self.sleep(ready_at - now)
            yield slot
        finally:
            state["last_completed"] = self.clock()
            state["cooldown_until"] = max(
                state.get("cooldown_until", 0.0), slot.cooldown_until
            )
            try:
                await asyncio.to_thread(self._write_state, state_path, state)
            finally:
                await asyncio.to_thread(lock.release)


def utc_timestamp(epoch: float) -> str:
    """Return a stable diagnostic timestamp without exposing local paths."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
