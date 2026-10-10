"""Ordinary navigation mistakes must return usable repair guidance through MCP."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import pytest
import regulationsgov_mcp.server as srv
F=json.loads((Path(__file__).parent/'fixtures/ordinary_recovery_2026_10.json').read_text())

@pytest.mark.parametrize('tool,bad,corrected,tokens,record', [
 ('search_documents', {'agency_id':'OSHA','search_term':'"Heat"','within_comment_period':False},
  {'agency_id':'OSHA','search_term':'"Heat"'}, ['omit','comment-period'], 'document'),
 ('search_dockets', {'agency_id':'OSHA','search_term':'"Heat"','last_modified_date_ge':'2025-01-01'},
  {'agency_id':'OSHA','search_term':'"Heat"','last_modified_date_ge':'2025-01-01 00:00:00'},
  ['last_modified_date_ge','YYYY-MM-DD HH:MM:SS'], 'docket'),
])
def test_guidance_repairs_natural_filter_and_date_navigation(monkeypatch,tool,bad,corrected,tokens,record):
    async def run():
        with pytest.raises(Exception) as caught:
            await srv.mcp.call_tool(tool,bad)
        text=str(caught.value).lower()
        assert all(t.lower() in text for t in tokens),text
        calls=[]
        async def captured(path,params=None):
            calls.append((path,params))
            return {'data':[deepcopy(F[record])], 'meta':{'totalElements':1}}
        monkeypatch.setattr(srv,'_get',captured)
        response=(await srv.mcp.call_tool(tool,corrected)).structured_content
        assert response['data'][0]['id']==F[record]['id']
        params=calls[0][1]
        if tool=='search_documents': assert 'filter[withinCommentPeriod]' not in params
        else: assert params['filter[lastModifiedDate][ge]']=='2025-01-01 00:00:00'
    asyncio.run(run())


def test_unexpected_provider_programming_error_is_not_reclassified(monkeypatch):
    async def failed(path,params=None): raise ValueError('unexpected provider implementation error')
    monkeypatch.setattr(srv,'_get',failed)
    with pytest.raises(ValueError):
        asyncio.run(srv._search_documents(agency_id='OSHA',search_term='"Heat"'))
