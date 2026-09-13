"""Direct MCP-dispatch contracts: 13 additional scenarios for each public tool."""
import asyncio
import hashlib
import io
import json

import httpx
import pytest
from pypdf import PdfWriter

import acquisition_gov_mcp.server as s
from test_server import NoWaitPacer, blank_pdf, text_pdf
from test_tool_paths import call

TOOLS=['list_rfo_parts','get_rfo_part','list_rfo_agency_deviations','get_rfo_agency_deviation','get_rfo_guidance']

@pytest.fixture
def rig(monkeypatch,fixtures):
    data={'index':(fixtures/'rfo-index.html').read_bytes(),
          'part':(fixtures/'rfo-part-10.html').read_bytes(),
          'guidance':(fixtures/'rfo-guidance.html').read_bytes(),
          'pdf':text_pdf('Issued: May 2, 2025\nEffective: June 1, 2025\nExpires: July 1, 2027\nApplicability: Applies to test solicitations.','Second page.'),'calls':[]}
    async def fetch(url,**kw):
        data['calls'].append(url)
        key='index' if url==s.RFO_INDEX_URL else 'pdf' if url.endswith('.pdf') else 'part' if 'far-overhaul-part-' in url else 'guidance'
        return data[key], 'application/pdf' if key=='pdf' else 'text/html',url
    monkeypatch.setattr(s,'_fetch_bytes',fetch)
    monkeypatch.setattr(s,'_pdf_slots',asyncio.Semaphore(1))
    return data

def source_id(index):
    return s._parse_index(index,s.RFO_INDEX_URL)[0]['agency_deviations'][0]['source_id']

async def rejects(name,args):
    from mcp.server.mcpserver.exceptions import ToolError
    try:
        result=await s.mcp.call_tool(name,args)
    except ToolError:
        return
    assert result.is_error, 'tool incorrectly reported success'

@pytest.mark.p1
@pytest.mark.parametrize('tool',TOOLS)
@pytest.mark.parametrize('failure',['not_found','rate_limited','wrong_mime','hostile_redirect','network_timeout'])
async def test_each_tool_propagates_real_transport_failure(monkeypatch,fixtures,tool,failure):
    index=(fixtures/'rfo-index.html').read_bytes();requests=[]
    args={'list_rfo_parts':{'part':10},'get_rfo_part':{'part':10},'list_rfo_agency_deviations':{'part':10},'get_rfo_agency_deviation':{'source_id':source_id(index)},'get_rfo_guidance':{'resource':'faq'}}[tool]
    def handler(request):
        requests.append(str(request.url))
        if tool=='get_rfo_agency_deviation' and str(request.url)==s.RFO_INDEX_URL:
            return httpx.Response(200,headers={'Content-Type':'text/html'},content=index)
        if failure=='network_timeout':raise httpx.ReadTimeout('fixture timeout',request=request)
        if failure=='not_found':return httpx.Response(404,headers={'Content-Type':'text/html'},content=b'Not found')
        if failure=='rate_limited':return httpx.Response(429,headers={'Retry-After':'17'})
        if failure=='wrong_mime':return httpx.Response(200,headers={'Content-Type':'application/json'},content=b'{}')
        return httpx.Response(302,headers={'Location':'https://169.254.169.254/'})
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(s,'_client',client);monkeypatch.setattr(s,'_pacer',NoWaitPacer())
    monkeypatch.setattr(s,'_prefer_system_curl',False);monkeypatch.setattr(s.shutil,'which',lambda _:None)
    try:
        await rejects(tool,args)
        assert len(requests)==(2 if tool=='get_rfo_agency_deviation' else 1)
        assert all('169.254' not in url for url in requests)
    finally:await client.aclose()

@pytest.mark.p2
@pytest.mark.parametrize('scenario',['unfiltered','no_agency_match','unlisted_part','agency_normalization','date_boundary','source_hash','unknown_date','no_applicability_inference'])
async def test_list_rfo_parts_contract(rig,scenario):
    args={'no_agency_match':{'agency':'Nonexistent Department'},'unlisted_part':{'part':53},'agency_normalization':{'agency':' GENERAL   SERVICES '},'date_boundary':{'updated_since':'2025-08-15'},'unknown_date':{'part':12}}.get(scenario,{})
    result=await call('list_rfo_parts',args)
    if scenario=='unfiltered':assert [p['part'] for p in result['results']]==[10,12] and [p['agency_deviation_count'] for p in result['results']]==[3,1]
    elif scenario in {'no_agency_match','unlisted_part'}:assert result['count']==0 and result['results']==[]
    elif scenario=='agency_normalization':assert [p['agency_deviation_count'] for p in result['results']]==[2,1]
    elif scenario=='date_boundary':assert [p['part'] for p in result['results']]==[10,12]
    elif scenario=='source_hash':assert result['content_sha256']==hashlib.sha256(rig['index']).hexdigest()
    elif scenario=='unknown_date':assert result['results'][0]['updated_date'] is None and result['results'][0]['issuance_date']=='2025-06-01'
    else:assert all('effective_date' not in p and 'applicability_text' not in p and p['source_kind']=='model_deviation' for p in result['results']) and result['warnings']

@pytest.mark.p2
@pytest.mark.parametrize('scenario',['full_text','subsection','missing_section','cursor_past_end','pagination','max_chunk','dates','missing_title'])
async def test_get_rfo_part_contract(rig,scenario):
    args={'part':10}
    if scenario=='subsection':args['section']='10.001'
    if scenario=='missing_section':args['section']='No such section'
    if scenario=='cursor_past_end':args['cursor']='999999'
    if scenario in {'pagination','max_chunk'}:
        rig['part']=b'<main><h1>FAR Overhaul Part 10</h1><p>'+('alpha beta ' * 5000).encode()+b'</p></main>'
        args['max_characters']=1000 if scenario=='pagination' else 40000
    if scenario=='missing_title':rig['part']=b'<main><p>Temporary service page</p></main>'
    if scenario in {'missing_section','cursor_past_end','missing_title'}:
        await rejects('get_rfo_part',args);return
    result=await call('get_rfo_part',args)
    if scenario=='full_text':assert 'Practitioner resources' in result['content'] and 'Site navigation' not in result['content'] and 'Footer' not in result['content']
    elif scenario=='subsection':assert '10.001' in result['content'] and 'Practitioner resources' not in result['content'] and 'Agencies should' not in result['content']
    elif scenario=='pagination':
        chunks=[result['content']]
        while result['next_cursor']:
            args['cursor']=result['next_cursor'];result=await call('get_rfo_part',args);chunks.append(result['content'])
        expected='FAR Overhaul Part 10\n'+('alpha beta '*5000).strip()
        assert ''.join(chunks)==expected
    elif scenario=='max_chunk':assert len(result['content'])==40000 and result['next_cursor']=='40000'
    else:assert result['issuance_date']=='2025-05-02' and result['updated_date']=='2025-08-15' and result['effective_date'] is None and result['applicability_text'] is None

@pytest.mark.p2
@pytest.mark.parametrize('scenario',['limit_one','limit_max','combined_filters','no_match','normalized_agency','duplicate_order','metadata_only','cross_part_id'])
async def test_list_rfo_agency_deviations_contract(rig,scenario):
    args={'part':10}
    if scenario=='limit_one':args['limit']=1
    if scenario=='limit_max':args={'agency':'Administration','limit':250}
    if scenario=='combined_filters':args['agency']='Aeronautics'
    if scenario=='no_match':args['agency']='Nonexistent Department'
    if scenario=='normalized_agency':args={'agency':' GENERAL   SERVICES '}
    if scenario=='cross_part_id':args={'agency':'General Services'}
    result=await call('list_rfo_agency_deviations',args)
    if scenario=='limit_one':assert result['count']==1 and result['total_matches']==3 and any('truncated' in w for w in result['warnings'])
    elif scenario=='limit_max':assert result['count']==result['total_matches']==4 and not any('truncated' in w for w in result['warnings'])
    elif scenario=='combined_filters':assert result['count']==1 and 'Aeronautics' in result['results'][0]['agency'] and result['results'][0]['far_parts']==[10]
    elif scenario=='no_match':assert result['count']==result['total_matches']==0
    elif scenario=='normalized_agency':assert result['count']==3
    elif scenario=='duplicate_order':assert [d['index_occurrence'] for d in result['results']]==[1,2,3] and result['results'][0]['source_id']==result['results'][1]['source_id']
    elif scenario=='metadata_only':assert all(d['content_sha256'] is None and d['effective_date'] is None and d['text_extraction_status']=='not_retrieved' for d in result['results']) and len(rig['calls'])==1
    else:assert len({d['source_id'] for d in result['results']})==1 and {p for d in result['results'] for p in d['far_parts']}=={10,12}

@pytest.mark.p2
@pytest.mark.parametrize('scenario',['default_pages','maximum_pages','encrypted','blank','malformed','partially_extractable','document_fields','past_last_page'])
async def test_get_rfo_agency_deviation_contract(rig,scenario):
    args={'source_id':source_id(rig['index'])}
    if scenario in {'default_pages','maximum_pages'}:rig['pdf']=text_pdf(*[f'Page text {i}' for i in range(1,31)])
    if scenario=='maximum_pages':args['page_end']=25
    if scenario=='encrypted':
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.encrypt('secret');out=io.BytesIO();writer.write(out);rig['pdf']=out.getvalue()
    if scenario=='blank':rig['pdf']=blank_pdf()
    if scenario=='malformed':rig['pdf']=b'not-a-pdf'
    if scenario=='partially_extractable':rig['pdf']=text_pdf('Readable first page','')
    if scenario=='past_last_page':args['page_start']=10
    result=await call('get_rfo_agency_deviation',args)
    if scenario in {'default_pages','maximum_pages'}:
        end=10 if scenario=='default_pages' else 25
        assert result['total_pages']==30 and result['page_end']==end and f'[Page {end}]' in result['page_numbered_text'] and f'[Page {end+1}]' not in result['page_numbered_text'] and any('elsewhere' in w for w in result['warnings'])
    elif scenario in {'encrypted','blank','malformed','partially_extractable','past_last_page'}:
        expected={'encrypted':'encrypted','blank':'unextractable','malformed':'error','partially_extractable':'partial','past_last_page':'error'}[scenario]
        assert result['text_extraction_status']==expected and result['warnings'] and result['content_sha256']==hashlib.sha256(rig['pdf']).hexdigest()
    else:assert result['issuance_date']=='2025-05-02' and result['effective_date']=='2025-06-01' and result['expiration_date']=='2027-07-01' and result['applicability_text'].startswith('Page 1:')

@pytest.mark.p2
@pytest.mark.parametrize('scenario',['all_html','missing_html_heading','html_pagination','pdf_heading','missing_pdf_heading','encrypted_pdf','pdf_page_cap','pdf_document_fields'])
async def test_get_rfo_guidance_contract(rig,scenario):
    args={'resource':'faq' if scenario in {'all_html','missing_html_heading','html_pagination'} else 'deviation_guidance'}
    if scenario=='missing_html_heading':args['heading']='No such heading'
    if scenario=='html_pagination':rig['guidance']=b'<main><h1>FAQ</h1><p>'+b'test '*10000+b'</p></main>'
    if scenario=='pdf_heading':rig['pdf']=text_pdf('Introductory text\nRequested heading\nRelevant text');args['heading']='Requested heading'
    if scenario=='missing_pdf_heading':args['heading']='No such heading'
    if scenario=='encrypted_pdf':
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.encrypt('secret');out=io.BytesIO();writer.write(out);rig['pdf']=out.getvalue()
    if scenario=='pdf_page_cap':rig['pdf']=text_pdf(*[f'Page text {i}' for i in range(1,31)])
    if scenario in {'missing_html_heading','missing_pdf_heading'}:
        await rejects('get_rfo_guidance',args);return
    result=await call('get_rfo_guidance',args)
    assert result['source_kind']=='nonregulatory_guidance' and any('not codified' in w for w in result['warnings'])
    if scenario=='all_html':assert 'Agency adoption' in result['content'] and 'Other guidance' in result['content']
    elif scenario=='html_pagination':
        chunks=[result['content']]
        while result['next_cursor']:
            args['cursor']=result['next_cursor'];result=await call('get_rfo_guidance',args);chunks.append(result['content'])
        assert ''.join(chunks)=='FAQ\n'+('test '*10000).strip()
    elif scenario=='pdf_heading':assert result['content'].startswith('Requested heading') and 'Introductory' not in result['content']
    elif scenario=='encrypted_pdf':assert result['text_extraction_status']=='encrypted' and result['content']==''
    elif scenario=='pdf_page_cap':assert result['total_pages']==30 and '[Page 25]' in result['content'] and '[Page 26]' not in result['content'] and any('elsewhere' in w for w in result['warnings'])
    else:assert result['agency']=='FAR Council' and result['issuance_date']=='2025-05-02' and result['effective_date']=='2025-06-01' and result['far_parts']==[]

@pytest.mark.p1
async def test_get_rfo_part_accepts_actual_large_part52_and_paginates(monkeypatch,fixtures):
    import gzip
    raw=gzip.decompress((fixtures/'rfo-part-52-2026-09-13.html.gz').read_bytes())
    async def fetch(url,**kw):return raw,'text/html',url
    monkeypatch.setattr(s,'_fetch_bytes',fetch)
    first=await call('get_rfo_part',{'part':52,'max_characters':1000})
    assert first['far_parts']==[52] and first['text_extraction_status']=='complete'
    assert first['content_sha256']==hashlib.sha256(raw).hexdigest() and first['next_cursor']=='1000'
    second=await call('get_rfo_part',{'part':52,'max_characters':1000,'cursor':first['next_cursor']})
    assert second['cursor']=='1000' and second['content']!=first['content'] and second['content_sha256']==first['content_sha256']
