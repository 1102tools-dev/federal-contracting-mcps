# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Bounded, hosted-only cache of government API answers, with miss coalescing.

The canonical copy is shared/response_cache.py; scripts/sync_response_cache.py
vendors it into each live-API server as ``_response_cache.py``.

It is off unless MCP_RESPONSE_CACHE=1, which only the hosted Dockerfiles set,
so the PyPI packages behave exactly as before. An entry holds the raw bytes of
one good government answer. The caller's ``parse`` turns bytes into its result
on a miss and on every hit, so a cached answer is the one an uncached call made
when the entry was filled, and nothing shares a mutable object. ``parse`` also
validates: if it raises, nothing is stored.

Callers check the cache before entering their pacer, so a hit uses no spacing,
no in-flight slot and no budget. Identical misses that overlap share the one
government call already running; different questions still queue in the pacer
as before. Errors, refusals, timeouts and cancellations are never stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

ENABLE_ENV = "MCP_RESPONSE_CACHE"

MINUTE = 60.0
HOUR = 3600.0
DAY = 86400.0

T = TypeVar("T")


def enabled_from_env(environment: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environment is None else environment
    return env.get(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def cache_key(method: str, url: str, params: Any = None, body: Any = None) -> str:
    """A fixed-size key for one upstream request.

    Query parameters are sorted by name; repeated names keep their order. The
    body is canonical JSON. Callers never pass credentials: API keys travel in
    headers, which are not part of the key.
    """
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if params:
        items = params.items() if isinstance(params, Mapping) else params
        pairs += [(str(k), str(v)) for k, v in items]
    pairs.sort(key=lambda kv: kv[0])
    canonical = json.dumps(
        [method.upper(), parsed.scheme, parsed.netloc, parsed.path, pairs, body],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(
        self,
        *,
        max_bytes: int,
        max_entry_bytes: int,
        max_entries: int = 4096,
        enabled: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled_from_env() if enabled is None else enabled
        self.max_bytes = max_bytes
        self.max_entry_bytes = max_entry_bytes
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[bytes | None]] = {}
        self.bytes = 0
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict[str, int]:
        """Counts since start: answers without a government call, calls made."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self._entries),
            "bytes": self.bytes,
        }

    def _drop(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self.bytes -= len(entry[1])

    def _lookup(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry[0] <= self.clock():
            self._drop(key)
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def _store(self, key: str, ttl: float, content: bytes) -> None:
        size = len(content)
        if size > self.max_entry_bytes or size > self.max_bytes or self.max_entries < 1:
            return
        self._drop(key)
        now = self.clock()
        for expired in [k for k, (expires, _) in self._entries.items() if expires <= now]:
            self._drop(expired)
        # Least recently used first.
        while self._entries and (
            len(self._entries) >= self.max_entries or self.bytes + size > self.max_bytes
        ):
            self._drop(next(iter(self._entries)))
        self._entries[key] = (now + ttl, content)
        self.bytes += size

    async def get_or_fetch(
        self,
        key: str,
        ttl: float,
        fetch: Callable[[], Awaitable[bytes]],
        parse: Callable[[bytes], T],
    ) -> T:
        """Return ``parse(content)`` for a cached or freshly fetched answer.

        ``fetch`` makes the paced government call and raises on any error;
        it runs only on a miss.
        """
        if not self.enabled or ttl <= 0:
            return parse(await fetch())
        while True:
            content = self._lookup(key)
            if content is not None:
                self.hits += 1
                return parse(content)
            pending = self._inflight.get(key)
            if pending is None:
                break
            # The same question is already on its way to the government.
            # shield: a waiter's cancellation must not cancel the shared call.
            content = await asyncio.shield(pending)
            if content is not None:
                self.hits += 1
                return parse(content)
            # That call failed and stored nothing: ask again ourselves.

        future: asyncio.Future[bytes | None] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        shared: bytes | None = None
        try:
            self.misses += 1
            content = await fetch()
            result = parse(content)
            self._store(key, ttl, content)
            shared = content
            return result
        finally:
            del self._inflight[key]
            future.set_result(shared)
