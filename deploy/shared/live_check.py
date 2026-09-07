"""Exercise every public tool; prerequisite IDs come from live responses."""
import json,subprocess,sys,time
from pathlib import Path
slug=sys.argv[1];base=f'https://{slug}.1102tools.com';out=Path(__file__).resolve().parents[1]/slug/'review';evidence=[]
def rpc(method,params):
 p=subprocess.run(['curl','--doh-url','https://cloudflare-dns.com/dns-query','-fsS','--max-time','65',base+'/mcp','-H','Content-Type: application/json','-H','Accept: application/json, text/event-stream','--data-binary',json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})],capture_output=True,text=True)
 if p.returncode: raise RuntimeError(p.stderr[:300])
 return json.loads(p.stdout)
def call(name,args):
 start=time.monotonic()
 try:
  r=rpc('tools/call',{'name':name,'arguments':args});d=r.get('result',{});err=r.get('error') or (d if d.get('isError') else None)
  if err:raise RuntimeError(str(err)[:400])
  data=d.get('structuredContent')
  if data is None:data=json.loads(d['content'][0]['text'])
  if isinstance(data,dict) and data.get('error'):raise RuntimeError(str(data['error'])[:400])
  evidence.append({'tool':name,'ok':True,'seconds':round(time.monotonic()-start,2),'arguments':args})
  (out/f'live-{name}.json').write_text(json.dumps(data,indent=2)+'\n')
  return data
 except Exception as e:
  evidence.append({'tool':name,'ok':False,'error':str(e)});return {}
 finally:
  print(slug,json.dumps(evidence[-1]),flush=True)
  (out/'live-results.json').write_text(json.dumps({'endpoint':base+'/mcp','results':evidence},indent=2)+'\n')
rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'1102tools-review','version':'1'}})
tools=rpc('tools/list',{})['result']['tools'];(out/'tools.json').write_text(json.dumps(tools,indent=2)+'\n')
if slug=='gsa-calc':
 d=call('keyword_search',{'keyword':'program manager','page_size':3});rows=[x['_source'] for x in d.get('hits',{}).get('hits',[])]
 vendor=(rows[0].get('vendor_name') if rows else None)
 call('exact_search',{'field':'labor_category','value':rows[0]['labor_category'] if rows else 'Program Manager','page_size':3})
 call('suggest_contains',{'field':'labor_category','term':'program'})
 call('filtered_browse',{'experience_min':5,'price_min':50,'price_max':150,'page_size':3})
 call('igce_benchmark',{'labor_category':'program manager'})
 call('price_reasonableness_check',{'labor_category':'program manager','proposed_rate':150})
 if vendor:call('vendor_rate_card',{'vendor_name':vendor,'page_size':3})
 call('sin_analysis',{'sin_code':'54151S','page_size':3})
elif slug=='ecfr':
 call('get_latest_date',{})
 for n,a in [('get_cfr_content',{'section':'1.102'}),('get_cfr_structure',{'part':'1'}),('get_version_history',{'section':'1.102'}),('get_ancestry',{'section':'1.102'}),('search_cfr',{'query':'market research','title':48,'per_page':3}),('list_agencies',{}),('get_corrections',{'limit':3}),('lookup_far_clause',{'section_id':'52.212-4'}),('compare_versions',{'section_id':'1.102','date_before':'2025-01-01','date_after':'2026-01-01'}),('list_sections_in_part',{'part_number':10}),('find_far_definition',{'term':'commercial product','max_matches':3}),('find_recent_changes',{'since_date':'2026-08-01','per_page':3})]:call(n,a)
elif slug=='federal-register':
 d=call('search_documents',{'term':'Federal Acquisition Regulation','per_page':3});rows=d.get('results',[])
 if rows:
  detail=call('get_document',{'document_number':rows[0]['document_number']});call('get_documents_batch',{'document_numbers':[x['document_number'] for x in rows]})
  docket=(detail.get('docket_ids') or [None])[0]
  if docket:call('far_case_history',{'docket_id':docket})
 for n,a in [('get_facet_counts',{'facet':'type','term':'Federal Acquisition Regulation'}),('get_public_inspection',{'limit':3}),('list_agencies',{'query':'General Services'}),('open_comment_periods',{'term':'acquisition','limit':3})]:call(n,a)
elif slug=='acquisition-gov':
 call('list_rfo_parts',{'part':10});call('get_rfo_part',{'part':10,'max_characters':4000})
 d=call('list_rfo_agency_deviations',{'part':10,'limit':3});rows=d.get('results',[])
 if rows:call('get_rfo_agency_deviation',{'source_id':rows[0]['source_id'],'page_end':2})
 call('get_rfo_guidance',{'resource':'faq'})
missing={t['name'] for t in tools}-{e['tool'] for e in evidence}
print('Missing:',sorted(missing));sys.exit(bool(missing) or any(not e['ok'] for e in evidence))
