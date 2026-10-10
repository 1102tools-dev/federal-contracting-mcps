"""Intentional recovery hints stay visible; unrelated faults stay SDK-masked."""
import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver import exceptions as sdk_errors

import usaspending_gov_mcp.server as srv

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/sdk23_expected_guidance.json').read_text())


@pytest.fixture(autouse=True)
def disable_hosted_cache(monkeypatch):
    monkeypatch.setenv('MCP_RESPONSE_CACHE', '0')


def payload(result):
    data = result.structured_content
    return data['result'] if isinstance(data, dict) and set(data) == {'result'} else data


def visible_rejection(name, arguments, expected):
    with pytest.raises(ToolError) as raised:
        asyncio.run(srv.mcp.call_tool(name, arguments))
    for hint in expected:
        assert hint.lower() in str(raised.value).lower()
    return raised.value


def test_parent_profile_id_reports_uei_recovery_without_network(monkeypatch):
    calls = []
    async def send(method, path, *, params=None, body=None):
        calls.append((method, path, params))
        return json.dumps(FIXTURE['children']).encode()
    monkeypatch.setattr(srv, '_send', send)
    monkeypatch.setattr(srv, '_data_version', lambda: asyncio.sleep(0, result=None))
    parent = FIXTURE['parent']
    visible_rejection('get_recipient_children', {'uei_or_duns': parent['id'], 'year': 2024},
                      ['recipient hash', 'UEI', 'search_recipients', 'uei'])
    assert calls == []
    result = payload(asyncio.run(srv.mcp.call_tool('get_recipient_children',
                     {'uei_or_duns': parent['uei'], 'year': 2024})))
    assert result == {'results': FIXTURE['children'], 'total': len(FIXTURE['children'])}
    assert calls == [('GET', f"/api/v2/recipient/children/{parent['uei']}/", {'year': '2024'})]


def test_supplier_report_limit_reports_paging_recovery_without_network(monkeypatch):
    calls = []
    async def post(path, json):
        calls.append((path, json))
        return copy.deepcopy(FIXTURE['award_page'])
    monkeypatch.setattr(srv, '_post', post)
    args = {'award_type': 'contracts', 'awarding_agency': 'Department of Energy',
            'naics_codes': ['541715'], 'time_period_start': '2024-10-01',
            'time_period_end': '2025-09-30'}
    visible_rejection('search_awards', {**args, 'limit': 200}, ['maximum of 100', 'page'])
    assert calls == []
    with pytest.raises(ValueError) as direct:
        srv._clamp_limit(200, cap=100)
    assert isinstance(direct.value, ToolError)
    assert 'maximum of 100' in str(direct.value)
    result = payload(asyncio.run(srv.mcp.call_tool('search_awards', {**args, 'limit': 100})))
    assert {k: v for k, v in result.items() if k != 'time_period_note'} == FIXTURE['award_page']
    assert len(calls) == 1 and calls[0][0] == '/api/v2/search/spending_by_award/'
    assert calls[0][1]['limit'] == 100 and calls[0][1]['page'] == 1


def test_latest_action_selection_reports_required_window_without_network(monkeypatch):
    calls = []
    async def post(path, json):
        calls.append((path, json))
        return copy.deepcopy(FIXTURE['count'])
    monkeypatch.setattr(srv, '_post', post)
    args = {'awarding_agency': 'Department of Energy', 'naics_codes': ['541715'],
            'date_type': 'action_date'}
    visible_rejection('get_award_count', args, ['time window'])
    assert calls == []
    result = payload(asyncio.run(srv.mcp.call_tool('get_award_count',
                     {**args, 'time_period_start': '2025-08-01', 'time_period_end': '2025-08-31'})))
    assert result == FIXTURE['count']
    assert len(calls) == 1
    assert calls[0][1]['filters']['time_period'] == [
        {'start_date': '2025-08-01', 'end_date': '2025-08-31', 'date_type': 'action_date'}]


def test_unknown_programming_and_source_errors_are_not_expected_guidance(monkeypatch):
    secret = 'private-provider-secret'
    async def post(path, json):
        raise ValueError(secret)
    monkeypatch.setattr(srv, '_post', post)
    with pytest.raises(ToolError) as raised:
        asyncio.run(srv.mcp.call_tool('get_award_count', {'awarding_agency': 'Department of Energy'}))
    assert type(raised.value.__cause__) is ValueError
    unexpected = getattr(sdk_errors, 'UnexpectedToolError', None)
    if unexpected is not None:
        assert isinstance(raised.value, unexpected)
        assert str(raised.value) == 'Error executing tool get_award_count'
        assert secret not in str(raised.value)
    request = httpx.Request('GET', 'https://example.invalid/private?api_key=' + secret)
    response = httpx.Response(503, json={'detail': secret}, request=request)
    async def send(*args, **kwargs):
        raise httpx.HTTPStatusError('unavailable', request=request, response=response)
    monkeypatch.setattr(srv, '_send', send)
    monkeypatch.setattr(srv, '_data_version', lambda: asyncio.sleep(0, result=None))
    with pytest.raises(ToolError) as unavailable:
        asyncio.run(srv.mcp.call_tool('get_award_types_reference', {}))
    assert type(unavailable.value.__cause__) is RuntimeError
    assert '503' in str(unavailable.value.__cause__)
    if unexpected is not None:
        assert isinstance(unavailable.value, unexpected)
        assert str(unavailable.value) == 'Error executing tool get_award_types_reference'
        assert secret not in str(unavailable.value) and 'api_key' not in str(unavailable.value)
