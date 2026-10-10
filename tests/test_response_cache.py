"""Offline checks for the hosted response cache and its five vendored copies."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared/response_cache.py"
COPIES = sorted(ROOT.glob("servers/*/src/*/_response_cache.py"))


def test_five_identical_copies():
    assert len(COPIES) == 5
    for path in COPIES:
        assert path.read_bytes() == SOURCE.read_bytes(), path


@pytest.fixture(params=[SOURCE] + COPIES, ids=lambda p: p.parent.name)
def rc(request):
    spec = importlib.util.spec_from_file_location("response_cache_under_test", request.param)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Upstream:
    """Counts government calls; returns bytes or raises."""

    def __init__(self, answers=None):
        self.calls = 0
        self.answers = answers or {}

    def fetcher(self, key, delay=0.0):
        async def fetch():
            self.calls += 1
            if delay:
                await asyncio.sleep(delay)
            answer = self.answers.get(key, b'{"q": "%s"}' % key.encode())
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return fetch


def parse(content):
    return content.decode()


def make(rc, **kw):
    kw.setdefault("max_bytes", 1000)
    kw.setdefault("max_entry_bytes", 400)
    kw.setdefault("enabled", True)
    return rc.ResponseCache(**kw)


def run(coro):
    return asyncio.run(coro)


def test_off_by_default(rc, monkeypatch):
    monkeypatch.delenv(rc.ENABLE_ENV, raising=False)
    cache = rc.ResponseCache(max_bytes=1000, max_entry_bytes=400)
    up = Upstream()

    async def go():
        for _ in range(3):
            assert await cache.get_or_fetch("k", rc.HOUR, up.fetcher("a"), parse) == '{"q": "a"}'
    run(go())
    assert cache.enabled is False
    assert up.calls == 3
    assert cache.stats() == {"hits": 0, "misses": 0, "entries": 0, "bytes": 0}
    assert rc.enabled_from_env({rc.ENABLE_ENV: "1"}) is True
    assert rc.enabled_from_env({rc.ENABLE_ENV: "0"}) is False
    assert rc.enabled_from_env({}) is False


def test_hit_miss_and_expiry(rc):
    clock = Clock()
    cache = make(rc, clock=clock)
    up = Upstream()

    async def go():
        first = await cache.get_or_fetch("k", 60, up.fetcher("a"), parse)
        second = await cache.get_or_fetch("k", 60, up.fetcher("a"), parse)
        assert first == second == '{"q": "a"}'
        assert up.calls == 1
        clock.now += 59.9
        await cache.get_or_fetch("k", 60, up.fetcher("a"), parse)
        assert up.calls == 1
        clock.now += 0.2
        await cache.get_or_fetch("k", 60, up.fetcher("a"), parse)
        assert up.calls == 2
    run(go())
    assert cache.stats() == {"hits": 2, "misses": 2, "entries": 1, "bytes": len(b'{"q": "a"}')}


def test_each_hit_parses_fresh_objects(rc):
    cache = make(rc)
    up = Upstream()

    async def go():
        import json
        a = await cache.get_or_fetch("k", 60, up.fetcher("a"), json.loads)
        a["q"] = "changed by a tool"
        b = await cache.get_or_fetch("k", 60, up.fetcher("a"), json.loads)
        assert b == {"q": "a"}
    run(go())


def test_byte_limit_evicts_least_recently_used(rc):
    cache = make(rc, max_bytes=30, max_entry_bytes=30)
    up = Upstream({k: k.encode() * 10 for k in "abcd"})  # 10 bytes each

    async def go():
        for k in "abc":
            await cache.get_or_fetch(k, 60, up.fetcher(k), parse)
        await cache.get_or_fetch("a", 60, up.fetcher("a"), parse)  # a is now newest
        await cache.get_or_fetch("d", 60, up.fetcher("d"), parse)  # evicts b
        assert up.calls == 4
        await cache.get_or_fetch("a", 60, up.fetcher("a"), parse)
        await cache.get_or_fetch("c", 60, up.fetcher("c"), parse)
        assert up.calls == 4
        await cache.get_or_fetch("b", 60, up.fetcher("b"), parse)
        assert up.calls == 5
    run(go())
    assert cache.bytes <= 30


def test_entry_count_limit(rc):
    cache = make(rc, max_entries=2)
    up = Upstream()

    async def go():
        for k in "abc":
            await cache.get_or_fetch(k, 60, up.fetcher(k), parse)
    run(go())
    assert cache.stats()["entries"] == 2


def test_oversized_entry_is_served_not_stored(rc):
    cache = make(rc, max_entry_bytes=5)
    up = Upstream({"big": b"x" * 6})

    async def go():
        assert await cache.get_or_fetch("big", 60, up.fetcher("big"), parse) == "xxxxxx"
        await cache.get_or_fetch("big", 60, up.fetcher("big"), parse)
    run(go())
    assert up.calls == 2
    assert cache.stats()["entries"] == 0


def test_errors_refusals_and_bad_bodies_are_never_stored(rc):
    cache = make(rc)
    up = Upstream({"err": RuntimeError("HTTP 500"), "cancel": asyncio.CancelledError()})

    def strict(content):
        if content.startswith(b"<html"):
            raise RuntimeError("non-JSON 200")
        return content

    async def go():
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cache.get_or_fetch("err", 60, up.fetcher("err"), parse)
        assert up.calls == 2
        for _ in range(2):
            with pytest.raises(asyncio.CancelledError):
                await cache.get_or_fetch("cancel", 60, up.fetcher("cancel"), parse)
        assert up.calls == 4
        up.answers["html"] = b"<html>maintenance</html>"
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cache.get_or_fetch("html", 60, up.fetcher("html"), strict)
        assert up.calls == 6
    run(go())
    assert cache.stats()["entries"] == 0


def test_concurrent_identical_misses_make_one_call(rc):
    cache = make(rc)
    up = Upstream()

    async def go():
        results = await asyncio.gather(*[
            cache.get_or_fetch("k", 60, up.fetcher("a", delay=0.05), parse) for _ in range(10)
        ])
        assert set(results) == {'{"q": "a"}'}
    run(go())
    assert up.calls == 1
    assert cache.stats()["hits"] == 9 and cache.stats()["misses"] == 1


def test_different_questions_are_not_serialized(rc):
    cache = make(rc)
    running = 0
    peak = 0

    def fetcher(k):
        async def fetch():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1
            return k.encode()
        return fetch

    async def go():
        await asyncio.gather(*[cache.get_or_fetch(k, 60, fetcher(k), parse) for k in "abcd"])
    run(go())
    assert peak == 4


def test_waiters_retry_when_the_shared_call_fails(rc):
    cache = make(rc)
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        if calls == 1:
            raise RuntimeError("timeout")
        return b"ok"

    async def go():
        results = await asyncio.gather(
            *[cache.get_or_fetch("k", 60, flaky, parse) for _ in range(3)], return_exceptions=True
        )
        assert isinstance(results[0], RuntimeError)
        assert results[1:] == ["ok", "ok"]
    run(go())
    assert calls == 2


def test_a_cancelled_waiter_does_not_cancel_the_shared_call(rc):
    cache = make(rc)
    up = Upstream()

    async def go():
        leader = asyncio.create_task(cache.get_or_fetch("k", 60, up.fetcher("a", delay=0.05), parse))
        await asyncio.sleep(0.01)
        waiter = asyncio.create_task(cache.get_or_fetch("k", 60, up.fetcher("a"), parse))
        await asyncio.sleep(0.01)
        waiter.cancel()
        assert await leader == '{"q": "a"}'
        with pytest.raises(asyncio.CancelledError):
            await waiter
    run(go())
    assert up.calls == 1
    assert cache.stats()["entries"] == 1


def test_cache_key(rc):
    key = rc.cache_key
    assert key("GET", "https://x.gov/a?b=2&a=1") == key("GET", "https://x.gov/a?a=1&b=2")
    assert key("GET", "https://x.gov/a", {"a": 1, "b": 2}) == key("GET", "https://x.gov/a?b=2&a=1")
    # Repeated names keep their order; different values are different questions.
    assert key("GET", "https://x.gov/a?t=1&t=2") != key("GET", "https://x.gov/a?t=2&t=1")
    assert key("GET", "https://x.gov/a?a=1") != key("GET", "https://x.gov/a?a=2")
    assert key("GET", "https://x.gov/a") != key("POST", "https://x.gov/a")
    assert key("POST", "/p", body={"a": 1, "b": [1, 2]}) == key("POST", "/p", body={"b": [1, 2], "a": 1})
    assert key("POST", "/p", body={"b": [1, 2]}) != key("POST", "/p", body={"b": [2, 1]})
    assert len(key("POST", "/p", body={"x": "y" * 60000})) == 64


def test_the_five_hosted_images_turn_the_cache_on():
    for slug in ("ecfr", "federal-register", "gsa-calc", "regulations-gov", "usaspending"):
        dockerfile = (ROOT / "deploy" / slug / "Dockerfile").read_text()
        assert "MCP_RESPONSE_CACHE=1" in dockerfile, slug
        assert "MCP_RESPONSE_CACHE_SECONDS" not in dockerfile, slug


def test_the_hosting_machine_can_give_the_cache_more_room(rc):
    Cache = rc.ResponseCache
    env = {"MCP_RESPONSE_CACHE": "1", "MCP_RESPONSE_CACHE_MB": "256", "MCP_RESPONSE_CACHE_ENTRIES": "32768"}
    big = Cache(max_bytes=48 * 1024 * 1024, max_entry_bytes=1024, environment=env)
    assert big.enabled and big.max_bytes == 256 * 1024 * 1024 and big.max_entries == 32768
    plain = Cache(max_bytes=48 * 1024 * 1024, max_entry_bytes=1024, environment={"MCP_RESPONSE_CACHE": "1"})
    assert plain.max_bytes == 48 * 1024 * 1024 and plain.max_entries == 4096
    bad = Cache(max_bytes=48 * 1024 * 1024, max_entry_bytes=1024,
                environment={"MCP_RESPONSE_CACHE": "1", "MCP_RESPONSE_CACHE_MB": "lots", "MCP_RESPONSE_CACHE_ENTRIES": "-5"})
    assert bad.max_bytes == 48 * 1024 * 1024 and bad.max_entries == 4096
    # An explicit enabled= (tests, callers that size the cache themselves) ignores the overrides.
    fixed = Cache(max_bytes=1024, max_entry_bytes=512, enabled=True, environment=env)
    assert fixed.max_bytes == 1024 and fixed.max_entries == 4096

