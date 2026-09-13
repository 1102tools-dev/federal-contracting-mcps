"""Use the exact image built by this release without changing service identities."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('slug');p.add_argument('sha');args=p.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}',args.sha):raise SystemExit('Expected a full git commit SHA')
    config_path=ROOT/'deploy'/args.slug/'wrangler.jsonc';config=json.loads(config_path.read_text())
    account=config['account_id'];image=f"registry.cloudflare.com/{account}/{config['name']}:{args.sha}"
    for entry in [config,*config.get('env',{}).values()]:
        for container in entry.get('containers',[]):
            container['image']=image;container.pop('image_build_context',None)
    output=config_path.with_name('wrangler.release.json');output.write_text(json.dumps(config,indent=2)+'\n')
    print(image)
if __name__=='__main__':main()
