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
