"""Deterministic budgets plus real cross-process lock and cancellation checks."""
import asyncio
import json
import multiprocessing
import time
from types import SimpleNamespace

import pytest

from gsa_calc_mcp._throughput import GsaCalcPacer

class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    async def sleep(self, seconds): self.now += seconds

def pacer(tmp_path, **kw):
    return GsaCalcPacer(pacing_dir=tmp_path, environment={}, **kw)

@pytest.mark.asyncio
async def test_hourly_budget_fails_promptly_and_recovers_across_instances(tmp_path):
    clock=Clock()
    a=pacer(tmp_path,clock=clock,sleep=clock.sleep)
    b=pacer(tmp_path,clock=clock,sleep=clock.sleep)
    for i in range(500):
        await (a if i%2 else b)._reserve(.01)
    before=clock()
    with pytest.raises(RuntimeError,match='500 upstream attempts per hour'):
        await a._reserve(.01)
    assert clock()==before
    clock.now=4600
    await b._reserve(.01)
    state=json.loads(next(tmp_path.glob('*.json')).read_text())
    assert len(state['starts'])==500

@pytest.mark.asyncio
async def test_long_provider_cooldown_fails_promptly_without_new_attempt(tmp_path):
    clock=Clock();p=pacer(tmp_path,clock=clock,sleep=clock.sleep)
    async with p.request_slot() as slot:
        slot.observe_response(SimpleNamespace(status_code=429,headers={'Retry-After':'2221'}))
    before=clock()
    with pytest.raises(RuntimeError,match='provider cooldown is active'):
        async with p.request_slot():pass
    assert clock()==before
    assert len(json.loads(next(tmp_path.glob('*.json')).read_text())['starts'])==1

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
    p=GsaCalcPacer(pacing_dir=tmp_path,environment={'FEDERAL_API_MIN_INTERVAL_SECONDS':'.1'},clock=clock,sleep=clock.sleep)
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

@pytest.mark.asyncio
async def test_exhausted_budget_is_visible_in_mcp_response(tmp_path,monkeypatch):
    import httpx
    from gsa_calc_mcp import server
    from gsa_calc_mcp.http import create_app
    p=pacer(tmp_path);now=time.time()
    path=tmp_path/f'{p._identity()}.json'
    path.write_text(json.dumps({'starts':[now-.6*i for i in range(500)],'last_started':now}))
    monkeypatch.setattr(server,'_pacer',p)
    app=create_app()
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost:8080',headers={'Accept':'application/json, text/event-stream'}) as client:
            response=await asyncio.wait_for(client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'keyword_search','arguments':{'keyword':'engineer','page_size':1}}}),2)
            result=response.json()['result']
            assert result['isError']
            assert '500 upstream attempts per hour' in result['content'][0]['text']
            assert 'Retry after' in result['content'][0]['text']

@pytest.mark.asyncio
async def test_provider_429_guidance_survives_mcp_and_prevents_retry(tmp_path,monkeypatch):
    import httpx
    from gsa_calc_mcp import server
    from gsa_calc_mcp.http import create_app
    calls=0
    def upstream(request):
        nonlocal calls
        calls+=1
        return httpx.Response(429,json={'detail':'throttled'},headers={'Retry-After':'2221'})
    monkeypatch.setattr(server,'_pacer',pacer(tmp_path))
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        monkeypatch.setattr(server,'_client',upstream_client)
        app=create_app()
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost:8080',headers={'Accept':'application/json, text/event-stream'}) as client:
                for expected in ('Retry-After','provider cooldown'):
                    response=await asyncio.wait_for(client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'keyword_search','arguments':{'keyword':'engineer','page_size':1}}}),2)
                    assert int(response.headers['x-1102tools-provider-retry-after']) >= 2200
                    result=response.json()['result']
                    assert result['isError'] and expected in result['content'][0]['text']
    assert calls==1
