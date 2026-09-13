import asyncio
import pytest
from ecfr_mcp._xml_cache import XmlCache
from ecfr_mcp._throughput import EcfrXmlPacer

@pytest.mark.asyncio
async def test_coalesces_duplicate_misses_and_expires():
    now=[0];cache=XmlCache(ttl=10,clock=lambda:now[0]);calls=0
    async def load():
        nonlocal calls
        calls+=1;await asyncio.sleep(.01);return '<ROOT>section</ROOT>'
    assert await asyncio.gather(*(cache.get_or_fetch('date/section',load) for _ in range(8)))==['<ROOT>section</ROOT>']*8
    assert calls==1
    now[0]=10
    await cache.get_or_fetch('date/section',load)
    assert calls==2

@pytest.mark.asyncio
async def test_errors_and_invalid_xml_are_not_cached():
    cache=XmlCache();calls=0
    async def fail():raise RuntimeError('upstream error')
    with pytest.raises(RuntimeError):await cache.get_or_fetch('a',fail)
    async def invalid():
        nonlocal calls
        calls+=1;return '<broken'
    await cache.get_or_fetch('a',invalid);await cache.get_or_fetch('a',invalid)
    assert calls==2 and not cache.entries

@pytest.mark.asyncio
async def test_entry_and_byte_bounds_and_lru():
    cache=XmlCache(max_entries=2,max_bytes=24,max_entry_bytes=20)
    async def small():return '<A>1</A>'
    for key in ('a','b'):await cache.get_or_fetch(key,small)
    await cache.get_or_fetch('a',small)
    await cache.get_or_fetch('c',small)
    assert list(cache.entries)==['a','c'] and cache.bytes==16
    async def large():return '<A>'+('x'*30)+'</A>'
    await cache.get_or_fetch('large',large)
    assert 'large' not in cache.entries and cache.bytes<=24

@pytest.mark.asyncio
async def test_cancelled_miss_does_not_poison_cache_or_lock():
    cache=XmlCache();started=asyncio.Event()
    async def slow():started.set();await asyncio.sleep(100)
    task=asyncio.create_task(cache.get_or_fetch('a',slow));await started.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    async def good():return '<A/>'
    assert await asyncio.wait_for(cache.get_or_fetch('a',good),1)=='<A/>'

@pytest.mark.parametrize('value,expected',[('.6',3),('6',6),('0',0)])
def test_xml_floor_independent_from_fast_json(value,expected):
    assert EcfrXmlPacer(environment={'FEDERAL_API_MIN_INTERVAL_SECONDS':value}).configured_interval()==expected

@pytest.mark.asyncio
async def test_server_cache_keys_include_date_and_filters(monkeypatch):
    from ecfr_mcp import server
    calls=[]
    async def fetch(path,params):calls.append((path,params));return '<ROOT>valid</ROOT>'
    monkeypatch.setattr(server,'_get_xml_uncached',fetch)
    await server._get_xml('/date1/title.xml',{'section':'1','part':'1'})
    await server._get_xml('/date1/title.xml',{'part':'1','section':'1'})
    await server._get_xml('/date2/title.xml',{'section':'1','part':'1'})
    await server._get_xml('/date1/title.xml',{'section':'2','part':'1'})
    assert len(calls)==3

@pytest.mark.asyncio
async def test_waiting_xml_lane_does_not_block_json(monkeypatch):
    from contextlib import asynccontextmanager
    from ecfr_mcp import server
    import httpx
    started=asyncio.Event();release=asyncio.Event()
    class BlockedXml:
        @asynccontextmanager
        async def request_slot(self):
            started.set();await release.wait()
            from ecfr_mcp._pacing import RequestSlot
            import time
            yield RequestSlot(now=time.time)
    monkeypatch.setattr(server,'_xml_pacer',BlockedXml())
    async with httpx.AsyncClient(base_url=server.BASE_URL,transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'ok':True}) if request.url.path.endswith('.json') else httpx.Response(200,text='<ROOT/>'))) as client:
        monkeypatch.setattr(server,'_client',client)
        pending=asyncio.create_task(server._get_xml('/date/title.xml'))
        await started.wait()
        assert await asyncio.wait_for(server._get_json('/titles.json'),1)=={'ok':True}
        assert not pending.done()
        release.set();assert await pending=='<ROOT/>'
