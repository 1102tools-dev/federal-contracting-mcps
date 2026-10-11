"""Offline cases for the hosted Acquisition.gov D1 loader (no Cloudflare, no network).

Runs scripts/load_acquisition_gov.py against the small recording
deploy/acquisition-gov/test/fixture_recording.py writes. Needs the
acquisition-gov-mcp package's dependencies (the loader parses with it):

    uv run --frozen --python 3.12 --project servers/acquisition-gov-mcp --with pytest pytest -q tests/test_acquisition_gov_loader.py
"""
import asyncio
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


loader = module("load_acquisition_gov", ROOT / "scripts/load_acquisition_gov.py")
fixture = module("fixture_recording", ROOT / "deploy/acquisition-gov/test/fixture_recording.py")
GSA = f"{fixture.UPLOADS}/GSA_RFO_Deviation_Part-10.pdf"
NASA = f"{fixture.UPLOADS}/NASA_RFO_Deviation_Part-10.pdf"


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    path = tmp_path_factory.mktemp("rec")
    fixture.write(path)
    return path


class Fetcher(loader.Fetcher):
    """The loader's own fetcher, with the package's _fetch_bytes answered from
    the recording as the site would: recorded errors raise, and overrides map a
    URL to an exception or to replacement bytes. Records what was requested."""

    def __init__(self, recording, overrides=None, **kwargs):
        super().__init__(retry_pause=0, log=lambda message: None, **kwargs)
        self.recording = loader.Recorder(recording)
        self.overrides = overrides or {}
        self.asked = []

    async def _fetch(self, url, kind):
        async def fetch_bytes(url, *, allowed_types, max_bytes):
            self.asked.append(url)
            override = self.overrides.get(url)
            if isinstance(override, Exception):
                raise override
            entry = self.recording.load(url, (allowed_types, max_bytes))
            if "error" in entry:
                raise RuntimeError(entry["error"])
            return (override if override is not None else entry["body"]), entry["content_type"], entry["final_url"]

        real, loader.server._fetch_bytes = loader.server._fetch_bytes, fetch_bytes
        try:
            return await super()._fetch(url, kind)
        finally:
            loader.server._fetch_bytes = real

    async def _download(self, url, kind, cached=None):
        # Fixture transport is offline; production conditional transport is
        # exercised separately below with real response status and headers.
        self.requests += 1
        body, content_type, final_url = await loader.server._fetch_bytes(url, allowed_types=kind[0], max_bytes=kind[1])
        self.downloads += 1
        self.bytes += len(body)
        return {'url': url, 'final_url': final_url, 'content_type': content_type,
                'body': body, 'sha256': hashlib.sha256(body).hexdigest(), 'fetched_at': loader.server._now()}


def run(db, fetcher, **options):
    return asyncio.run(loader.Loader(db, fetcher, log=lambda message: None, **options).run())


def rows(path, sql, *params):
    db = sqlite3.connect(path)
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def meta(path):
    return dict(rows(path, "SELECT key, value FROM meta"))


def test_first_load_then_reuse_and_cleanup(tmp_path, recording):
    path = tmp_path / "d1.sqlite"
    first = run(loader.LocalD1(path), Fetcher(recording))
    assert meta(path) == {"current": "1"}
    assert first["pdfs"] == 2 and first["fetch_errors"] == 51  # 51 parts are HTTP 404 in the fixture
    assert first["parsed"] == first["fetched"] - first["fetch_errors"] == 8
    assert rows(path, "SELECT COUNT(*) FROM sources WHERE snapshot = 1") == [(1 + 53 + 3 + 2,)]
    assert rows(path, "SELECT COUNT(*) FROM index_deviations") == [(4,)]
    # The GSA PDF is listed for parts 10 and 12 (and twice for 10); stored once.
    assert rows(path, "SELECT COUNT(DISTINCT url) FROM index_deviations") == [(2,)]

    second = run(loader.LocalD1(path), Fetcher(recording), full=True)
    assert (second["parsed"], second["reused"]) == (0, 8)
    assert meta(path) == {"current": "2", "previous": "1"}
    docs = rows(path, "SELECT COUNT(*) FROM docs")

    run(loader.LocalD1(path), Fetcher(recording), full=True)
    assert meta(path) == {"current": "3", "previous": "2"}
    assert rows(path, "SELECT DISTINCT snapshot FROM sources ORDER BY snapshot") == [(2,), (3,)]
    assert rows(path, "SELECT COUNT(*) FROM docs") == docs, "shared content is kept, not duplicated"


def test_incremental_run_carries_unchecked_pdfs_forward(tmp_path, recording):
    path = tmp_path / "d1.sqlite"
    run(loader.LocalD1(path), Fetcher(recording))
    before = dict(rows(path, "SELECT key, retrieved_at FROM sources WHERE snapshot = 1 AND key LIKE 'pdf:%'"))
    fetcher = Fetcher(recording)
    stats = run(loader.LocalD1(path), fetcher, revalidate=0)
    assert GSA not in fetcher.asked and NASA not in fetcher.asked
    assert stats["carried_forward"] == 2
    after = dict(rows(path, "SELECT key, retrieved_at FROM sources WHERE snapshot = 2 AND key LIKE 'pdf:%'"))
    assert after == before, "carried PDFs keep the fetch time of the copy they serve"

    fetcher = Fetcher(recording)
    stats = run(loader.LocalD1(path), fetcher, revalidate=1)
    assert fetcher.asked.count(GSA) + fetcher.asked.count(NASA) == 1, "only the least recently checked PDF"
    assert stats["carried_forward"] == 1


def test_transient_failure_keeps_the_last_good_copy(tmp_path, recording):
    path = tmp_path / "d1.sqlite"
    run(loader.LocalD1(path), Fetcher(recording))
    good = rows(path, "SELECT doc, error FROM sources WHERE snapshot = 1 AND key = ?", f"pdf:{NASA}")
    fetcher = Fetcher(recording, {NASA: RuntimeError("Acquisition.gov returned HTTP 503: busy")})
    stats = run(loader.LocalD1(path), fetcher, full=True)
    assert fetcher.asked.count(NASA) == 2, "a transient failure is retried once"
    assert stats["transient_kept"] == 1
    assert rows(path, "SELECT doc, error FROM sources WHERE snapshot = 2 AND key = ?", f"pdf:{NASA}") == good

    # A lasting failure (HTTP 404) replaces it: the live tool would report that error.
    run(loader.LocalD1(path), Fetcher(recording, {NASA: RuntimeError("Acquisition.gov returned HTTP 404: gone")}), full=True)
    assert rows(path, "SELECT doc, error FROM sources WHERE snapshot = 3 AND key = ?", f"pdf:{NASA}") == [(None, "Acquisition.gov returned HTTP 404: gone")]


def test_unusable_index_or_rate_limit_stops_without_switching(tmp_path, recording):
    path = tmp_path / "d1.sqlite"
    run(loader.LocalD1(path), Fetcher(recording))
    with pytest.raises(loader.Abort, match="Index unavailable"):
        run(loader.LocalD1(path), Fetcher(recording, {fixture.INDEX: RuntimeError("Acquisition.gov returned HTTP 500: x")}))
    shrunk = (fixture.FIXTURES / "rfo-index.html").read_bytes().replace(b"NASA_RFO_Deviation_Part-10.pdf", b"GSA_RFO_Deviation_Part-10.pdf")
    with pytest.raises(loader.Abort, match="deviation PDFs but the current snapshot has 2"):
        run(loader.LocalD1(path), Fetcher(recording, {fixture.INDEX: shrunk}), full=True)
    with pytest.raises(loader.Abort, match="rate limited"):
        run(loader.LocalD1(path), Fetcher(recording, {NASA: RuntimeError("Acquisition.gov rate limited the request (HTTP 429).")}), full=True)
    assert meta(path)["current"] == "1"
    assert rows(path, "SELECT COUNT(*) FROM sources WHERE snapshot = 1") == [(59,)]


def test_an_interrupted_run_resumes_its_staged_snapshot(tmp_path, recording):
    path = tmp_path / "d1.sqlite"
    run(loader.LocalD1(path), Fetcher(recording))
    with pytest.raises(loader.Abort):
        run(loader.LocalD1(path), Fetcher(recording, {NASA: RuntimeError("Acquisition.gov returned HTTP 403: blocked")}), full=True)
    assert meta(path) == {"current": "1", "staging": "2"}
    fetcher = Fetcher(recording)
    run(loader.LocalD1(path), fetcher, full=True)
    assert meta(path) == {"current": "2", "previous": "1"}
    assert GSA not in fetcher.asked, "a PDF the interrupted run staged is not fetched again"
    assert NASA in fetcher.asked


def test_statements_fit_d1_limits(tmp_path, recording):
    statements = []

    class Capture(loader.LocalD1):
        def execute(self, batch):
            statements.extend(batch)
            super().execute(batch)

    run(Capture(tmp_path / "d1.sqlite"), Fetcher(recording))
    assert any("INSERT OR REPLACE INTO pages" in s for s in statements)
    for statement in statements:
        assert len(statement.encode("utf-8")) < 100_000
    # The generated PDF's page over 200,000 characters is one long applicability line.
    assert rows(tmp_path / "d1.sqlite", "SELECT applicability, over_cap FROM pages WHERE page = 35 AND seq = 0") == [("[[0, 200000]]", 1)]


def test_split_text_counts_code_points_and_fits_statements():
    text = "a'\U0001F600" * 40_000
    pieces = loader.split_text(text)
    assert "".join(piece for _, _, piece in pieces) == text
    assert [start for start, _, _ in pieces] == [sum(length for _, length, _ in pieces[:i]) for i in range(len(pieces))]
    for _, _, piece in pieces:
        assert len(loader.quote(piece).encode("utf-8")) < loader.STATEMENT_BYTES
    assert loader.split_text("") == [(0, 0, "")]
    assert loader.quote("a\x00b'") == "('a' || char(0) || 'b''')"


def test_applicability_offsets_match_the_package():
    text = "Intro\r\n4. APPLICABILITY: all\nNot this\x0bThis applies to everyone end"
    found = loader.applicability(3, text)
    lines = [" ".join(text[a:b].split()) for a, b in found]
    expected = loader._pdf._extract_document_fields([(3, text)])["applicability_text"]
    assert "\n".join(f"Page 3: {line}" for line in lines) == expected


def test_parser_version_change_reparses_identical_sources_on_full_reload(tmp_path, recording, monkeypatch):
    """A patch parser must not reuse an old PDF's derived date matches."""
    path = tmp_path / "d1.sqlite"
    monkeypatch.setattr(loader, "PARSER_VERSION", "1.0.9+3")
    run(loader.LocalD1(path), Fetcher(recording), full=True)
    old = dict(rows(path, "SELECT key, doc FROM sources WHERE snapshot = 1 AND error IS NULL"))
    monkeypatch.setattr(loader, "PARSER_VERSION", "1.0.10+3")
    stats = run(loader.LocalD1(path), Fetcher(recording), full=True)
    new = dict(rows(path, "SELECT key, doc FROM sources WHERE snapshot = 2 AND error IS NULL"))
    assert old.keys() == new.keys()
    assert all(new[key] != old[key] for key in old)
    assert (stats["parsed"], stats["reused"], stats["carried_forward"]) == (8, 0, 0)


def test_parser_version_change_incremental_reload_retains_unchecked_pdf(tmp_path, recording, monkeypatch):
    """Document why release acceptance requires a full refresh, not the daily batch."""
    path = tmp_path / "d1.sqlite"
    monkeypatch.setattr(loader, "PARSER_VERSION", "1.0.9+3")
    run(loader.LocalD1(path), Fetcher(recording), full=True)
    old = dict(rows(path, "SELECT key, doc FROM sources WHERE snapshot = 1 AND key LIKE 'pdf:%'"))
    monkeypatch.setattr(loader, "PARSER_VERSION", "1.0.10+3")
    stats = run(loader.LocalD1(path), Fetcher(recording), revalidate=0)
    new = dict(rows(path, "SELECT key, doc FROM sources WHERE snapshot = 2 AND key LIKE 'pdf:%'"))
    assert new == old
    assert stats["carried_forward"] == 2


def test_new_parser_does_not_resume_old_staged_pdf(tmp_path, recording, monkeypatch):
    path = tmp_path / 'd1.sqlite'
    monkeypatch.setattr(loader, 'PARSER_VERSION', '1.0.10+3')
    run(loader.LocalD1(path), Fetcher(recording), full=True)
    with pytest.raises(loader.Abort):
        run(loader.LocalD1(path), Fetcher(recording, {NASA: RuntimeError('Acquisition.gov returned HTTP 403: blocked')}), full=True)
    old = rows(path, 'SELECT doc FROM sources WHERE snapshot = 2 AND key = ?', f'pdf:{GSA}')[0][0]
    assert meta(path) == {'current': '1', 'staging': '2'}
    monkeypatch.setattr(loader, 'PARSER_VERSION', '1.0.10+4')
    fetcher = Fetcher(recording)
    stats = run(loader.LocalD1(path), fetcher, full=True)
    assert GSA in fetcher.asked, 'old derived data must not pass the recent-stage done check'
    assert NASA in fetcher.asked
    assert meta(path) == {'current': '2', 'previous': '1'}
    new = rows(path, 'SELECT doc, content_sha256 FROM sources WHERE snapshot = 2 AND key = ?', f'pdf:{GSA}')[0]
    assert new[0] != old and new[0] == loader.doc_id('pdf', new[1])
    assert stats['carried_forward'] == 0


def test_staged_fetch_error_is_retried_on_resume(tmp_path, recording):
    path = tmp_path / 'd1.sqlite'
    run(loader.LocalD1(path), Fetcher(recording), full=True)
    db = loader.LocalD1(path)
    loader.Loader(db, Fetcher(recording), log=lambda _: None).setup()
    db.execute([f"INSERT OR REPLACE INTO sources SELECT 2,key,url,final_url,source_id,retrieved_at,content_sha256,'HTTP 404',NULL FROM sources WHERE snapshot=1 AND key={loader.quote('pdf:'+NASA)};"])
    fetcher = Fetcher(recording)
    run(db, fetcher, revalidate=0)
    assert NASA in fetcher.asked
    assert rows(path, 'SELECT error FROM sources WHERE snapshot=2 AND key=?', f'pdf:{NASA}') == [(None,)]


@pytest.fixture
def compact_parts(monkeypatch):
    # Only the two successful model pages from this saved fixture; no live site.
    monkeypatch.setattr(loader, 'PARTS', (10, 12))


def test_raw_cache_preserves_pdf_bytes_url_and_hash(tmp_path, recording, compact_parts):
    """The durable cache must survive a fresh process, including guidance PDFs."""
    path = tmp_path / 'd1.sqlite'
    cache_path = tmp_path / 'raw-cache'
    run(loader.LocalD1(path), Fetcher(recording, raw_cache=loader.Recorder(cache_path)))
    cache = loader.Recorder(cache_path)
    saved = loader.Recorder(recording)
    pdf_urls = [GSA, NASA, *[url for url in loader.constants.GUIDANCE_URLS.values() if url.endswith('.pdf')]]
    for url in pdf_urls:
        expected = saved.load(url, loader.PDF)
        actual = cache.load(url, loader.PDF)
        assert actual['url'] == url
        assert actual['body'] == expected['body']
        assert actual['sha256'] == hashlib.sha256(expected['body']).hexdigest()
    manifest = json.loads((cache_path / 'manifest.json').read_text())
    assert manifest[cache.key(GSA, loader.PDF)]['sha256'] == cache.load(GSA, loader.PDF)['sha256']
    assert (cache_path / 'bodies' / cache.load(GSA, loader.PDF)['sha256']).read_bytes() == cache.load(GSA, loader.PDF)['body']


def test_reparse_forces_extraction_without_network_or_mutating_live_docs(tmp_path, recording, monkeypatch, compact_parts):
    path = tmp_path / 'd1.sqlite'
    cache_path = tmp_path / 'raw-cache'
    run(loader.LocalD1(path), Fetcher(recording, raw_cache=loader.Recorder(cache_path)))
    original_sources = rows(path, 'SELECT key, doc FROM sources WHERE snapshot=1 AND error IS NULL ORDER BY key')
    original_pages = rows(path, 'SELECT * FROM pages ORDER BY doc,page,seq')
    parsed_kinds = []
    real_parse = loader.parse

    async def counted_parse(kind, body, **inputs):
        parsed_kinds.append(kind)
        return await real_parse(kind, body, **inputs)

    class Offline(loader.Fetcher):
        async def _fetch(self, *args, **kwargs):
            raise AssertionError('reparse attempted a network fetch')

        async def _download(self, *args, **kwargs):
            raise AssertionError('reparse attempted a download')

    monkeypatch.setattr(loader, 'parse', counted_parse)
    stats = run(loader.LocalD1(path), Offline(raw_cache=loader.Recorder(cache_path)), reparse=True)
    reparsed_sources = rows(path, 'SELECT key, doc FROM sources WHERE snapshot=2 AND error IS NULL ORDER BY key')
    assert [key for key, _ in reparsed_sources] == [key for key, _ in original_sources]
    assert all(old_doc != new_doc for (_, old_doc), (_, new_doc) in zip(original_sources, reparsed_sources))
    assert len(parsed_kinds) == 8 and 'pdf' in parsed_kinds and 'guidance_pdf' in parsed_kinds
    assert stats['requests'] == stats['downloads'] == 0
    assert rows(path, 'SELECT key, doc FROM sources WHERE snapshot=1 AND error IS NULL ORDER BY key') == original_sources
    old_docs = {doc for _, doc in original_sources}
    assert [row for row in rows(path, 'SELECT * FROM pages ORDER BY doc,page,seq') if row[0] in old_docs] == original_pages


@pytest.mark.parametrize('corrupt', [False, True], ids=['missing', 'corrupt'])
def test_reparse_bad_raw_cache_aborts_without_download_or_switch(tmp_path, recording, corrupt, compact_parts):
    path = tmp_path / 'd1.sqlite'
    cache_path = tmp_path / 'raw-cache'
    run(loader.LocalD1(path), Fetcher(recording, raw_cache=loader.Recorder(cache_path)))
    sha = loader.Recorder(cache_path).load(NASA, loader.PDF)['sha256']
    body_path = cache_path / 'bodies' / sha
    if corrupt:
        body_path.write_bytes(b'broken PDF')
    else:
        body_path.unlink()

    class Offline(loader.Fetcher):
        async def _fetch(self, *args, **kwargs):
            raise AssertionError('missing or corrupt cache must never fall back to network')

    with pytest.raises(loader.Abort):
        run(loader.LocalD1(path), Offline(raw_cache=loader.Recorder(cache_path)), reparse=True)
    assert meta(path)['current'] == '1'


def test_conditional_pdf_reload_downloads_only_new_or_changed_and_keeps_pacing(tmp_path, monkeypatch):
    """Real fetch logic and pacer, with a fake origin and clock instead of waits."""
    new_url = f'{fixture.UPLOADS}/NEW_RFO_Deviation_Part-10.pdf'
    bodies = {GSA: fixture.pdf([['Original GSA']]), NASA: fixture.pdf([['Original NASA']])}
    versions = {GSA: 'gsa-1', NASA: 'nasa-1'}
    now = [1_800_000_000.0]
    requests = []

    async def sleep(seconds):
        now[0] += seconds

    pacer = loader.server.FederalApiPacer(
        bucket='www.acquisition.gov', default_interval=3.0,
        environment={'FEDERAL_API_MIN_INTERVAL_SECONDS': '3'},
        pacing_dir=tmp_path / 'pacing', clock=lambda: now[0], sleep=sleep,
    )
    monkeypatch.setattr(loader.server, '_pacer', pacer)
    monkeypatch.setattr(loader.shutil, 'which', lambda executable: '/fixture/curl')

    async def origin(url, *, max_bytes, headers):
        requests.append((url, now[0], dict(headers)))
        etag = f'"{versions[url]}"'
        response_headers = {'etag': etag, 'last-modified': 'Wed, 01 Oct 2025 12:00:00 GMT'}
        if headers.get('If-None-Match') == etag:
            return loader.httpx.Response(304, headers=response_headers), b''
        response_headers['content-type'] = 'application/pdf'
        assert len(bodies[url]) < max_bytes
        return loader.httpx.Response(200, headers=response_headers), bodies[url]

    monkeypatch.setattr(loader, '_conditional_curl_once', origin)
    cache_path = tmp_path / 'raw-cache'

    async def reload(urls):
        fetcher = loader.Fetcher(raw_cache=loader.Recorder(cache_path), retry_pause=0, log=lambda _: None)
        results = {url: await fetcher.fetch(url, loader.PDF) for url in urls}
        return fetcher, results

    first, _ = asyncio.run(reload([GSA, NASA]))
    assert (first.downloads, first.checks) == (2, 0)
    unchanged, _ = asyncio.run(reload([GSA, NASA]))
    assert (unchanged.downloads, unchanged.checks, unchanged.bytes) == (0, 2, 0)
    bodies[NASA] = fixture.pdf([['Changed NASA']])
    versions[NASA] = 'nasa-2'
    bodies[new_url] = fixture.pdf([['New agency']])
    versions[new_url] = 'new-1'
    changed, results = asyncio.run(reload([GSA, NASA, new_url]))
    assert (changed.downloads, changed.checks) == (2, 1)
    assert results[NASA]['body'] == bodies[NASA]
    assert results[new_url]['body'] == bodies[new_url]
    assert results[NASA]['sha256'] == hashlib.sha256(bodies[NASA]).hexdigest()
    assert all(later[1] - earlier[1] >= 3 for earlier, later in zip(requests, requests[1:]))
    assert requests[2][2] == {'If-None-Match': '"gsa-1"', 'If-Modified-Since': 'Wed, 01 Oct 2025 12:00:00 GMT'}
    assert requests[-1][2] == {}, 'a new URL must not inherit another PDF’s validators'


@pytest.mark.parametrize('transient_error', [False, True], ids=['unposted-404', 'incomplete-503'])
def test_reparse_preserves_unposted_resources_but_aborts_on_transient_cache(tmp_path, recording, monkeypatch, transient_error):
    """Unposted FAR parts have truthful error rows and no PDF/body to extract."""
    monkeypatch.setattr(loader, 'PARTS', (10, 12, 20, 21))
    path = tmp_path / 'd1.sqlite'
    cache_path = tmp_path / 'raw-cache'
    run(loader.LocalD1(path), Fetcher(recording, raw_cache=loader.Recorder(cache_path)))
    unposted = rows(path, "SELECT key,error,doc FROM sources WHERE snapshot=1 AND key IN ('part:20','part:21') ORDER BY key")
    assert len(unposted) == 2 and all('HTTP 404' in error and doc is None for _, error, doc in unposted)
    cache = loader.Recorder(cache_path)
    if transient_error:
        url = f'{loader.constants.RFO_INDEX_URL}/far-overhaul-part-20'
        cache.save(url, loader.HTML, {'url': url, 'error': 'Acquisition.gov returned HTTP 503: busy',
                                    'transient': True, 'fetched_at': loader.server._now()})

    class Offline(loader.Fetcher):
        async def _fetch(self, *args, **kwargs):
            raise AssertionError('offline cached error attempted a fetch')

    if transient_error:
        with pytest.raises(loader.Abort, match='no complete raw cached copy'):
            run(loader.LocalD1(path), Offline(raw_cache=cache), reparse=True)
        assert meta(path)['current'] == '1'
    else:
        stats = run(loader.LocalD1(path), Offline(raw_cache=cache), reparse=True)
        assert stats['requests'] == stats['downloads'] == 0
        assert stats['fetch_errors'] == 2 and stats['parsed'] == 8
        assert rows(path, "SELECT key,error,doc FROM sources WHERE snapshot=2 AND key IN ('part:20','part:21') ORDER BY key") == unposted
