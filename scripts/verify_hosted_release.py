"""Verify deployed commit, package version, tool contract, and an upstream call."""
import argparse,json,subprocess,time,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CASES={'usaspending':('get_award_types_reference',{}),'ecfr':('get_latest_date',{}),'gsa-calc':('keyword_search',{'keyword':'program manager','page_size':1}),'federal-register':('search_documents',{'term':'Federal Acquisition Regulation','per_page':1}),'acquisition-gov':('list_rfo_parts',{'part':10})}

def request(url,payload=None):
    cmd=['curl','-fsS','--max-time','65',url]
    if payload is not None:cmd+=['-H','Content-Type: application/json','-H','Accept: application/json, text/event-stream','--data-binary',json.dumps(payload)]
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Endpoint unavailable: '+result.stderr[:200])
    return json.loads(result.stdout)

def main():
    p=argparse.ArgumentParser();p.add_argument('slug');p.add_argument('--sha',required=True);p.add_argument('--base');p.add_argument('--no-upstream',action='store_true');p.add_argument('--wait-seconds',type=int,default=600);args=p.parse_args()
    service=json.loads((ROOT/'deploy/services.json').read_text())[args.slug]
    base=args.base or service['endpoint'].removesuffix('/mcp')
    version=tomllib.loads((ROOT/'servers'/service['package']/'pyproject.toml').read_text())['project']['version']
    deadline=time.monotonic()+args.wait_seconds
    while True:
        try:
            health=request(base+'/health')
            if health.get('release_sha')==args.sha:break
        except (ValueError,RuntimeError):pass
        if time.monotonic()>deadline:raise SystemExit('Hosted service did not report expected release commit before the deadline')
        time.sleep(10)
    def rpc(method,params):
        data=request(base+'/mcp',{'jsonrpc':'2.0','id':1,'method':method,'params':params})
        if data.get('error') or data.get('result',{}).get('isError'):raise RuntimeError('MCP returned an error for '+method)
        return data['result']
    init=rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'1102tools-release-check','version':'1'}})
    assert init['serverInfo']['version']==version,'Deployed package version differs'
    assert not init.get('instructions'),'Server instructions changed from the published baseline'
    actual=rpc('tools/list',{})['tools']
    expected=json.loads((ROOT/'deploy'/args.slug/'tools-contract.json').read_text())
    assert sorted(actual,key=lambda t:t['name'])==sorted(expected,key=lambda t:t['name']),'Published tool definitions differ'
    if not args.no_upstream:
        name,arguments=CASES[args.slug]
        for _ in range(3):
            result=rpc('tools/call',{'name':name,'arguments':arguments})
            data=result.get('structuredContent')
            if data is None and result.get('content'):
                try:data=json.loads(result['content'][0]['text'])
                except (ValueError,KeyError):pass
            assert not (isinstance(data,dict) and data.get('error')),'Upstream error in tool result'
    print(f"Verified {args.slug}: {version}, commit {args.sha}, {len(actual)} tools")
if __name__=='__main__':main()
