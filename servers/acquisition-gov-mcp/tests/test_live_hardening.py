"""Serialized live SDK-path evidence, gated and never enabled by default CI."""
import asyncio
import json
import os
import time
from pathlib import Path

import pytest
import acquisition_gov_mcp.server as s

pytestmark=[pytest.mark.live,pytest.mark.skipif(os.getenv('ACQUISITION_GOV_LIVE_TESTS')!='1',reason='set ACQUISITION_GOV_LIVE_TESTS=1 for serialized official-source checks')]

async def probe(name,args,records):
    start=time.monotonic();result=await s.mcp.call_tool(name,args)
    assert not result.is_error
    data=result.structured_content or json.loads(result.content[0].text)
    assert len(data['content_sha256'])==64
    assert data['source_url'].startswith('https://www.acquisition.gov/')
    record={'tool':name,'arguments':args,'seconds':round(time.monotonic()-start,3),'source_url':data['source_url'],'content_sha256':data['content_sha256'],'retrieved_at':data['retrieved_at'],'count':data.get('count'),'text_extraction_status':data.get('text_extraction_status'),'total_pages':data.get('total_pages'),'warnings':data.get('warnings',[])}
    records.append(record)
    print(json.dumps(record),flush=True)
    return data

async def test_all_five_tools_and_all_guidance_resources():
    records=[]
    try:
        parts=await probe('list_rfo_parts',{},records)
        assert parts['results'] and all(1<=p['part']<=53 for p in parts['results'])
        model=await probe('get_rfo_part',{'part':10,'max_characters':1000},records)
        assert model['far_parts']==[10] and model['content'] and model['text_extraction_status']=='complete'
        section=await probe('get_rfo_part',{'part':10,'section':'10.001','max_characters':1000},records)
        assert '10.001' in section['content'] and section['section']=='10.001'
        if model['next_cursor']:
            continuation=await probe('get_rfo_part',{'part':10,'max_characters':1000,'cursor':model['next_cursor']},records)
            assert continuation['cursor']==model['next_cursor']
            assert continuation['content_sha256']==model['content_sha256']
        listing=await probe('list_rfo_agency_deviations',{'part':10,'limit':10},records)
        assert listing['results']
        chosen=listing['results'][0]
        filtered=await probe('list_rfo_agency_deviations',{'agency':chosen['agency'],'part':10,'limit':10},records)
        assert any(d['source_id']==chosen['source_id'] for d in filtered['results'])
        document=await probe('get_rfo_agency_deviation',{'source_id':chosen['source_id'],'page_start':1,'page_end':1},records)
        assert document['total_pages']>=1 and document['text_extraction_status']=='complete' and document['page_numbered_text']
        for resource in ['faq','policy_and_guidance','deviation_guidance']:
            guidance=await probe('get_rfo_guidance',{'resource':resource},records)
            assert guidance['text_extraction_status']=='complete' and guidance['content']
            assert guidance['source_kind']=='nonregulatory_guidance'
    finally:
        output=os.getenv('ACQUISITION_GOV_EVIDENCE_PATH')
        if output:Path(output).write_text(json.dumps({'observations':records},indent=2)+'\n')
        if s._client is not None:await s._client.aclose();s._client=None

async def test_cached_curl_transport_handles_successive_live_calls(monkeypatch):
    records=[]
    monkeypatch.setattr(s,'_prefer_system_curl',True)
    try:
        result=await probe('list_rfo_parts',{'part':10},records)
        assert result['count']==1
        result=await probe('get_rfo_guidance',{'resource':'faq'},records)
        assert result['content'] and result['text_extraction_status']=='complete'
    finally:
        output=os.getenv('ACQUISITION_GOV_EVIDENCE_PATH')
        if output:Path(output).with_name(Path(output).stem+'-curl.json').write_text(json.dumps({'observations':records},indent=2)+'\n')
        if s._client is not None:await s._client.aclose();s._client=None
