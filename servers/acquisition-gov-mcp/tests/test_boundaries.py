"""P0 security/resource boundaries and P1 transport parity, all offline."""
import asyncio
import io
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

import acquisition_gov_mcp.server as s
from test_server import NoWaitPacer, text_pdf

@pytest.mark.p0
@pytest.mark.parametrize('url',[
 'http://www.acquisition.gov/x','https://127.0.0.1/','https://[::1]/',
 'https://169.254.169.254/latest/meta-data','https://www.acquisition.gov.evil.test/',
 'https://user:pass@www.acquisition.gov/','https://www.acquisition.gov:443/',
 'https://www.acquisition.gov:0/','file:///etc/passwd','data:text/html,test',
 'https://www.acquisition.gov%2e.evil.test/','https://www.acquisition.gov\\@evil.test/',
 'https://www.acquisition.gov:bad/','https://evil.test/#https://www.acquisition.gov/',
])
async def test_forbidden_initial_url_never_opens_transport(monkeypatch,url):
    calls=[]
    def client():calls.append(1);raise AssertionError('must not access transport')
    monkeypatch.setattr(s,'_get_client',client)
    with pytest.raises(ValueError):await s._fetch_bytes(url,allowed_types=('text/html',),max_bytes=100)
    assert not calls

@pytest.mark.p1
@pytest.mark.parametrize('use_curl',[False,True])
@pytest.mark.parametrize('status,headers,expect',[
 (200,{'Content-Type':'text/html'},None),
 (404,{'Content-Type':'text/html'},'HTTP 404'),
 (503,{'Content-Type':'text/html'},'HTTP 503'),
 (429,{'Retry-After':'19'},'Retry-After'),
 (302,{},'without Location'),
 (200,{'Content-Type':'text/html-extra'},'Content-Type'),
 (200,{'Content-Type':'text/html','Content-Encoding':'gzip'},'compressed'),
])
async def test_both_transports_enforce_same_response_policy(monkeypatch,use_curl,status,headers,expect):
    calls=[]
    def response():return httpx.Response(status,headers=headers)
    async def curl(url,**kw):calls.append(url);return response(),b''
    def handler(req):calls.append(str(req.url));return response()
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=False)
    monkeypatch.setattr(s,'_pacer',NoWaitPacer());monkeypatch.setattr(s,'_client',client)
    monkeypatch.setattr(s,'_prefer_system_curl',use_curl);monkeypatch.setattr(s,'_curl_once',curl)
    monkeypatch.setattr(s.shutil,'which',lambda n:'/usr/bin/curl')
    try:
        if expect:
            with pytest.raises(RuntimeError,match=expect):await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=100)
        else:assert (await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=100))[1]=='text/html'
        assert len(calls)==1
    finally:await client.aclose()

@pytest.mark.p0
@pytest.mark.parametrize('use_curl',[False,True])
async def test_redirect_allowlist_and_chain_limit_for_both_transports(monkeypatch,use_curl):
    calls=[];locations=['/safe','https://169.254.169.254/']
    def response():return httpx.Response(302,headers={'Location':locations[min(len(calls)-1,len(locations)-1)]})
    async def curl(url,**kw):calls.append(url);return response(),b''
    def handler(req):calls.append(str(req.url));return response()
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=False)
    monkeypatch.setattr(s,'_pacer',NoWaitPacer());monkeypatch.setattr(s,'_client',client)
    monkeypatch.setattr(s,'_prefer_system_curl',use_curl);monkeypatch.setattr(s,'_curl_once',curl)
    monkeypatch.setattr(s.shutil,'which',lambda n:'/usr/bin/curl')
    try:
        with pytest.raises(ValueError,match='allowlist'):await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=100)
        assert len(calls)==2 and all('169.254' not in url for url in calls)
        calls.clear();locations[:]=['/loop']
        with pytest.raises(RuntimeError,match='redirect limit'):await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=100)
        assert len(calls)==s.MAX_REDIRECTS+1
    finally:await client.aclose()

@pytest.mark.p0
@pytest.mark.parametrize('body',[b'<div>'*129+b'x'+b'</div>'*129,b'<br>'*75001,b'<div a="'+b'x'*16385+b'">'],ids=['depth','tag_count','tag_size'])
def test_html_complexity_limits(body):
    with pytest.raises(RuntimeError,match='limit'):s._main_content(body)

@pytest.mark.p0
async def test_chunked_body_aborts_before_unbounded_buffering():
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'12345';yield b'67890';raise AssertionError('reader continued beyond limit')
    response=httpx.Response(200,stream=Stream())
    with pytest.raises(RuntimeError,match='exceeds'):await s._bounded_httpx_body(response,max_bytes=7)
    await response.aclose()

@pytest.mark.p0
async def test_pdf_large_decoded_stream_is_rejected_in_isolated_parser():
    writer=PdfWriter();page=writer.add_blank_page(width=100,height=100)
    stream=DecodedStreamObject();stream.set_data(b'0 0 m\n'*400_000)
    page[NameObject('/Contents')]=writer._add_object(stream.flate_encode())
    output=io.BytesIO();writer.write(output)
    result=await s._read_pdf_safely(output.getvalue(),page_start=1,page_end=1)
    assert result[1] in {'unextractable','error'} and result[2]

class FakeProcess:
    def __init__(self,output=b'',wait=False):
        self.output=output;self.block=wait;self.returncode=None;self.killed=False
        class Stream:
            async def read(self,n):await asyncio.Event().wait()
        self.stdout=Stream();self.stderr=Stream()
    async def communicate(self,*args):
        if self.block:await asyncio.Event().wait()
        self.returncode=0;return self.output,b''
    def kill(self):self.killed=True;self.returncode=-9
    async def wait(self):return self.returncode

@pytest.mark.p0
@pytest.mark.parametrize('oversized_stream',['body','metadata'])
async def test_curl_stream_limits_kill_process_before_reading_more(monkeypatch,oversized_stream):
    proc=FakeProcess()
    class OversizedStream:
        async def read(self,n):
            if getattr(self,'read_once',False):
                raise AssertionError('continued reading after size limit')
            self.read_once=True
            return b'x'*(101 if oversized_stream=='body' else 8193)
    if oversized_stream=='body':proc.stdout=OversizedStream()
    else:proc.stderr=OversizedStream()
    async def spawn(*a,**kw):return proc
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(s.shutil,'which',lambda n:'/usr/bin/curl')
    with pytest.raises(RuntimeError,match='exceeds'):
        await s._curl_once(s.RFO_INDEX_URL,max_bytes=100)
    assert proc.killed

@pytest.mark.p0
@pytest.mark.parametrize('target',['pdf','curl'])
async def test_parser_and_curl_subprocesses_are_killed_on_cancellation(monkeypatch,target):
    proc=FakeProcess(wait=True);started=asyncio.Event()
    async def spawn(*a,**kw):started.set();return proc
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(s.shutil,'which',lambda n:'/usr/bin/curl')
    monkeypatch.setattr(s,'_pdf_slots',asyncio.Semaphore(1))
    coro=s._read_pdf_safely(b'pdf',page_start=1,page_end=1) if target=='pdf' else s._curl_once(s.RFO_INDEX_URL,max_bytes=100)
    task=asyncio.create_task(coro);await started.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert proc.killed

@pytest.mark.p0
async def test_pdf_deadline_returns_explicit_failure_and_kills_worker(monkeypatch):
    proc=FakeProcess(wait=True)
    async def spawn(*a,**kw):return proc
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(s,'MAX_PDF_PARSE_SECONDS',.01)
    monkeypatch.setattr(s,'_pdf_slots',asyncio.Semaphore(1))
    result=await s._read_pdf_safely(b'pdf',page_start=1,page_end=1)
    assert result[1]=='error' and 'time budget' in result[2][0] and proc.killed

@pytest.mark.p0
async def test_pdf_only_one_worker_runs_at_a_time(monkeypatch):
    procs=[];release=asyncio.Event()
    class Proc(FakeProcess):
        async def communicate(self,*a):await release.wait();return await super().communicate(*a)
    async def spawn(*a,**kw):p=Proc(b'["","unextractable",[],{},0,0]');procs.append(p);return p
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(s,'_pdf_slots',asyncio.Semaphore(1))
    tasks=[asyncio.create_task(s._read_pdf_safely(b'pdf',page_start=1,page_end=1)) for _ in range(4)]
    await asyncio.sleep(.01);assert len(procs)==1
    release.set();await asyncio.gather(*tasks);assert len(procs)==4

@pytest.mark.p2
@pytest.mark.parametrize('output',[b'not-json',b'x'*(2*1024*1024+1)],ids=['invalid_json','oversized_output'])
async def test_invalid_worker_results_fail_explicitly(monkeypatch,output):
    async def spawn(*a,**kw):return FakeProcess(output)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(s,'_pdf_slots',asyncio.Semaphore(1))
    assert (await s._read_pdf_safely(b'pdf',page_start=1,page_end=1))[1]=='error'
