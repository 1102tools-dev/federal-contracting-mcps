"""Source-derived ordinary grade-specific pricing must not pool senior grades."""
import asyncio,json
from pathlib import Path
from copy import deepcopy
import pytest
import gsa_calc_mcp.server as s
F=json.loads((Path(__file__).parent/'fixtures/nurse_grade_source_2026_10.json').read_text())
@pytest.mark.parametrize('case',['mixed_grade','no_exact_grade'])
def test_discovered_nurse_grade_has_no_verdict_on_other_grades(monkeypatch,case):
    async def source(q):return deepcopy(F[case]['raw'])
    monkeypatch.setattr(s,'_get',source)
    args=F[case]['arguments'];r=asyncio.run(s.mcp.call_tool('price_reasonableness_check',args)).structured_content
    assert r['status']=='MIXED_LABOR_TITLES'
    assert all(x is None for x in r['analysis'].values())
    assert r['total_rates']==(24 if case=='mixed_grade' else 15)
    assert r['population_scope']['exact_title_rate_count']==(3 if case=='mixed_grade' else 0)
    assert r['population_scope']['exact_title_population_verified'] is False
    assert 'exact_search' in r['message']
    assert ('3 exact' if case=='mixed_grade' else 'No exact') in r['message']

def test_exact_source_nurse_grade_keeps_small_sample_limit(monkeypatch):
    async def source(q):return deepcopy(F['exact_grade']['raw'])
    monkeypatch.setattr(s,'_get',source)
    r=asyncio.run(s.mcp.call_tool('price_reasonableness_check',dict(labor_category='Registered Nurse I',education_level='BA',experience_min=1,proposed_rate=60))).structured_content
    assert r['status']=='LOW_SAMPLE' and r['total_rates']==3
    assert r['analysis']['iqr_position'] is None
