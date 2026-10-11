"""Selected nightly PDF rechecks, using the existing tiny offline recording."""
import hashlib

import pytest

from test_acquisition_gov_loader import Fetcher, GSA, NASA, fixture, loader, meta, rows, run


@pytest.fixture(scope='module')
def small_recording(tmp_path_factory):
    path = tmp_path_factory.mktemp('forced-recheck-recording')
    fixture.write(path)
    recording = loader.Recorder(path)
    original = recording.load(GSA, loader.PDF)
    body = fixture.pdf([['Issued: October 1, 2026', 'Original GSA deviation.']])
    recording.save(GSA, loader.PDF, dict(original, body=body, sha256=hashlib.sha256(body).hexdigest()))
    return path


@pytest.fixture(autouse=True)
def compact_parts(monkeypatch):
    monkeypatch.setattr(loader, 'PARTS', (10, 12))


def test_selected_staged_pdf_is_refetched_and_reparsed_with_zero_ordinary_rechecks(tmp_path, small_recording):
    path = tmp_path / 'snapshot.sqlite'
    run(loader.LocalD1(path), Fetcher(small_recording))
    with pytest.raises(loader.Abort):
        run(loader.LocalD1(path), Fetcher(small_recording, {NASA: RuntimeError('Acquisition.gov returned HTTP 403: blocked')}), full=True)
    assert meta(path) == {'current': '1', 'staging': '2'}
    old_doc = rows(path, 'SELECT doc FROM sources WHERE snapshot=2 AND key=?', f'pdf:{GSA}')[0][0]
    revised = fixture.pdf([['Issued: October 11, 2026', 'Forced revised GSA deviation.']])
    fetcher = Fetcher(small_recording, {GSA: revised})
    stats = run(loader.LocalD1(path), fetcher, revalidate=0, revalidate_urls=(GSA,))
    assert fetcher.asked.count(GSA) == 1
    assert NASA not in fetcher.asked, 'an unselected existing PDF stays in the ordinary zero-recheck batch'
    assert stats['forced_rechecks'] == 1 and stats['parsed'] == 1
    new_doc = rows(path, 'SELECT doc FROM sources WHERE snapshot=2 AND key=?', f'pdf:{GSA}')[0][0]
    assert new_doc != old_doc
    assert 'Forced revised GSA deviation.' in rows(path, 'SELECT body FROM pages WHERE doc=?', new_doc)[0][0]
    assert meta(path) == {'current': '2', 'previous': '1'}


def test_forced_rechecks_precede_ordinary_batch_without_duplicate_downloads(tmp_path, small_recording):
    path = tmp_path / 'snapshot.sqlite'
    run(loader.LocalD1(path), Fetcher(small_recording))
    fetcher = Fetcher(small_recording)
    stats = run(loader.LocalD1(path), fetcher, revalidate=1, revalidate_urls=(GSA, GSA))
    selected = [url for url in fetcher.asked if url in (GSA, NASA)]
    assert selected == [GSA, NASA]
    assert stats['forced_rechecks'] == 1


def test_unknown_forced_url_aborts_before_pdf_fetch_or_snapshot_switch(tmp_path, small_recording):
    path = tmp_path / 'snapshot.sqlite'
    run(loader.LocalD1(path), Fetcher(small_recording))
    fetcher = Fetcher(small_recording)
    unknown = f'{fixture.UPLOADS}/Not-in-the-current-index.pdf'
    with pytest.raises(loader.Abort, match='not in the current official index'):
        run(loader.LocalD1(path), fetcher, revalidate=0, revalidate_urls=(unknown,))
    assert meta(path)['current'] == '1'
    assert not any(url.endswith('.pdf') for url in fetcher.asked)
    assert rows(path, 'SELECT COUNT(*) FROM sources WHERE snapshot=1 AND key LIKE ?', 'pdf:%') == [(2,)]
