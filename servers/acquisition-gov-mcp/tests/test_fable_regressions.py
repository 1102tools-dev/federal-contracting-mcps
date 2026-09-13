"""Independent-review regressions: complete section text and useful PDF failures."""
import pytest
import acquisition_gov_mcp.server as s
from test_server import text_pdf

@pytest.mark.p1
@pytest.mark.parametrize('markup,expected', [
 ('<div>Direct requirement.</div>', 'Direct requirement.'),
 ('<blockquote>Quoted requirement.</blockquote>', 'Quoted requirement.'),
 ('<pre>Clause text.</pre>', 'Clause text.'),
 ('<dl><dt>Term</dt><dd>Definition.</dd></dl>', 'Definition.'),
 ('<div><span>Inline requirement.</span></div>', 'Inline requirement.'),
 ('Bare requirement.', 'Bare requirement.'),
 ('<section><div>Nested requirement.</div></section>', 'Nested requirement.'),
 ('<ol><li><h3>Subheading</h3>List requirement.</li></ol>', 'List requirement.'),
])
def test_section_retains_all_visible_text_once(markup, expected):
 node=s._main_content(('<main><h1>FAR Overhaul Part 10</h1><h2>10.001 Policy</h2>'+markup+'<h2>10.002 Other</h2><p>EXCLUDED</p></main>').encode())
 result=s._extract_section(node, '10.001')
 assert expected in result
 assert 'EXCLUDED' not in result and '10.002' not in result
 if 'Subheading' in markup: assert result.count('Subheading')==1

@pytest.mark.p1
def test_section_does_not_leak_past_heading_nested_in_container():
 node=s._main_content(b'<main><h2>Scope</h2><div>KEEP<h2>Next</h2>SECRET</div></main>')
 assert s._extract_section(node,'Scope').split()==['Scope','KEEP']

@pytest.mark.p2
def test_section_exact_heading_normalizes_source_whitespace():
 node=s._main_content(b'<main><h2>A   heading</h2><p>Exact</p><h2>A heading details</h2><p>Other</p></main>')
 assert 'Exact' in s._extract_section(node,'A heading')
 assert 'Other' not in s._extract_section(node,'A heading')

@pytest.mark.p2
def test_main_inside_form_is_not_deleted():
 node=s._main_content(b'<form><main><h1>FAR Overhaul Part 10</h1><p>Actual content</p></main></form><aside>Unrelated</aside>')
 assert 'Actual content' in node.get_text() and 'Unrelated' not in node.get_text()

@pytest.mark.p2
async def test_pdf_range_failure_preserves_page_count():
 _,status,warnings,_,total,end=await s._read_pdf_safely(text_pdf('One page.'),page_start=2,page_end=None)
 assert status=='error' and total==1 and end==0
 assert any('page_start' in w and '1' in w for w in warnings)

@pytest.mark.p2
async def test_pdf_heading_normalizes_both_query_and_source(monkeypatch):
 async def fetch(url,**kw): return b'pdf','application/pdf',url
 async def read(*a,**kw): return 'Before\nRequested   heading\nBody','complete',[],{},1,1
 monkeypatch.setattr(s,'_fetch_bytes',fetch);monkeypatch.setattr(s,'_read_pdf_safely',read)
 result=await s.get_rfo_guidance('deviation_guidance',heading='  Requested   heading ')
 assert 'Body' in result['content'] and 'Before' not in result['content']

@pytest.mark.p2
@pytest.mark.parametrize('title',['Download PDF','PDF','Download','View PDF'])
def test_generic_download_title_does_not_hide_agency(title):
 from bs4 import BeautifulSoup
 link=BeautifulSoup(f'<a title="{title}">National Science Foundation (NSF)</a>','html.parser').a
 assert s._agency_name(link)=='National Science Foundation (NSF)'

@pytest.mark.p2
async def test_primary_part_title_takes_precedence_over_incidental_h2(monkeypatch):
 async def fetch(url,**kw): return b'<main><h2>Resources</h2><h1>FAR Overhaul Part 10</h1><p>Content</p></main>','text/html',url
 monkeypatch.setattr(s,'_fetch_bytes',fetch)
 assert (await s.get_rfo_part(10))['far_parts']==[10]

@pytest.mark.p1
def test_real_http_timeout_cancels_underlying_tool(monkeypatch):
 import asyncio,threading
 from starlette.testclient import TestClient
 from acquisition_gov_mcp.http import create_app
 started=threading.Event();stopped=threading.Event()
 async def fetch(*a,**kw):
  started.set()
  try: await asyncio.sleep(60)
  finally: stopped.set()
 monkeypatch.setattr(s,'_fetch_bytes',fetch)
 app=create_app();app.request_timeout=.1
 with TestClient(app) as client:
  response=client.post('/mcp',headers={'Host':'localhost:8080','Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_rfo_part','arguments':{'part':10}}})
  assert response.status_code==504 and started.is_set()
  assert stopped.wait(.2), 'HTTP slot released but underlying MCP tool remains active'
  assert app.active==0

@pytest.mark.p1
async def test_real_http_four_timeouts_cancel_all_work_and_recover(monkeypatch):
 import asyncio,httpx
 from acquisition_gov_mcp.http import create_app
 inflight=0;peak=0;finished=0;started=asyncio.Event();release=asyncio.Event()
 async def fetch(url,**kw):
  nonlocal inflight,peak,finished
  inflight+=1;peak=max(peak,inflight)
  if inflight==4:started.set()
  try: await release.wait();return b'<main><h1>FAR Overhaul Part 10</h1><p>Recovered</p></main>','text/html',url
  finally:inflight-=1;finished+=1
 monkeypatch.setattr(s,'_fetch_bytes',fetch)
 app=create_app();app.request_timeout=.3
 body={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_rfo_part','arguments':{'part':10}}}
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost:8080',headers={'Accept':'application/json, text/event-stream'}) as client:
  tasks=[asyncio.create_task(client.post('/mcp',json=body)) for _ in range(4)]
  await asyncio.wait_for(started.wait(),2)
  overflow=await client.post('/mcp',json=body)
  assert overflow.status_code==429 and overflow.headers['retry-after']=='5'
  assert (await client.get('/health')).status_code==200
  responses=await asyncio.gather(*tasks)
  assert all(r.status_code==504 for r in responses)
  assert inflight==app.active==0 and finished==peak==4
  release.set()
  app.request_timeout=5  # allow the real parser process to start during recovery
  recovered=await client.post('/mcp',json=body)
  assert recovered.status_code==200 and not recovered.json()['result']['isError']
  assert inflight==app.active==0

@pytest.mark.p1
@pytest.mark.parametrize('mode',['disconnect','cancel'])
async def test_real_http_client_departure_cancels_tool(monkeypatch,mode):
 import asyncio,json
 from acquisition_gov_mcp.http import create_app
 entered=asyncio.Event();stopped=asyncio.Event()
 async def fetch(*a,**kw):
  entered.set()
  try:await asyncio.sleep(60)
  finally:stopped.set()
 monkeypatch.setattr(s,'_fetch_bytes',fetch)
 app=create_app();incoming=asyncio.Queue();sent=[]
 body=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_rfo_part','arguments':{'part':10}}}).encode()
 incoming.put_nowait({'type':'http.request','body':body,'more_body':False})
 scope={'type':'http','method':'POST','path':'/mcp','raw_path':b'/mcp','query_string':b'','scheme':'http','http_version':'1.1','root_path':'','server':('localhost',8080),'client':('127.0.0.1',12345),'headers':[(b'host',b'localhost:8080'),(b'content-type',b'application/json'),(b'accept',b'application/json, text/event-stream')]}
 async def send(message):sent.append(message)
 task=asyncio.create_task(app(scope,incoming.get,send))
 await asyncio.wait_for(entered.wait(),2)
 if mode=='disconnect':incoming.put_nowait({'type':'http.disconnect'})
 else:task.cancel()
 await asyncio.gather(task,return_exceptions=True)
 assert stopped.is_set() and app.active==0

@pytest.mark.p2
@pytest.mark.parametrize('method',['GET','DELETE'])
def test_local_http_stateless_methods_match_hosted_policy(method):
 from starlette.testclient import TestClient
 from acquisition_gov_mcp.http import create_app
 with TestClient(create_app()) as client:
  response=client.request(method,'/mcp')
  assert response.status_code==405 and response.headers['allow']=='POST'

@pytest.mark.p2
async def test_truncation_tells_clients_how_to_retrieve_remaining_records(monkeypatch):
 async def index():
  return [{'part':10,'agency_deviations':[{'agency':'Example','source_id':str(n),'far_parts':[10]} for n in range(251)]}],'https://www.acquisition.gov/index','digest','time'
 monkeypatch.setattr(s,'_index',index)
 result=await s.list_rfo_agency_deviations(part=10,limit=250)
 assert result['count']==250 and result['total_matches']==251
 assert any('Narrow the agency filter' in w and 'individual FAR parts' in w for w in result['warnings'])

@pytest.mark.p1
async def test_real_part52_parser_keeps_event_loop_responsive(fixtures,monkeypatch):
 import asyncio,gzip
 body=gzip.decompress((fixtures/'rfo-part-52-2026-09-13.html.gz').read_bytes())
 ticks=[];finished=False
 async def ticker():
  while not finished:
   ticks.append(1);await asyncio.sleep(.005)
 task=asyncio.create_task(ticker())
 try:
  result=await s._read_html_safely(body,'document',part=52,maximum=1000)
  assert result['content'] and result['total_characters']>1000000
  assert len(ticks)>=5, 'large parser monopolized the event loop'
 finally:
  finished=True;await task

@pytest.mark.p0
@pytest.mark.parametrize('mode',['timeout','cancel','oversized_output','invalid_json'])
async def test_real_html_worker_cleanup_and_protocol_limits(monkeypatch,mode):
 import asyncio,sys
 original=asyncio.create_subprocess_exec;children=[];started=asyncio.Event()
 payload={'timeout':'import time; time.sleep(60)','cancel':'import time; time.sleep(60)','oversized_output':'print("x"*200)','invalid_json':'print("not-json")'}[mode]
 async def spawn(*args,**kwargs):
  process=await original(sys.executable,'-c',payload,**kwargs)
  children.append(process);started.set();return process
 monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
 if mode=='timeout':monkeypatch.setattr(s,'MAX_HTML_PARSE_SECONDS',.05)
 if mode=='oversized_output':monkeypatch.setattr(s,'MAX_HTML_WORKER_BYTES',100)
 task=asyncio.create_task(s._read_html_safely(b'<main>test</main>','index',source_url=s.RFO_INDEX_URL))
 await started.wait()
 if mode=='cancel':
  task.cancel()
  with pytest.raises(asyncio.CancelledError):await task
 else:
  with pytest.raises(RuntimeError):await task
 assert children[0].returncode is not None

@pytest.mark.p0
async def test_html_workers_are_serialized(monkeypatch):
 import asyncio,sys
 original=asyncio.create_subprocess_exec;children=[]
 async def spawn(*args,**kwargs):
  process=await original(sys.executable,'-c','import time; time.sleep(.08); print(\'{"result": []}\')',**kwargs)
  assert all(p.returncode is not None for p in children), 'multiple HTML parsers active'
  children.append(process);return process
 monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
 results=await asyncio.gather(*(s._read_html_safely(b'html','index') for _ in range(3)))
 assert results==[[],[],[]] and len(children)==3

@pytest.mark.p2
@pytest.mark.parametrize('href',['https://www.gsa.gov/file.pdf','mailto:far@gsa.gov','http://www.acquisition.gov/file.pdf','//cdn.example.gov/file.pdf','javascript:void(0)'])
async def test_unfetchable_deviation_link_preserves_valid_results_and_warns(fixtures,monkeypatch,href):
 body=(fixtures/'rfo-index.html').read_bytes().replace(b'</details>',f'<a href="{href}">Other Agency</a></details>'.encode())
 async def fetch(url,**kw):return body,'text/html',url
 monkeypatch.setattr(s,'_fetch_bytes',fetch)
 parts=await s.list_rfo_parts(part=10)
 assert parts['count']==1 and parts['results'][0]['agency_deviation_count']==3
 assert any('skipped' in w for w in parts['warnings'])
 deviations=await s.list_rfo_agency_deviations(part=10)
 assert deviations['count']==3 and any('skipped' in w for w in deviations['warnings'])
 assert all(d['source_url'].startswith('https://www.acquisition.gov/') for d in deviations['results'])

@pytest.mark.p2
@pytest.mark.parametrize('text,label,expected',[
 ('Issued on May 1, 2025','Issued','2025-05-01'),
 ('Last updated: Sept 3, 2025','Updated','2025-09-03'),
 ('Updated: 3 September 2025','Updated','2025-09-03'),
 ('Effective Date: October 1, 2025','Date',None),
 ('Issued on February 30, 2025','Issued',None),
])
def test_explicit_labeled_date_variants(text,label,expected):
 assert s._labeled_date(text,label)==expected

@pytest.mark.p1
async def test_long_provider_cooldown_fails_fast_without_shortening_it(monkeypatch,tmp_path):
 import json,time,httpx
 calls=[]
 def handler(request):calls.append(1);return httpx.Response(429,headers={'Retry-After':'31536000'})
 pacer=s.FederalApiPacer(bucket='test-acquisition',default_interval=3,sleep=s._bounded_pacing_sleep,environment={'FEDERAL_API_PACING_DIR':str(tmp_path)})
 client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
 monkeypatch.setattr(s,'_pacer',pacer);monkeypatch.setattr(s,'_client',client);monkeypatch.setattr(s,'_prefer_system_curl',False)
 try:
  with pytest.raises(RuntimeError,match='rate limited'):await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=100)
  with pytest.raises(RuntimeError,match='No upstream request was sent'):await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=100)
  assert len(calls)==1
  state=json.loads(next(tmp_path.glob('*.json')).read_text())
  assert state['cooldown_until']>time.time()+31535000
 finally:await client.aclose()
