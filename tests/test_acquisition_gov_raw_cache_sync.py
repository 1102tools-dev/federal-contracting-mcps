"""Offline checks for isolated cache sync; no live site traffic or PDF parsing."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_acquisition_gov_raw_cache as syncer
loader = syncer.loader
BASE = 'https://www.acquisition.gov/sites/default/files/'


def result(url, body=b'%PDF-small', kind=None):
    return dict(url=url, final_url=url, content_type='text/html' if kind == loader.HTML else 'application/pdf',
                body=body, sha256=hashlib.sha256(body).hexdigest(), fetched_at='2026-10-11T00:00:00Z')


def setup(monkeypatch, path, old, new, changes=None, errors=None):
    monkeypatch.setattr(syncer, 'index_urls', lambda value: set(json.loads(value['body'])))
    monkeypatch.setattr(loader, 'PARTS', [])
    monkeypatch.setattr(loader.constants, 'GUIDANCE_URLS', {})
    cache = loader.Recorder(path)
    cache.save(loader.constants.RFO_INDEX_URL, loader.HTML,
               result(loader.constants.RFO_INDEX_URL, json.dumps(old).encode(), loader.HTML))
    for url in old:
        cache.save(url, loader.PDF, result(url))

    class Fetch:
        requests = downloads = checks = 0
        async def _fetch(self, url, kind):
            self.requests += 1
            if kind == loader.HTML:
                return result(url, json.dumps(new).encode(), kind)
            if url in (errors or {}):
                return dict(url=url, error=errors[url], fetched_at='2026-10-11T01:00:00Z')
            return result(url, (changes or {}).get(url, b'%PDF-small'))
    return cache, Fetch()


def run(cache, fetch):
    return asyncio.run(syncer.sync(cache, fetcher=fetch, log=lambda _: None))


def test_added_changed_removed_and_url_archive(monkeypatch, tmp_path):
    a,b,c,d,e = [BASE + x + '.pdf' for x in 'abcde']
    cache, fetch = setup(monkeypatch, tmp_path, [a,b,c,d], [a,b,e,c], {b:b'%PDF-new'})
    status = run(cache, fetch)
    assert {k:status[k] for k in ['added','changed','removed','errors']} == dict(added=1,changed=1,removed=1,errors=0)
    assert status['index_count'] == status['cached_count'] == 4
    assert cache.load(d,loader.PDF) is None
    archived = loader.Recorder(tmp_path/'_removed').load(d,loader.PDF)
    assert archived['body'] == b'%PDF-small'
    assert cache.load(a,loader.PDF)['body'] == b'%PDF-small' # shared hash remains
    assert json.loads((tmp_path/'_sync-status.json').read_text()) == status
    assert not list(tmp_path.rglob('*.partial'))


def test_shrink_guard_preserves_index_and_pdfs(monkeypatch, tmp_path):
    old = [BASE + str(i)+'.pdf' for i in range(5)]
    cache, fetch = setup(monkeypatch,tmp_path,old,old[:3])
    before = (tmp_path/'manifest.json').read_bytes()
    status = run(cache,fetch)
    assert status['errors'] == 1 and status['removed'] == 0
    assert (tmp_path/'manifest.json').read_bytes() == before
    assert fetch.requests == 1
    assert not (tmp_path/'_removed').exists()


def test_exactly_eighty_percent_allowed_and_shared_removed_hashes(monkeypatch,tmp_path):
    old = [BASE+str(i)+'.pdf' for i in range(10)]
    cache,fetch = setup(monkeypatch,tmp_path,old,old[:8],{u:b'%PDF-active' for u in old[:8]})
    status=run(cache,fetch)
    assert status['errors']==0 and status['removed']==2
    archive=loader.Recorder(tmp_path/'_removed')
    assert all(archive.load(u,loader.PDF)['body']==b'%PDF-small' for u in old[8:])
    assert not (tmp_path/'bodies'/hashlib.sha256(b'%PDF-small').hexdigest()).exists()


def test_failed_fetch_preserves_good_body_and_defers_pruning(monkeypatch,tmp_path):
    old=[BASE+str(i)+'.pdf' for i in range(5)]
    cache,fetch=setup(monkeypatch,tmp_path,old,old[:4],errors={old[0]:'Acquisition.gov returned HTTP 404: absent'})
    status=run(cache,fetch)
    assert status['errors']==1 and status['removed']==0
    assert cache.load(old[0],loader.PDF)['body']==b'%PDF-small'
    assert cache.load(old[4],loader.PDF)['body']==b'%PDF-small'
    # The saved baseline makes a later successful sync archive the disappeared URL.
    fetch._fetch = lambda url,kind: good(url,kind,old[:4])
    status=run(loader.Recorder(tmp_path),fetch)
    assert status['errors']==0 and status['removed']==1


async def good(url,kind,urls):
    return result(url,json.dumps(urls).encode(),kind) if kind==loader.HTML else result(url)


def test_known_unavailable_not_an_operational_error(monkeypatch,tmp_path):
    url=BASE+'known.pdf'
    cache,fetch=setup(monkeypatch,tmp_path,[url],[url],errors={url:'Acquisition.gov returned HTTP 404: absent'})
    cache.save(url,loader.PDF,dict(url=url,error='Acquisition.gov returned HTTP 404: absent',fetched_at='old'))
    status=run(cache,fetch)
    assert status['errors']==0 and status['expected_unavailable']==1
    assert status['cached_count']==0 and status['index_count']==1


def test_archive_hash_collision_keeps_distinct_versions(monkeypatch,tmp_path):
    url=BASE+'gone.pdf'
    cache=loader.Recorder(tmp_path)
    cache.save(url,loader.PDF,result(url,b'%PDF-new'))
    archive=loader.Recorder(tmp_path/'_removed')
    archive.save(url,loader.PDF,result(url,b'%PDF-old'))
    syncer.archive_removed(cache,[url])
    assert loader.Recorder(tmp_path/'_removed').load(url,loader.PDF)['body']==b'%PDF-new'
    assert (archive.path/'bodies'/hashlib.sha256(b'%PDF-old').hexdigest()).read_bytes()==b'%PDF-old'


def test_atomic_body_write_failure_preserves_previous_pdf(monkeypatch,tmp_path):
    url=BASE+'same.pdf'
    cache=loader.Recorder(tmp_path)
    original=result(url)
    cache.save(url,loader.PDF,original)
    real=loader.os.replace
    def failed(source,destination):
        if Path(destination).parent.name=='bodies':
            raise OSError('simulated rename failure')
        return real(source,destination)
    monkeypatch.setattr(loader.os,'replace',failed)
    import pytest
    with pytest.raises(OSError,match='rename failure'):
        cache.save(url,loader.PDF,result(url,b'%PDF-changed'))
    assert cache.load(url,loader.PDF)['body']==original['body']
    assert not list((tmp_path/'bodies').glob('*.partial'))


def test_index_parse_failure_writes_status_without_cache_change(monkeypatch,tmp_path):
    url=BASE+'one.pdf'
    cache,fetch=setup(monkeypatch,tmp_path,[url],[url])
    before=(tmp_path/'manifest.json').read_bytes()
    def bad(value):
        raise ValueError('redesigned index')
    monkeypatch.setattr(syncer,'index_urls',bad)
    status=run(cache,fetch)
    assert status['errors']==1 and status['removed']==0 and status['finished_at']
    assert (tmp_path/'manifest.json').read_bytes()==before
    assert (tmp_path/'_sync-status.json').exists()


def test_limited_acceptance_checks_only_twenty_five_pdfs_and_preserves_index_state_archive(monkeypatch,tmp_path):
    old=[BASE+str(i).zfill(3)+'.pdf' for i in range(30)]
    new=old[:29]+[BASE+'new.pdf']
    cache,fetch=setup(monkeypatch,tmp_path,old,new)
    monkeypatch.setattr(loader,'PARTS',[1,2])
    monkeypatch.setattr(loader.constants,'GUIDANCE_URLS',{'test':BASE+'guidance'})
    syncer.atomic_json(tmp_path/'_sync-state.json',{'urls':old})
    baseline=(tmp_path/'_sync-state.json').read_bytes()
    index=cache.load(loader.constants.RFO_INDEX_URL,loader.HTML)['body']
    status=asyncio.run(syncer.sync(cache,fetcher=fetch,limit=25,log=lambda _:None))
    assert status['mode']=='limited' and status['limit']==25 and status['checked_count']==25
    assert status['index_count']==30 and status['requests']==26 and status['errors']==0
    assert status['removed']==0 and not (tmp_path/'_removed').exists()
    assert (tmp_path/'_sync-state.json').read_bytes()==baseline
    assert cache.load(loader.constants.RFO_INDEX_URL,loader.HTML)['body']==index
    assert cache.load(old[-1],loader.PDF)['body']==b'%PDF-small'


def test_limited_acceptance_still_rejects_shrunken_index(monkeypatch,tmp_path):
    old=[BASE+str(i)+'.pdf' for i in range(30)]
    cache,fetch=setup(monkeypatch,tmp_path,old,old[:20])
    status=asyncio.run(syncer.sync(cache,fetcher=fetch,limit=25,log=lambda _:None))
    assert status['errors']==1 and status['checked_count']==0 and status['requests']==1
    assert status['removed']==0


def test_network_fetches_do_not_hold_mutation_lock(monkeypatch,tmp_path):
    from contextlib import contextmanager
    url=BASE+'one.pdf'
    cache,fetch=setup(monkeypatch,tmp_path,[url],[url])
    locked=False
    commits=0
    @contextmanager
    def tracked(cache):
        nonlocal locked,commits
        assert not locked
        locked=True
        commits+=1
        try:
            yield
        finally:
            locked=False
    original=fetch._fetch
    async def check(url,kind):
        assert not locked
        return await original(url,kind)
    fetch._fetch=check
    monkeypatch.setattr(syncer,'mutation',tracked)
    status=run(cache,fetch)
    assert status['errors']==0 and commits==2 # PDF then archive/index/baseline


def test_limited_status_counts_all_twelve_known_absent_pdfs(monkeypatch, tmp_path):
    urls = [BASE + str(i).zfill(3) + '.pdf' for i in range(40)]
    cache, fetch = setup(monkeypatch, tmp_path, urls, urls)
    for i, url in enumerate(urls[-12:]):
        code = 404 if i % 2 else 410
        cache.save(url, loader.PDF, dict(url=url, error=f'Acquisition.gov returned HTTP {code}: gone', fetched_at='checked'))
    status = asyncio.run(syncer.sync(cache, fetcher=fetch, limit=25, log=lambda _: None))
    assert status['errors'] == 0 and status['checked_unavailable'] == 0
    assert status['expected_unavailable'] == 12 and status['cached_count'] == 28
    assert status['cached_count'] + status['expected_unavailable'] + status['missing_count'] == 40
    assert {item['url'] for item in status['unavailable_details']} == set(urls[-12:])
    assert all(item['status'] in {404, 410} and item['checked_at'] == 'checked' for item in status['unavailable_details'])


def test_missing_and_transient_are_not_expected_unavailable(monkeypatch, tmp_path):
    urls = [BASE + str(i) + '.pdf' for i in range(4)]
    cache, fetch = setup(monkeypatch, tmp_path, urls, urls)
    cache.entries.pop(cache.key(urls[1], loader.PDF))
    cache.save(urls[2], loader.PDF, dict(url=urls[2], error='Acquisition.gov returned HTTP 503: retry', transient=True))
    cache.save(urls[3], loader.PDF, dict(url=urls[3], error='Acquisition.gov returned HTTP 404: unverified', transient=True))
    status = asyncio.run(syncer.sync(cache, fetcher=fetch, limit=1, log=lambda _: None))
    assert status['expected_unavailable'] == 0 and status['missing_count'] == 3
    assert status['cached_count'] == 1
    assert {row['url'] for row in status['missing_details']} == set(urls[1:])


def test_recovered_pdf_clears_recorded_absence(monkeypatch, tmp_path):
    url = BASE + 'recovered.pdf'
    cache, fetch = setup(monkeypatch, tmp_path, [url], [url])
    cache.save(url, loader.PDF, dict(url=url, error='Acquisition.gov returned HTTP 404: gone', fetched_at='old'))
    status = run(cache, fetch)
    assert status['added'] == 1 and status['expected_unavailable'] == 0
    assert status['cached_count'] == 1 and status['unavailable_details'] == []


def test_deployed_commit_marker_validated_and_written_to_status(monkeypatch, tmp_path):
    assert syncer.source_commit(tmp_path) is None
    marker = tmp_path / 'SOURCE_COMMIT'
    for invalid in ['main', 'abc123', 'a' * 40 + '\nextra', '../secret']:
        marker.write_text(invalid)
        assert syncer.source_commit(tmp_path) is None
    revision = '0123456789abcdef' * 2 + '01234567'
    marker.write_text(revision + '\n')
    assert syncer.source_commit(tmp_path) == revision
    monkeypatch.setattr(syncer, 'source_commit', lambda: revision)
    url = BASE + 'one.pdf'
    cache, fetch = setup(monkeypatch, tmp_path / 'cache', [url], [url])
    status = run(cache, fetch)
    assert status['source_commit'] == revision
    assert json.loads((cache.path / '_sync-status.json').read_text())['source_commit'] == revision


def test_failed_index_refresh_keeps_previous_count_and_accounting(monkeypatch, tmp_path):
    urls = [BASE + str(i) + '.pdf' for i in range(3)]
    cache, fetch = setup(monkeypatch, tmp_path, urls, urls)
    cache.save(urls[-1], loader.PDF, dict(url=urls[-1], error='Acquisition.gov returned HTTP 404: gone', fetched_at='old'))
    async def failed(url, kind):
        fetch.requests += 1
        return dict(url=url, error='Acquisition.gov returned HTTP 503: retry', transient=True)
    fetch._fetch = failed
    status = run(cache, fetch)
    assert status['errors'] == 1 and status['index_count'] == 3
    assert status['cached_count'] == 2 and status['expected_unavailable'] == 1
    assert status['missing_count'] == 0 and status['removed'] == 0
