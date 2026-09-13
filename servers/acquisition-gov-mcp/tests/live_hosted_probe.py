"""Serialized sampled production checks. No concurrency or rate-limit probing."""
import argparse,json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
BASE='https://acquisition-gov.1102tools.com'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expected-sha')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
SHA=args.expected_sha
OUT=args.output;records=[]
def request(path,payload=None):
 cmd=['curl','-fsS','--max-time','65',BASE+path]
 if payload is not None:cmd+=['-H','Content-Type: application/json','-H','Accept: application/json, text/event-stream','--data-binary',json.dumps(payload)]
 p=subprocess.run(cmd,text=True,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr[:250])
 return json.loads(p.stdout)
def probe(name,args):
 if records:time.sleep(3)
 started=time.monotonic()
 raw=request('/mcp',{'jsonrpc':'2.0','id':len(records)+1,'method':'tools/call','params':{'name':name,'arguments':args}})
 assert 'error' not in raw,raw
 result=raw['result'];assert not result.get('isError'),result
 data=result.get('structuredContent') or json.loads(result['content'][0]['text'])
 assert len(data['content_sha256'])==64 and data['source_url'].startswith('https://www.acquisition.gov/')
 record={'tool':name,'arguments':args,'seconds':round(time.monotonic()-started,3),'source_url':data['source_url'],'content_sha256':data['content_sha256'],'retrieved_at':data['retrieved_at'],'count':data.get('count'),'total_matches':data.get('total_matches'),'total_pages':data.get('total_pages'),'extraction_status':data.get('text_extraction_status'),'returned_characters':data.get('returned_characters',len(data.get('content',''))),'agency':data.get('agency'),'warnings':data.get('warnings',[])}
 records.append(record)
 print(json.dumps({'probe':len(records),**record}),flush=True)
 return data
failure=None
try:
 health=request('/health')
 if SHA is not None:assert health.get('release_sha')==SHA,health
 SHA=health.get('release_sha')
 parts=probe('list_rfo_parts',{});available={p['part'] for p in parts['results']}
 assert parts['count']>=1
 assert probe('list_rfo_parts',{'part':12})['results'][0]['part']==12
 dated=probe('list_rfo_parts',{'updated_since':'2025-01-01'})
 assert all(p['updated_date'] is None or p['updated_date']>='2025-01-01' for p in dated['results'])
 assert probe('list_rfo_parts',{'agency':'General Services'})['count']>=1
 models={}
 for part in [1,2,12,15,39,52,53]:
  assert part in available, f'Part {part} no longer listed'
  models[part]=probe('get_rfo_part',{'part':part,'max_characters':1000})
  assert models[part]['text_extraction_status']=='complete' and models[part]['content'] and models[part]['far_parts']==[part]
 for part in [52,15]:
  cursor=models[part]['next_cursor'];assert cursor, f'Part {part} unexpectedly fits one chunk'
  continued=probe('get_rfo_part',{'part':part,'max_characters':1000,'cursor':cursor})
  assert continued['cursor']==cursor and continued['content'] and continued['content_sha256']==models[part]['content_sha256']
 documents=[]
 for part in [1,12,52]:
  listing=probe('list_rfo_agency_deviations',{'part':part,'limit':250})
  assert listing['count']==len(listing['results']) and all(d['far_parts']==[part] for d in listing['results'])
  documents+=listing['results']
 chosen=[];agencies=set();urls=set()
 for item in documents:
  if item['agency'] not in agencies and item['source_url'] not in urls and item['source_url'].lower().endswith('.pdf'):
   chosen.append(item);agencies.add(item['agency']);urls.add(item['source_url'])
  if len(chosen)==5:break
 assert len(chosen)==5,'Fewer than five distinct indexed agency PDFs'
 for item in chosen:
  pdf=probe('get_rfo_agency_deviation',{'source_id':item['source_id'],'page_start':1,'page_end':2})
  assert pdf['text_extraction_status'] in {'complete','partial','unextractable','encrypted'}
  if pdf['text_extraction_status'] in {'complete','partial'}:assert pdf['page_numbered_text']
 for resource in ['faq','policy_and_guidance','deviation_guidance']:
  result=probe('get_rfo_guidance',{'resource':resource})
  assert result['source_kind']=='nonregulatory_guidance' and result['text_extraction_status']=='complete' and result['content']
 assert len(records)==24
except BaseException as exc:
 failure=f'{type(exc).__name__}: {exc}'
 print('FAILED: '+failure,flush=True)
 raise
finally:
 OUT.write_text(json.dumps({'tested_at':datetime.now(timezone.utc).isoformat(),'release_sha':SHA,'endpoint':BASE+'/mcp','expected_calls':24,'completed_calls':len(records),'failure':failure,'scope':'Serialized production sample across seven FAR parts, five distinct agency PDFs, filters, pagination and all guidance resources. Not exhaustive coverage or a load test.','observations':records},indent=2)+'\n')
