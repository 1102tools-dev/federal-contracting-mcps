"""Offline cases for the hosted Acquisition.gov D1 loader (no Cloudflare, no network).

Runs scripts/load_acquisition_gov.py against the small recording
deploy/acquisition-gov/test/fixture_recording.py writes. Needs the
acquisition-gov-mcp package's dependencies (the loader parses with it):

    uv run --frozen --python 3.12 --project servers/acquisition-gov-mcp --with pytest pytest -q tests/test_acquisition_gov_loader.py
"""
import asyncio
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

    def __init__(self, recording, overrides=None):
        super().__init__(retry_pause=0, log=lambda message: None)
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
