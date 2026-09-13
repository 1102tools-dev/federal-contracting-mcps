import inspect,json,os,re
from pathlib import Path
TOOLS=['list_rfo_parts','get_rfo_part','list_rfo_agency_deviations','get_rfo_agency_deviation','get_rfo_guidance']
def pytest_collection_modifyitems(items):
 direct={t:[] for t in TOOLS};shared=[];live=[];tiers={}
 for item in items:
  if 'live' in item.keywords or Path(str(item.path)).name=='test_live.py':live.append(item.nodeid);continue
  tier=next((p for p in ['p0','p1','p2','p3'] if p in item.keywords),'legacy');tiers[tier]=tiers.get(tier,0)+1
  params=getattr(getattr(item,'callspec',None),'params',{})
  tool=params.get('tool',params.get('name'))
  if tool in TOOLS:targets=[tool]
  elif item.originalname=='test_tool_inventory_and_strict_schemas':targets=[]
  else:
   source=inspect.getsource(item.obj)
   targets=[t for t in TOOLS if re.search(r'\b'+t+r'\b',source)]
  if targets:
   for t in targets:direct[t].append(item.nodeid)
  else:shared.append(item.nodeid)
 report={'method':'Each collected offline case counts once for each public tool it directly invokes. Shared helper-only tests and catalog-only tests are separate. A multi-tool case can appear in more than one row. Parametrized cases are counted separately; repeated calls inside one case are not.','per_tool':{t:len(v) for t,v in direct.items()},'unique_direct_cases':len(set(x for v in direct.values() for x in v)),'shared_cases':len(shared),'offline_total':sum(tiers.values()),'tiers':tiers,'direct_case_ids':direct,'shared_case_ids':shared,'live_test_functions':live}
 Path(os.environ['COVERAGE_INVENTORY_PATH']).write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:report[k] for k in ['per_tool','unique_direct_cases','shared_cases','offline_total','tiers']}))
