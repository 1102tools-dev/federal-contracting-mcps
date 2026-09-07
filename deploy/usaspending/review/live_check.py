"""Run against a local/container/public HTTP endpoint; save evidence without raw data."""
import asyncio, json, sys, time
from pathlib import Path
import httpx

async def main():
    url = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8080/mcp'
    evidence=[]
    async with httpx.AsyncClient(timeout=65) as client:
        async def rpc(method, params):
            r=await client.post(url, headers={'Accept':'application/json, text/event-stream'}, json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
            r.raise_for_status()
            return r.json()
        await rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'1102tools-qualification','version':'1'}})
        tools=(await rpc('tools/list',{}))['result']['tools']
        async def call(name,args):
            start=time.monotonic()
            try:
                r=await rpc('tools/call',{'name':name,'arguments':args})
                result=r.get('result',{})
                error=r.get('error') or (result if result.get('isError') else None)
                data=result.get('structuredContent')
                if data is None and result.get('content'):
                    try: data=json.loads(result['content'][0]['text'])
                    except (ValueError,KeyError): pass
                entry={'tool':name,'ok':not bool(error),'seconds':round(time.monotonic()-start,2)}
                if error: entry['error']=str(error)[:500]
                evidence.append(entry)
                print(json.dumps(entry),flush=True)
                return data or {}
            except Exception as e:
                entry={'tool':name,'ok':False,'error':str(e)[:500]};evidence.append(entry);print(json.dumps(entry),flush=True);return {}
        contracts=await call('search_awards',{'keywords':['software'],'limit':1})
        idvs=await call('search_awards',{'award_type':'idvs','keywords':['services'],'limit':1})
        recipients=await call('search_recipients',{'keyword':'Lockheed','limit':1})
        accounts=await call('list_federal_accounts',{'limit':1})
        # IDs must come from the actual service response, never guessed fixtures.
        Path('/tmp/usaspending-live-fixtures.json').write_text(json.dumps({'contracts':contracts,'idvs':idvs,'recipients':recipients,'accounts':accounts}))
        contract=(contracts.get('results') or [{}])[0]; idv=(idvs.get('results') or [{}])[0];recipient=(recipients.get('results') or [{}])[0];account=(accounts.get('results') or [{}])[0]
        award=contract.get('generated_internal_id'); idv_id=idv.get('generated_internal_id')
        common={'toptier_code':'075','fiscal_year':2025,'limit':1,'page':1,'time_period_start':'2024-10-01','time_period_end':'2025-09-30','generated_award_id':award,'generated_idv_id':idv_id,'award_id':award,'category':'awarding_agency','code':'541512','state_fips':'48','piid':contract.get('Award ID'),'recipient_hash':recipient.get('id'),'recipient_id':recipient.get('id'),'uei_or_duns':recipient.get('uei'),'account_code':account.get('account_number'),'account_id':account.get('account_id')}
        terms={'autocomplete_psc':'D3','autocomplete_naics':'5415','autocomplete_recipient':'Lockheed','autocomplete_awarding_agency':'Health','autocomplete_funding_agency':'Health','autocomplete_cfda':'health','autocomplete_glossary':'obligation'}
        already={e['tool'] for e in evidence}
        for tool in tools:
            name=tool['name']
            if name in already:continue
            props=tool['inputSchema'].get('properties',{});required=tool['inputSchema'].get('required',[])
            args={k:v for k,v in common.items() if k in props and v is not None}
            if name.startswith('get_idv_'):args['award_id']=idv_id if 'award_id' in props else None;args={k:v for k,v in args.items() if v is not None}
            if 'search_text' in props:args['search_text']=terms.get(name,'health')
            if any(k not in args for k in required):
                entry={'tool':name,'ok':False,'error':'Live prerequisite fixture unavailable: '+','.join(k for k in required if k not in args)};evidence.append(entry);print(json.dumps(entry),flush=True);continue
            await call(name,args)
        Path(__file__).with_name('live-results.json').write_text(json.dumps({'endpoint':url,'tools':len(tools),'results':evidence},indent=2)+'\n')
        return sum(not e['ok'] for e in evidence)
if __name__=='__main__':sys.exit(asyncio.run(main()))
