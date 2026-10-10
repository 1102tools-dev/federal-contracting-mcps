"""Realistic Round 2 definition research against saved authoritative eCFR text."""
import asyncio
from pathlib import Path

import pytest

import ecfr_mcp.server as srv


@pytest.mark.parametrize('term', [
    'contracting officer representative',
    "contracting officer's representative",
    'COR',
])
def test_cor_definition_and_followups_complete_from_far_2_101(monkeypatch, term):
    xml = (Path(__file__).parent / 'fixtures/ecfr_xml/t48_2.101.xml').read_text()

    async def resolve(title):
        return '2026-10-07'

    async def get_xml(path, params):
        assert params == {'section': '2.101'}
        return xml

    async def no_fallback(*args, **kwargs):
        pytest.fail('A FAR 2.101 definition must not be reported absent and searched elsewhere')

    monkeypatch.setattr(srv, '_resolve_date', resolve)
    monkeypatch.setattr(srv, '_get_xml', get_xml)
    monkeypatch.setattr(srv, '_get_json', no_fallback)
    result = asyncio.run(srv.find_far_definition(term))
    assert result['definition_count'] == 1
    definition = result['matches'][0]
    assert definition['kind'] == 'definition'
    assert definition['term'] == "Contracting officer's representative (COR)"
    assert 'designated and authorized in writing' in ' '.join(definition['context'])
    assert 'specific technical or administrative functions' in ' '.join(definition['context'])
    assert 'does not define' not in result['note']


def test_grant_comparison_hint_completes_the_historical_read(monkeypatch):
    import ast
    import re

    xml = '<DIV8 N="200.320" TYPE="SECTION"><HEAD>§ 200.320 Procurement methods.</HEAD><P>Grant recipients must document procurement procedures.</P></DIV8>'

    async def resolve(title):
        return '2026-10-07'

    async def get_xml(path, params):
        if 'title-2.xml' not in path:
            raise RuntimeError('HTTP 404: No matching content found.')
        return xml

    monkeypatch.setattr(srv, '_resolve_date', resolve)
    monkeypatch.setattr(srv, '_get_xml', get_xml)
    compared = asyncio.run(srv.compare_versions('200.320', '2024-09-30', '2024-10-01', title_number=2, changes_only=True))
    hint = re.search(r'get_cfr_content\(([^)]+)\)', compared['note']).group(1)
    call = ast.parse('get_cfr_content(' + hint.replace('...', "'2024-10-01'") + ')', mode='eval').body
    args = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    read = asyncio.run(srv.get_cfr_content(**args))
    assert read['title'] == 2
    assert 'Grant recipients' in read['paragraphs'][0]


@pytest.mark.parametrize('filters,expected_ids', [
    ({'chapter': '1', 'part': '52'}, [4065]),
    ({'chapter': '2', 'section': '252.225-7035'}, [4313]),
    ({'chapter': '1', 'part': '52', 'section': '52.212-3'}, [4065]),
])
def test_correction_research_stays_within_requested_scope(monkeypatch, filters, expected_ids):
    import json
    data = json.loads((Path(__file__).parent / 'fixtures/ecfr_xml/corrections_scope_20261010.json').read_text())

    async def get_json(path, params):
        assert path == '/api/admin/v1/corrections.json'
        assert params == {'title': '48'}
        return data

    monkeypatch.setattr(srv, '_get_json', get_json)
    result = asyncio.run(srv.get_corrections(title_number=48, since_year=2024, **filters))
    assert [row['id'] for row in result['corrections']] == expected_ids
    assert result['count_filtered'] == len(expected_ids)
