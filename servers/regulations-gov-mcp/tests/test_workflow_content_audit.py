"""Content regressions for workflow continuation and unavailable organizations."""
import asyncio
import pytest
import regulationsgov_mcp.server as srv


def call(name, **arguments):
    return asyncio.run(srv.mcp.call_tool(name, arguments)).structured_content

@pytest.mark.parametrize('workflow', ['history', 'open'])
def test_workflow_page_past_end_explains_how_to_recover(monkeypatch, workflow):
    async def fake(path, params=None):
        if path.startswith('dockets/'):
            return {'data': {'attributes': {'title': 'Semiconductor products'}}}
        return {'data': [], 'meta': {'totalElements': 5, 'lastPage': True}}
    monkeypatch.setattr(srv, '_get', fake)
    if workflow == 'history':
        result = call('far_case_history', docket_id='FAR-2023-0008', page_size=5, page_number=2)
    else:
        result = call('open_comment_periods', agency_ids=['FAR'], page_size=5, page_number=2)
    assert result['paged_past_end'] is True
    assert 'Last page with data is page 1' in result['paged_past_end_reason']
    assert result['documents'] == []


def test_organization_lookup_failure_is_not_an_individual_submitter(monkeypatch):
    async def fake(path, params=None):
        raise srv.ToolError('HTTP 429 rate limited')
    monkeypatch.setattr(srv, '_get', fake)
    result = {'data': [{'id': 'FAR-2023-0008-0025', 'attributes': {}}]}
    asyncio.run(srv._add_organizations(result))
    assert result['data'][0]['attributes']['organizationLookupFailed'] is True
    assert 'failed' in result['organization_lookup']['note'].lower()
    assert 'unknown' in result['organization_lookup']['note'].lower()

@pytest.mark.parametrize('workflow', ['history', 'open'])
def test_workflow_preserves_page_limit_guidance(monkeypatch, workflow):
    async def fake(path, params=None):
        if path.startswith('dockets/'):
            return {'data': {'attributes': {'title': 'Large docket'}}}
        if path == 'comments':
            return {'data': [], 'meta': {'totalElements': 0}}
        return {'data': [{'id': f'FAR-2023-0008-{i:04d}', 'attributes': {'title': str(i)}} for i in range(5)], 'meta': {'totalElements': 501}}
    monkeypatch.setattr(srv, '_get', fake)
    result = call('far_case_history', docket_id='FAR-2023-0008', page_size=5) if workflow == 'history' else call('open_comment_periods', agency_ids=['FAR'], page_size=5)
    assert '301 cannot be reached by paging' in result['page_limit_note']
    assert result['next_page_number'] == 2


@pytest.mark.parametrize('workflow', ['history', 'open'])
def test_workflow_zero_matches_is_explicit(monkeypatch, workflow):
    async def fake(path, params=None):
        if path.startswith('dockets/'):
            return {'data': {'attributes': {'title': 'Empty docket'}}}
        return {'data': [], 'meta': {'totalElements': 0}}
    monkeypatch.setattr(srv, '_get', fake)
    result = call('far_case_history', docket_id='FAR-2023-0008', page_size=5) if workflow == 'history' else call('open_comment_periods', agency_ids=['ZZZ'], page_size=5)
    assert result['no_data'] is True
    assert result['no_data_reason']
