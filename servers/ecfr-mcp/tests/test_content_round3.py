"""Source-backed Section508 timeline and chronological pagination."""
import json
from pathlib import Path
import pytest
from ecfr_mcp import server as srv

@pytest.mark.asyncio
async def test_section508_history_chronology_and_followup_pages(monkeypatch):
    source=json.loads((Path(__file__).parent/'fixtures/history_508_round3.json').read_text())
    async def versions(*args,**kwargs):
        return source['content_versions'],source['meta'],True
    monkeypatch.setattr(srv,'_all_versions',versions)
    result=await srv.get_version_history(title_number=36,section='1194.1',per_page=20)
    expected=['2016-12-13','2017-01-18','2017-03-03','2017-03-21']
    assert [v['date'] for v in result['content_versions']]==expected
    pages=[await srv.get_version_history(title_number=36,section='1194.1',per_page=2,page=p) for p in [1,2]]
    assert [v['date'] for page in pages for v in page['content_versions']]==expected
    assert all(page['total_count']==4 and page['total_pages']==2 for page in pages)
    assert 'page=2' in pages[0]['note']


@pytest.mark.asyncio
async def test_compare_source_backed_2016_history_snapshot(monkeypatch):
    fixtures=Path(__file__).parent/'fixtures'
    requested=[]
    async def latest(*args):return '2026-10-07'
    async def text(path,params):
        day=path.split('/')[5]
        requested.append(day)
        return (fixtures/f'section508-{day}.xml').read_text()
    monkeypatch.setattr(srv,'_resolve_date',latest)
    monkeypatch.setattr(srv,'_get_xml',text)
    result=await srv.compare_versions(title_number=36,section_id='1194.1',date_before='2016-12-13',date_after='2017-01-18',changes_only=True)
    assert requested==['2016-12-13','2017-01-18']
    assert result['identical'] is False
    assert any('82 FR 5832' in str(c) for c in result['changes'])
