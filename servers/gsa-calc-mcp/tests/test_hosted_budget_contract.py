"""Hosted durable admission counts tool calls; each reviewed tool must use <=1 API call."""
import pytest
from gsa_calc_mcp import server

CASES={
 'keyword_search':{'keyword':'engineer'},
 'exact_search':{'field':'labor_category','value':'Engineer II'},
 'suggest_contains':{'field':'labor_category','term':'engineer'},
 'filtered_browse':{'education_level':'BA'},
 'igce_benchmark':{'labor_category':'engineer'},
 'price_reasonableness_check':{'labor_category':'engineer','proposed_rate':120},
 'vendor_rate_card':{'vendor_name':'Booz Allen'},
 'sin_analysis':{'sin_code':'541330ENG'},
}

@pytest.mark.asyncio
async def test_every_published_tool_has_a_budget_case():
    assert {t.name for t in await server.mcp.list_tools()}==set(CASES)

@pytest.mark.asyncio
@pytest.mark.parametrize('name,args',CASES.items())
async def test_tool_uses_one_upstream_request(monkeypatch,name,args):
    calls=[]
    async def get(query):
        calls.append(query)
        return {'hits':{'total':{'value':0,'relation':'eq'},'hits':[]},'aggregations':{}}
    monkeypatch.setattr(server,'_get',get)
    await getattr(server,name)(**args)
    assert len(calls)==1
