"""Deterministic budgets plus real cross-process lock and cancellation checks."""
import asyncio
import json
import multiprocessing
import time
from types import SimpleNamespace

import pytest

from federal_register_mcp._throughput import FederalRegisterPacer

class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    async def sleep(self, seconds): self.now += seconds

def pacer(tmp_path, **kw):
    return FederalRegisterPacer(pacing_dir=tmp_path, environment={}, **kw)

@pytest.mark.asyncio
async def test_501_attempts_rolling_window_across_instances(tmp_path):
    clock=Clock()
    a=pacer(tmp_path, clock=clock, sleep=clock.sleep)
    b=pacer(tmp_path, clock=clock, sleep=clock.sleep)
    starts=[]
    for i in range(501):
        # Faster reservation interval isolates the rolling-window gate itself.
        await (a if i%2 else b)._reserve(0.01)
        starts.append(clock())
    assert starts[500] >= starts[0]+300
    assert all(sum(t-300 < s <= t for s in starts) <= 500 for t in starts)

@pytest.mark.asyncio
async def test_start_spacing_not_completion_spacing_and_errors_count(tmp_path):
    clock=Clock(); p=pacer(tmp_path,clock=clock,sleep=clock.sleep)
    with pytest.raises(ValueError):
        async with p.request_slot():
            first=clock(); clock.now+=0.4
            raise ValueError('network failed')
    async with p.request_slot():
        assert clock() == pytest.approx(first+0.6)
    state=json.loads(next(tmp_path.glob('*.json')).read_text())
    assert len(state['starts'])==2

@pytest.mark.asyncio
async def test_retry_after_shared_and_cancelled_attempt_consumed(tmp_path):
    clock=Clock(); a=pacer(tmp_path,clock=clock,sleep=clock.sleep)
    with pytest.raises(asyncio.CancelledError):
        async with a.request_slot() as slot:
            slot.observe_response(SimpleNamespace(status_code=429,headers={'Retry-After':'12'}))
            raise asyncio.CancelledError()
    async with pacer(tmp_path,clock=clock,sleep=clock.sleep).request_slot():
        assert clock()==1012
    assert len(json.loads(next(tmp_path.glob('*.json')).read_text())['starts'])==2

@pytest.mark.asyncio
async def test_cancellation_waiting_does_not_leak_slot(tmp_path):
    p=pacer(tmp_path)
    contexts=[p._concurrency_slot() for _ in range(2)]
    for ctx in contexts: await ctx.__aenter__()
    waiting=asyncio.create_task(p._concurrency_slot().__aenter__())
    await asyncio.sleep(0.04); assert not waiting.done()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError): await waiting
    for ctx in contexts: await ctx.__aexit__(None,None,None)
    async with asyncio.timeout(1):
        async with p._concurrency_slot(): pass

@pytest.mark.asyncio
async def test_real_overlap_bounded_to_two_across_instances(tmp_path):
    active=peak=0; starts=[]
    async def call():
        nonlocal active,peak
        async with pacer(tmp_path).request_slot():
            active+=1; peak=max(peak,active); starts.append(time.time())
            await asyncio.sleep(2.0)
            active-=1
    await asyncio.gather(*(call() for _ in range(6)))
    assert 2 <= peak <= 2
    assert all(b-a >= .59 for a,b in zip(starts,starts[1:]))

@pytest.mark.asyncio
async def test_positive_override_cannot_accelerate_default(tmp_path):
    clock=Clock()
    p=FederalRegisterPacer(pacing_dir=tmp_path,environment={'FEDERAL_API_MIN_INTERVAL_SECONDS':'.1'},clock=clock,sleep=clock.sleep)
    async with p.request_slot(): first=clock()
    async with p.request_slot(): assert clock()-first==pytest.approx(.6)

@pytest.mark.asyncio
async def test_legacy_state_and_corruption_fail_closed(tmp_path):
    clock=Clock(); p=pacer(tmp_path,clock=clock,sleep=clock.sleep)
    path=tmp_path/f'{p._identity()}.json'
    path.write_text(json.dumps({'last_completed':1000,'cooldown_until':1005}))
    async with p.request_slot(): assert clock()==1005
    path.write_text('broken')
    with pytest.raises(RuntimeError,match='unreadable'):
        async with p.request_slot(): pass


def child_slot(directory, queue, release):
    async def run():
        from pathlib import Path
        async with pacer(Path(directory))._concurrency_slot():
            queue.put('acquired')
            while not release.is_set(): await asyncio.sleep(.01)
    asyncio.run(run())

@pytest.mark.asyncio
async def test_cross_process_slots_and_crash_recovery(tmp_path):
    ctx=multiprocessing.get_context('spawn'); q=ctx.Queue(); release=ctx.Event()
    processes=[ctx.Process(target=child_slot,args=(str(tmp_path),q,release)) for _ in range(2)]
    try:
        for p in processes: p.start()
        for _ in processes: assert await asyncio.to_thread(q.get,True,15)=='acquired'
        waiter=asyncio.create_task(pacer(tmp_path)._concurrency_slot().__aenter__())
        await asyncio.sleep(.1); assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError): await waiter
        processes[0].terminate(); await asyncio.to_thread(processes[0].join,5)
        async with asyncio.timeout(2):
            async with pacer(tmp_path)._concurrency_slot(): pass
    finally:
        release.set()
        for p in processes:
            await asyncio.to_thread(p.join,5)
            if p.is_alive(): p.kill(); p.join()
        q.close()


def child_budget(directory, queue):
    async def run():
        from pathlib import Path
        p=pacer(Path(directory))
        for _ in range(2):
            async with p.request_slot(): queue.put(time.time())
    asyncio.run(run())

@pytest.mark.asyncio
async def test_cross_process_start_spacing(tmp_path):
    ctx=multiprocessing.get_context('spawn'); q=ctx.Queue()
    children=[ctx.Process(target=child_budget,args=(str(tmp_path),q)) for _ in range(3)]
    try:
        for child in children: child.start()
        starts=sorted([await asyncio.to_thread(q.get,True,15) for _ in range(6)])
        assert all(b-a >= .58 for a,b in zip(starts,starts[1:]))
        state=json.loads(next(tmp_path.glob('*.json')).read_text())
        assert len(state['starts'])==6
    finally:
        for child in children:
            await asyncio.to_thread(child.join,5)
            if child.is_alive(): child.kill(); child.join()
        q.close()
