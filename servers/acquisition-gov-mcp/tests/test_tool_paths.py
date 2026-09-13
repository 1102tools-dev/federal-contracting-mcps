"""P1/P2 SDK-path tests: metadata, pagination, filtering and input validation."""
import asyncio
import json

import pytest
import acquisition_gov_mcp.server as s
from test_server import text_pdf

@pytest.fixture
def sources(monkeypatch,fixtures):
    calls=[]
    async def fetch(url,**kw):
        calls.append(url)
        if url==s.RFO_INDEX_URL:body=(fixtures/'rfo-index.html').read_bytes();kind='text/html'
        elif 'far-overhaul-part-' in url:body=(fixtures/'rfo-part-10.html').read_bytes();kind='text/html'
        elif url.endswith('.pdf'):body=text_pdf('Issued: May 2, 2025\nEffective Date: June 1, 2025\nApplicability: applies to fixture solicitations.','Page two text.');kind='application/pdf'
        else:body=(fixtures/'rfo-guidance.html').read_bytes();kind='text/html'
        return body,kind,url
    monkeypatch.setattr(s,'_fetch_bytes',fetch)
    monkeypatch.setattr(s,'_pdf_slots',asyncio.Semaphore(1))
    return calls

async def call(name,args):
    result=await s.mcp.call_tool(name,args)
    assert not result.is_error
    return result.structured_content or json.loads(result.content[0].text)

@pytest.mark.p1
@pytest.mark.parametrize('name,args,field,expected',[
 ('list_rfo_parts',{'part':10},'count',1),
 ('get_rfo_part',{'part':10,'section':'Model deviation'},'source_kind','model_deviation'),
 ('list_rfo_agency_deviations',{'agency':'General Services'},'total_matches',3),
 ('get_rfo_guidance',{'resource':'faq','heading':'Agency adoption'},'source_kind','nonregulatory_guidance'),
 ('get_rfo_guidance',{'resource':'policy_and_guidance'},'agency','Acquisition.gov'),
 ('get_rfo_guidance',{'resource':'deviation_guidance'},'agency','FAR Council'),
])
async def test_success_via_actual_mcp_dispatch(sources,name,args,field,expected):
    result=await call(name,args)
    assert result[field]==expected
    assert len(result['content_sha256'])==64 and result['retrieved_at']
    assert result['source_url'].startswith('https://www.acquisition.gov/')

@pytest.mark.p1
async def test_pdf_lookup_merge_and_page_scope_via_mcp(sources):
    listing=await call('list_rfo_agency_deviations',{'agency':'General Services'})
    source=listing['results'][0]['source_id']
    result=await call('get_rfo_agency_deviation',{'source_id':source,'page_start':2,'page_end':2})
    assert result['far_parts']==[10,12]
    assert result['page_start']==result['page_end']==2
    assert '[Page 2]' in result['page_numbered_text'] and '[Page 1]' not in result['page_numbered_text']
    assert result['effective_date'] is None
    assert any('elsewhere' in w for w in result['warnings'])

@pytest.mark.p2
@pytest.mark.parametrize('name,args',[
 ('list_rfo_parts',{'part':0}),('list_rfo_parts',{'part':54}),
 ('list_rfo_parts',{'updated_since':'2025-02-30'}),('list_rfo_parts',{'updated_since':'yesterday'}),
 ('get_rfo_part',{'part':10,'max_characters':999}),('get_rfo_part',{'part':10,'max_characters':40001}),
 ('get_rfo_part',{'part':10,'section':' '}),('get_rfo_part',{'part':10,'cursor':'-1'}),
 ('get_rfo_part',{'part':10,'cursor':'9'*1000}),
 ('list_rfo_agency_deviations',{}),('list_rfo_agency_deviations',{'agency':' '}),
 ('list_rfo_agency_deviations',{'part':10,'limit':0}),('list_rfo_agency_deviations',{'part':10,'limit':251}),
 ('get_rfo_agency_deviation',{'source_id':'https://169.254.169.254/'}),
 ('get_rfo_agency_deviation',{'source_id':'agency-deviation-nope'}),
 ('get_rfo_agency_deviation',{'source_id':'agency-deviation-'+'0'*20,'page_start':0}),
 ('get_rfo_agency_deviation',{'source_id':'agency-deviation-'+'0'*20,'page_start':2,'page_end':1}),
 ('get_rfo_agency_deviation',{'source_id':'agency-deviation-'+'0'*20,'page_start':1,'page_end':26}),
 ('get_rfo_guidance',{'resource':'unknown'}),('get_rfo_guidance',{'resource':'faq','heading':' '}),
 ('get_rfo_guidance',{'resource':'faq','cursor':'bad'}),
])
async def test_invalid_inputs_rejected_before_network(sources,name,args):
    try:
        result=await s.mcp.call_tool(name,args)
        assert result.is_error
    except Exception as exc:
        assert type(exc).__name__ in {'ToolError', 'ValidationError'}
    assert sources==[]

@pytest.mark.p1
async def test_unknown_source_id_does_not_fetch_arbitrary_document(sources):
    with pytest.raises(Exception):await s.mcp.call_tool('get_rfo_agency_deviation',{'source_id':'agency-deviation-'+'0'*20})
    assert sources==[s.RFO_INDEX_URL]

@pytest.mark.p1
async def test_date_filter_retains_unknown_dates_with_explicit_warning(sources):
    result=await call('list_rfo_parts',{'updated_since':'2025-09-01'})
    assert [p['part'] for p in result['results']]==[12]
    assert any('without an update date' in w for w in result['warnings'])

@pytest.mark.p1
def test_cursor_round_trip_has_no_gaps_or_duplicates():
    text=('a\nβγδε ' * 500)
    chunks=[];cursor=None
    while True:
        result=s._chunk(text,cursor,1000);chunks.append(result['content']);cursor=result['next_cursor']
        if cursor is None:break
    assert ''.join(chunks)==text

@pytest.mark.p2
def test_ambiguous_heading_requires_specificity():
    node=s._main_content(b'<main><h2>Scope A</h2><p>a</p><h2>Scope B</h2><p>b</p></main>')
    with pytest.raises(ValueError,match='multiple headings'):s._extract_section(node,'Scope')

@pytest.mark.p2
def test_nested_list_and_table_content_not_duplicated():
    node=s._main_content(b'<main><h2>Scope</h2><ul><li>one<p>two</p></li></ul><table><tr><td><p>three</p></td></tr></table></main>')
    result=s._extract_section(node,'Scope')
    assert result.count('two')==result.count('three')==1
