"""Normal current-FY source availability preserves the actual range and recovery."""
import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
import usaspending_gov_mcp.server as s

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/federal_account_available_fy_1020.json').read_text())


def provider(monkeypatch, status=400):
    async def data_version():
        return None

    async def send(method, path, *, params=None, body=None):
        assert method == 'POST' and path == '/api/v2/federal_accounts/'
        if 'filters' not in body:
            return json.dumps(copy.deepcopy(FIXTURE['supported_default']['raw']))
        request = httpx.Request(method, 'https://api.usaspending.gov' + path, json=body)
        payload = FIXTURE['source_http400']['raw'] if status == 400 else {'detail': 'service temporarily unavailable'}
        response = httpx.Response(status, json=payload, request=request)
        response.raise_for_status()
        raise AssertionError('Expected source error')

    monkeypatch.setattr(s, '_data_version', data_version)
    monkeypatch.setattr(s, '_send', send)


def test_current_unavailable_fy_preserves_source_range_and_recovery(monkeypatch):
    provider(monkeypatch)
    with pytest.raises(Exception) as caught:
        asyncio.run(s.mcp.call_tool('list_federal_accounts', {'keyword': 'Energy', 'fiscal_year': FIXTURE['year'], 'limit': 5}))
    # The exact authoritative explanation, unavailable requested year and
    # supported parameter recovery must reach the client, not a crash label.
    message = str(caught.value)
    assert FIXTURE['source_http400']['raw']['detail'] in message
    assert str(FIXTURE['year']) in message
    assert 'fiscal_year' in message and 'fy' in message


def test_omit_unavailable_fy_recovers_actual_latest_source_year(monkeypatch):
    provider(monkeypatch)
    result = asyncio.run(s.mcp.call_tool('list_federal_accounts', {'keyword': 'Energy', 'limit': 5}))
    out = result.structured_content
    if set(out) == {'result'}:
        out = out['result']
    assert out == FIXTURE['supported_default']['raw']
    assert out['fy'] != str(FIXTURE['year'])


def test_unexpected_503_is_not_relabelled_as_unavailable_year(monkeypatch):
    provider(monkeypatch, status=503)
    with pytest.raises(Exception) as caught:
        asyncio.run(s.mcp.call_tool('list_federal_accounts', {'keyword': 'Energy', 'fiscal_year': FIXTURE['year'], 'limit': 5}))
    chain = caught.value
    errors = []
    while chain is not None:
        errors.append(str(chain))
        chain = chain.__cause__
    assert any('HTTP 503' in error for error in errors)
    assert not any('Omit fiscal_year' in error for error in errors)
