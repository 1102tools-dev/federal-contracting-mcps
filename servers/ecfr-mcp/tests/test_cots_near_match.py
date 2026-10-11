"""Near-name COTS lookups retain the complete official FAR definition."""
import asyncio
from pathlib import Path

import pytest
from ecfr_mcp import _definitions
import ecfr_mcp.server as srv


@pytest.mark.parametrize('term', [
    'commercial off-the-shelf',
    'commercial off the shelf item',
    'commercially available off-the-shelf',
    'Define commercially available off the shelf',
    'inherently governmental',
])
def test_near_name_returns_complete_definition_without_false_negative(monkeypatch, term):
    xml = (Path(__file__).parent / 'fixtures/ecfr_xml/t48_2.101.xml').read_text()

    async def text(*args, **kwargs):
        return xml

    async def unexpected_search(*args, **kwargs):
        pytest.fail('A known 2.101 definition must not fall through to elsewhere search')

    monkeypatch.setattr(srv, '_get_xml', text)
    monkeypatch.setattr(srv, '_get_json', unexpected_search)
    canonical = ('inherently governmental function' if term == 'inherently governmental'
                 else 'commercially available off-the-shelf item')
    expected = asyncio.run(srv.find_far_definition(canonical, date='2026-10-07'))
    actual = asyncio.run(srv.find_far_definition(term, date='2026-10-07'))
    assert actual['definition_count'] == 1
    assert actual['matches'][0]['kind'] == 'definition'
    assert actual['matches'][0]['context'] == expected['matches'][0]['context']
    assert 'does not define' not in actual['note']
    assert 'defined_elsewhere' not in actual


def test_ambiguous_prefix_and_opposite_term_are_not_auto_matched():
    paragraphs = ['*Small business concern* means one.',
                  '*Small business subcontractor* means another.',
                  '*Unallowable cost* means a cost that is not allowable.']
    assert not _definitions.find(paragraphs, 'small business')['definitions']
    assert not _definitions.find(paragraphs, 'allowable cost')['definitions']
