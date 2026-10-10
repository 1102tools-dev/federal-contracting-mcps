"""Ordinary source-discovered ocean title must retain its literal colon."""
import asyncio,json
from pathlib import Path
from copy import deepcopy
import pytest
import gsa_calc_mcp.server as s
F=json.loads((Path(__file__).parent/'fixtures/literal_colon_title_source_2026_10.json').read_text())
@pytest.mark.parametrize('before,keyword,count',[
    ('delimiter_exact_before','literal_keyword',1),
    ('graduate_exact_before','graduate_literal_keyword',0),
])
def test_source_discovered_ocean_title_is_literal_exact_population(monkeypatch,before,keyword,count):
    async def source(q):return deepcopy(F[keyword if q.startswith('keyword=') else before]['raw'])
    monkeypatch.setattr(s,'_get',source)
    r=asyncio.run(s.mcp.call_tool('exact_search',F[before]['arguments'])).structured_content
    assert r['_stats']['total_rates']==count
    assert {h['_source']['labor_category'] for h in r['hits']['hits']}==({F[before]['arguments']['value']} if count else set())
    if count:
        assert round(r['_stats']['min_rate'],2)==round(r['_stats']['max_rate'],2)==176.1
    else:
        assert r['_stats']['min_rate'] is None and not r['hits']['hits']


def test_non_delimited_ocean_grade_keeps_original_exact_search(monkeypatch):
    calls=[]
    async def source(q):
        calls.append(q);return deepcopy(F['ordinary_exact_control']['raw'])
    monkeypatch.setattr(s,'_get',source)
    r=asyncio.run(s.mcp.call_tool('exact_search',F['ordinary_exact_control']['arguments'])).structured_content
    assert calls[0].startswith('search=labor_category:Ocean+Engineer+I&')
    assert r['_stats']['total_rates']==1 and round(r['_stats']['min_rate'],2)==72.54
    assert r['hits']['hits'][0]['_source']['labor_category']=='Ocean Engineer I'

@pytest.mark.parametrize("case",["delimiter_exact_before","approximate_population_control"])
def test_wider_source_population_is_not_presented_as_literal_exact(monkeypatch,case):
    async def source(q):return deepcopy(F[case]['raw'])
    monkeypatch.setattr(s,'_get',source)
    with pytest.raises(s.UserInputError,match='cannot verify the complete exact') as e:
        asyncio.run(s.exact_search(**F['delimiter_exact_before']['arguments']))
    assert 'keyword_search' in str(e.value)
    assert 'Do not treat that wider keyword population' in str(e.value)
