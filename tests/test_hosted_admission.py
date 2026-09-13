"""Offline ASGI burst, FIFO, disconnect, deadline and memory-bound checks."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATHS = [ROOT / 'shared/hosted_admission.py'] + sorted(ROOT.glob('servers/*/src/*/_admission.py'))

@pytest.fixture(params=PATHS, ids=lambda p: p.parent.name)
def admission(request):
    spec = importlib.util.spec_from_file_location('admission_under_test', request.param)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AdmissionQueue

class Request:
    def __init__(self, guard, number=0, body=b'{}'):
        self.messages = []
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({'type':'http.request','body':body,'more_body':False})
        self.task = asyncio.create_task(guard(
            {'type':'http','path':'/mcp','method':'POST','number':number},
            self.incoming.get, self.send))
    async def send(self, message):
        self.messages.append(message)
    def disconnect(self):
        self.incoming.put_nowait({'type':'http.disconnect'})
    @property
    def status(self):
        return next((m['status'] for m in self.messages if m['type']=='http.response.start'), None)

async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)

async def reply(send):
    await send({'type':'http.response.start','status':200,'headers':[]})
    await send({'type':'http.response.body','body':b'ok'})

@pytest.mark.asyncio
async def test_48_accepted_49th_rejected_fifo_and_reuse(admission):
    entered = []
    gates = [asyncio.Event() for _ in range(49)]
    async def backend(scope, receive, send):
        n = scope['number']; entered.append(n)
        assert (await receive())['body'] == b'{}'
        await gates[n].wait()
        await reply(send)
    guard = admission(backend)
    requests = [Request(guard,n) for n in range(48)]
    await until(lambda: len(entered)==16 and guard.waiting==32)
    overflow = Request(guard,48)
    await overflow.task
    assert overflow.status==429 and guard.active==16 and guard.waiting==32
    assert dict(overflow.messages[0]['headers'])[b'retry-after']==b'5'
    for n in range(32):
        gates[n].set()
        await until(lambda: len(entered)==17+n)
        assert entered[-1]==16+n
    for gate in gates: gate.set()
    await asyncio.gather(*(r.task for r in requests))
    assert all(r.status==200 for r in requests)
    assert guard.active==guard.waiting==0
    again = Request(guard,48); await again.task
    assert again.status==200 and guard.active==0

@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['queued','active','just_promoted'])
@pytest.mark.parametrize('disconnect',[False,True])
async def test_cancel_and_disconnect_release_exactly_once(admission, phase, disconnect):
    entered=[]
    async def backend(scope,receive,send):
        entered.append(scope['number'])
        await asyncio.Event().wait()
    guard=admission(backend); guard.processing_limit=1
    first=Request(guard,0); second=Request(guard,1); third=Request(guard,2)
    await until(lambda: guard.waiting==2 and entered==[0])
    victim=second if phase!='active' else first
    if phase=='just_promoted':
        # Cancel the owner and queued successor together: exercise promotion races.
        first.task.cancel()
    if disconnect: victim.disconnect()
    else: victim.task.cancel()
    await asyncio.gather(victim.task, return_exceptions=True)
    if phase=='queued':
        assert guard.waiting==1 and guard.active==1
        first.task.cancel()
    await until(lambda: 2 in entered or (phase=='active' and 1 in entered))
    for r in (first,second,third): r.task.cancel()
    await asyncio.gather(first.task,second.task,third.task,return_exceptions=True)
    assert guard.active==guard.waiting==0

@pytest.mark.asyncio
async def test_total_deadline_includes_waiting_and_cancels_backend(admission):
    cancelled=[]
    async def backend(scope,receive,send):
        try: await asyncio.Event().wait()
        finally: cancelled.append(scope['number'])
    guard=admission(backend);guard.processing_limit=1;guard.request_timeout=.08
    first=Request(guard,0);second=Request(guard,1)
    await asyncio.gather(first.task,second.task)
    assert first.status==second.status==504
    assert guard.active==guard.waiting==0 and 0 in cancelled

@pytest.mark.asyncio
async def test_oversize_chunked_body_and_upload_disconnect(admission):
    calls=[]
    async def backend(scope,receive,send): calls.append(1)
    guard=admission(backend)
    oversized=Request(guard,body=b'x'*65537);await oversized.task
    assert oversized.status==413 and not calls and guard.active==0
    incoming=asyncio.Queue();messages=[]
    incoming.put_nowait({'type':'http.request','body':b'x'*32768,'more_body':True})
    incoming.put_nowait({'type':'http.request','body':b'x'*32769,'more_body':False})
    async def send(m): messages.append(m)
    await guard({'type':'http','path':'/mcp'},incoming.get,send)
    assert messages[0]['status']==413 and guard.active==0
    incoming.put_nowait({'type':'http.disconnect'})
    await guard({'type':'http','path':'/mcp'},incoming.get,send)
    assert guard.active==0

@pytest.mark.asyncio
async def test_application_failure_releases_slot(admission):
    async def backend(scope,receive,send): raise ValueError('simulated failure')
    guard=admission(backend);req=Request(guard)
    with pytest.raises(ValueError): await req.task
    assert guard.active==guard.waiting==0

@pytest.mark.asyncio
async def test_deadline_after_response_start_does_not_send_second_response(admission):
    async def backend(scope,receive,send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await asyncio.Event().wait()
    guard=admission(backend);guard.request_timeout=.02;req=Request(guard)
    with pytest.raises(TimeoutError):await req.task
    assert len(req.messages)==1 and guard.active==0

@pytest.mark.asyncio
async def test_lifespan_passes_through(admission):
    calls=[]
    async def backend(scope,receive,send):calls.append(scope['type'])
    guard=admission(backend)
    await guard({'type':'lifespan'},None,None)
    assert calls==['lifespan'] and guard.active==0


def test_all_four_packages_use_canonical_queue():
    assert len(PATHS)==5
    for path in PATHS[1:]:
        assert path.read_bytes()==PATHS[0].read_bytes()
