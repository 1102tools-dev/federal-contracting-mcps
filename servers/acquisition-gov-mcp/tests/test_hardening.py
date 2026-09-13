"""Risk-ranked regression tests for the September 2026 hardening audit."""
import asyncio
import io
from contextlib import asynccontextmanager

import httpx
import pytest
from pypdf import PdfWriter

import acquisition_gov_mcp.server as s
from test_server import NoWaitPacer, text_pdf

@pytest.mark.p1
async def test_cached_curl_success_is_returned_once(monkeypatch):
    calls=[]
    async def curl(url,**kw):
        calls.append(url)
        return httpx.Response(200,headers={'Content-Type':'text/html'}),b'<main>ok</main>'
    monkeypatch.setattr(s,'_pacer',NoWaitPacer())
    monkeypatch.setattr(s,'_prefer_system_curl',True)
    monkeypatch.setattr(s.shutil,'which',lambda n:'/usr/bin/curl')
    monkeypatch.setattr(s,'_curl_once',curl)
    for _ in range(2):
        body,kind,url=await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=1000)
        assert body==b'<main>ok</main>' and kind=='text/html'
    assert len(calls)==2

@pytest.mark.p1
async def test_cached_curl_429_observes_retry_after(monkeypatch):
    calls=[]
    async def curl(url,**kw):
        calls.append(url)
        return httpx.Response(429,headers={'Retry-After':'17'}),b''
    monkeypatch.setattr(s,'_pacer',NoWaitPacer())
    monkeypatch.setattr(s,'_prefer_system_curl',True)
    monkeypatch.setattr(s.shutil,'which',lambda n:'/usr/bin/curl')
    monkeypatch.setattr(s,'_curl_once',curl)
    with pytest.raises(RuntimeError,match="Retry-After='17'"):
        await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=1000)
    assert len(calls)==1

@pytest.mark.p1
async def test_missing_index_structure_does_not_look_like_zero_results(monkeypatch):
    async def fetch(*a,**kw):return b'<main>Access denied</main>','text/html',s.RFO_INDEX_URL
    monkeypatch.setattr(s,'_fetch_bytes',fetch)
    with pytest.raises(RuntimeError,match='index|structure'):
        await s.list_rfo_parts()

@pytest.mark.p1
def test_encrypted_pdf_returns_metadata_instead_of_crashing():
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.encrypt('secret')
    stream=io.BytesIO();writer.write(stream)
    text,status,warnings,fields,total,end=s._read_pdf(stream.getvalue(),page_start=1,page_end=1)
    assert status=='encrypted' and not text and warnings

@pytest.mark.p1
def test_effective_date_does_not_become_issuance_date():
    fields=s._extract_document_fields([(1,'Effective Date: October 1, 2025\nExpiration Date: October 1, 2027')])
    assert fields['issuance_date'] is None
    assert fields['effective_date']=='2025-10-01'

@pytest.mark.p1
def test_section_number_does_not_match_longer_number():
    node=s._main_content(b'<main><h2>10.10 Other</h2><p>wrong</p><h2>10.1 Scope</h2><p>right</p></main>')
    assert 'right' in s._extract_section(node,'10.1')
    assert 'wrong' not in s._extract_section(node,'10.1')

@pytest.mark.p1
def test_selected_section_stays_inside_main_content():
    node=s._main_content(b'<main><h2>Scope</h2><p>right</p></main><aside><p>outside</p></aside>')
    assert 'outside' not in s._extract_section(node,'Scope')

@pytest.mark.p2
def test_blank_section_is_rejected():
    with pytest.raises(ValueError,match='section|blank'):
        s._extract_section(s._main_content(b'<main><h1>Title</h1><p>text</p></main>'),'  ')

@pytest.mark.p1
async def test_wrong_part_page_is_not_labeled_as_requested_part(monkeypatch):
    async def fetch(url,**kw):return b'<main><h1>FAR Overhaul Part 12</h1><p>Other part</p></main>','text/html',url
    monkeypatch.setattr(s,'_fetch_bytes',fetch)
    with pytest.raises(RuntimeError,match='part|Part'):
        await s.get_rfo_part(10)

@pytest.mark.p2
async def test_bad_chunk_inputs_do_not_fetch_upstream(monkeypatch):
    calls=[]
    async def fetch(url,**kw):calls.append(url);return b'<main><h1>FAR Overhaul Part 10</h1></main>','text/html',url
    monkeypatch.setattr(s,'_fetch_bytes',fetch)
    for kwargs in [{'max_characters':1},{'cursor':'bad'},{'section':'   '}]:
        with pytest.raises(ValueError):await s.get_rfo_part(10,**kwargs)
    assert not calls

@pytest.mark.p2
async def test_content_type_requires_exact_media_type(monkeypatch):
    client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'Content-Type':'text/html-impostor'},content=b'<main>x</main>')))
    monkeypatch.setattr(s,'_pacer',NoWaitPacer());monkeypatch.setattr(s,'_client',client);monkeypatch.setattr(s,'_prefer_system_curl',False)
    try:
        with pytest.raises(RuntimeError,match='Content-Type'):
            await s._fetch_bytes(s.RFO_INDEX_URL,allowed_types=('text/html',),max_bytes=1000)
    finally:await client.aclose()

@pytest.mark.p1
def test_applicability_metadata_is_bounded():
    fields=s._extract_document_fields([(1,'Applicability: '+('X'*100_000))])
    assert len(fields['applicability_text'])<=8192
