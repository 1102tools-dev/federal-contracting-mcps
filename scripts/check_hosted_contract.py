"""Fail before deployment if reviewed tool metadata changes."""
import argparse,asyncio,json,os,sys
from importlib import import_module
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('slug')
    parser.add_argument('--write',action='store_true',help='rewrite the baseline from source (review the git diff before committing)')
    args=parser.parse_args()
    service=json.loads((ROOT/'deploy/services.json').read_text())[args.slug]
    os.environ['USASPENDING_TOOL_PROFILE']='full'
    sys.path.insert(0,str(ROOT/'servers'/service['package']/'src'))
    mcp=import_module(service['module']+'.server').mcp
    actual=[t.model_dump(mode='json',by_alias=True,exclude_none=True) for t in await mcp.list_tools()]
    baseline=ROOT/'deploy'/args.slug/'tools-contract.json'
    if args.write:
        baseline.write_text(json.dumps(sorted(actual,key=lambda t:t['name']),indent=2,sort_keys=True)+'\n')
        print(f"{args.slug}: wrote {len(actual)} tool definitions to {baseline.relative_to(ROOT)}")
        return
    expected=json.loads(baseline.read_text())
    actual=sorted(actual,key=lambda t:t['name']);expected=sorted(expected,key=lambda t:t['name'])
    if actual != expected:
        changed=sorted({t['name'] for t in actual+expected if t not in actual or t not in expected})
        raise SystemExit('Published tool metadata changed: '+', '.join(changed)+'. Review the diff and complete required directory review before updating the baseline.')
    print(f"{args.slug}: {len(actual)} live-baseline tool definitions unchanged")
if __name__=='__main__':asyncio.run(main())
