"""Offline cases for the hosted BLS OEWS loader (no Cloudflare calls, no network)."""
import gzip
import hashlib
import importlib.util
import io
import json
import sqlite3
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bls_loader", ROOT / "scripts/load_bls_oews.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

DATATYPES = [f"{i:02d}" for i in range(1, 18)]
FOOTNOTES = {"4": "Wages for some occupations ...", "5": "This wage is equal to or greater than $115.00 per hour.", "8": "Estimate not released."}


def cell(n, prefix="OEUM"):
    key = f"{prefix}{n:07d}000000151252"
    values = [str(1000 + n), "1.5", "-", str(n * 7), *["12.34"] * 11, None, None]
    notes = [None, None, "4", *[None] * 14]
    return key, values, notes


def make_bundle(directory, cells=300, release="2025A01", year="2025", tamper=None):
    """A tiny bundle shaped like the package's data/: manifest.json plus a gzipped database."""
    directory.mkdir(parents=True, exist_ok=True)
    db_path = directory / "oews.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript(f"""
        CREATE TABLE cell (key TEXT PRIMARY KEY, {", ".join(f"v{d} TEXT" for d in DATATYPES)},
                           {", ".join(f"f{d} TEXT" for d in DATATYPES)}) WITHOUT ROWID;
        CREATE TABLE area (area_code TEXT PRIMARY KEY, areatype_code TEXT, state_code TEXT, area_name TEXT) WITHOUT ROWID;
        CREATE TABLE occupation (occupation_code TEXT PRIMARY KEY, occupation_name TEXT, display_level INTEGER) WITHOUT ROWID;
        CREATE TABLE footnote (footnote_code TEXT PRIMARY KEY, footnote_text TEXT) WITHOUT ROWID;
        CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
    """)
    for n in range(cells):
        key, values, notes = cell(n)
        con.execute(f"INSERT INTO cell VALUES ({', '.join('?' * 35)})", (key, *values, *notes))
    con.executemany("INSERT INTO area VALUES (?, 'M', '00', ?)", [("0047900", "Washington-Arlington-Alexandria, DC-VA-MD-WV"),
                                                                   ("0000000", "National")])
    con.executemany("INSERT INTO occupation VALUES (?, ?, 3)", [("151252", "Software Developers"),
                                                                ("533032", "Heavy and Tractor-Trailer Truck Drivers' Helpers")])
    con.executemany("INSERT INTO footnote VALUES (?, ?)", FOOTNOTES.items())
    con.execute("INSERT INTO meta VALUES ('release_code', ?)", (release,))
    con.commit()
    con.close()
    raw = db_path.read_bytes()
    db_path.unlink()
    (directory / "oews.sqlite.gz").write_bytes(gzip.compress(raw))
    manifest = {
        "file": "oews.sqlite.gz", "database_sha256": hashlib.sha256(raw).hexdigest(), "database_bytes": len(raw),
        "data_year": year, "release": {"code": release, "description": f"May {year}", "period": "A01", "year": year},
        "retrieved": "2026-09-26", "counts": {"cells": cells, "occupations": 2, "areas": 2},
        "sources": {"oe.data.0.Current": {"url": "https://download.bls.gov/pub/time.series/oe/oe.data.0.Current",
                                          "sha256": "0" * 64, "last_modified": "2026-05-15"}},
    }
    if tamper:
        tamper(manifest)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest


class Recording(loader.LocalD1):
    """LocalD1 that records every statement and can fail after a number of them."""

    def __init__(self, path, fail_after=None):
        super().__init__(path)
        self.sql = []
        self.fail_after = fail_after

    def query(self, sql):
        if self.fail_after is not None and len(self.sql) >= self.fail_after:
            raise RuntimeError("connection lost")
        self.sql.append(sql)
        return super().query(sql)


def quiet(message):
    pass


def rows(path, sql):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_first_load_copies_the_release_and_activates_it(tmp_path):
    manifest = make_bundle(tmp_path / "data")
    db = Recording(tmp_path / "d1.sqlite")
    result = loader.load(db, tmp_path / "data", log=quiet)
    assert result["status"] == "loaded" and result["version"] == 1 and result["previous_version"] is None
    assert result["rows"] == {"cell": 300, "occupation": 2, "area": 2}
    d1 = tmp_path / "d1.sqlite"
    assert rows(d1, "SELECT version FROM active_release WHERE id = 1") == [(1,)]
    key, values, notes = cell(7)
    stored = rows(d1, f"SELECT * FROM cell WHERE version = 1 AND key = '{key}'")[0]
    assert list(stored[2:19]) == values and list(stored[19:]) == notes
    assert rows(d1, "SELECT name FROM occupation WHERE code = '533032'") == [("Heavy and Tractor-Trailer Truck Drivers' Helpers",)]
    release = rows(d1, "SELECT manifest, footnotes, database_sha256 FROM release WHERE version = 1")[0]
    assert json.loads(release[0]) == manifest
    assert json.loads(release[1]) == FOOTNOTES
    assert release[2] == manifest["database_sha256"]


def test_statements_fit_d1_limits(tmp_path, monkeypatch):
    make_bundle(tmp_path / "data", cells=400)
    monkeypatch.setattr(loader, "MAX_STATEMENT_BYTES", 8_000)
    db = Recording(tmp_path / "d1.sqlite")
    result = loader.load(db, tmp_path / "data", log=quiet)
    inserts = [s for s in db.sql if s.startswith("INSERT OR REPLACE INTO cell")]
    assert len(inserts) == result["insert_statements"] - 2 > 5  # occupation and area fit in one each
    assert all(len(s.encode()) <= 8_000 for s in db.sql if s.startswith("INSERT OR REPLACE"))
    # The real limit leaves headroom under D1's 100,000-byte statement cap.
    assert loader.MAX_STATEMENT_BYTES < 100_000
    assert rows(tmp_path / "d1.sqlite", "SELECT COUNT(*) FROM cell")[0][0] == 400


def test_rerun_is_a_no_op_and_force_switches_then_deletes_the_old_version(tmp_path, monkeypatch):
    make_bundle(tmp_path / "data", cells=250)
    monkeypatch.setattr(loader, "DELETE_RANGE_ROWS", 40)  # several key ranges
    d1 = tmp_path / "d1.sqlite"
    loader.load(loader.LocalD1(d1), tmp_path / "data", log=quiet)
    again = Recording(d1)
    assert loader.load(again, tmp_path / "data", log=quiet)["status"] == "unchanged"
    assert not [s for s in again.sql if s.startswith(("INSERT", "DELETE", "UPDATE"))]
    forced = loader.load(loader.LocalD1(d1), tmp_path / "data", force=True, log=quiet)
    assert (forced["version"], forced["previous_version"]) == (2, 1)
    assert rows(d1, "SELECT version FROM active_release") == [(2,)]
    for table in ("cell", "occupation", "area", "release"):
        assert rows(d1, f"SELECT DISTINCT version FROM {table}") == [(2,)], table
    assert rows(d1, "SELECT COUNT(*) FROM cell")[0][0] == 250


def test_new_release_replaces_the_active_one(tmp_path):
    make_bundle(tmp_path / "old", cells=120)
    make_bundle(tmp_path / "new", cells=130, release="2026A01", year="2026")
    d1 = tmp_path / "d1.sqlite"
    loader.load(loader.LocalD1(d1), tmp_path / "old", log=quiet)
    result = loader.load(loader.LocalD1(d1), tmp_path / "new", log=quiet)
    assert result["status"] == "loaded" and result["release"] == "May 2026"
    active = rows(d1, "SELECT r.manifest FROM active_release a JOIN release r ON r.version = a.version")
    assert json.loads(active[0][0])["release"]["code"] == "2026A01"
    assert rows(d1, "SELECT COUNT(*) FROM cell")[0][0] == 130


def test_interrupted_load_never_changes_what_readers_see_and_rerun_recovers(tmp_path):
    make_bundle(tmp_path / "old", cells=100)
    make_bundle(tmp_path / "new", cells=150, release="2026A01", year="2026")
    d1 = tmp_path / "d1.sqlite"

    def fresh():
        d1.unlink(missing_ok=True)
        loader.load(loader.LocalD1(d1), tmp_path / "old", log=quiet)

    fresh()
    probe = Recording(d1)
    loader.load(probe, tmp_path / "new", log=quiet)
    switch = next(i for i, sql in enumerate(probe.sql) if sql.startswith("INSERT INTO active_release"))
    # Fail mid-insert, just before the switch, and just after it (deleting the old version).
    for fail_after, active_after_failure, rows_visible in ((12, 1, 100), (switch, 1, 100), (switch + 1, 2, 150)):
        fresh()
        with pytest.raises(RuntimeError):
            loader.load(Recording(d1, fail_after=fail_after), tmp_path / "new", log=quiet)
        assert rows(d1, "SELECT version FROM active_release") == [(active_after_failure,)]
        assert rows(d1, f"SELECT COUNT(*) FROM cell WHERE version = {active_after_failure}")[0][0] == rows_visible
        result = loader.load(loader.LocalD1(d1), tmp_path / "new", log=quiet)
        assert result["status"] == ("unchanged" if active_after_failure == 2 else "loaded")
        active = rows(d1, "SELECT version FROM active_release")[0][0]
        for table in ("cell", "occupation", "area", "release"):
            assert rows(d1, f"SELECT DISTINCT version FROM {table}") == [(active,)], (fail_after, table)
        assert rows(d1, "SELECT COUNT(*) FROM cell")[0][0] == 150


def test_refuses_a_bundle_that_does_not_match_its_manifest(tmp_path):
    make_bundle(tmp_path / "data", tamper=lambda m: m.update(database_sha256="f" * 64))
    db = Recording(tmp_path / "d1.sqlite")
    with pytest.raises(SystemExit, match="does not match its manifest"):
        loader.load(db, tmp_path / "data", log=quiet)
    assert db.sql == []
    make_bundle(tmp_path / "other", tamper=lambda m: m["release"].update(code="2024A01"))
    with pytest.raises(SystemExit, match="release does not match"):
        loader.load(db, tmp_path / "other", log=quiet)
    assert db.sql == []


def test_row_count_mismatch_leaves_the_new_version_inactive(tmp_path):
    make_bundle(tmp_path / "old", cells=50)
    make_bundle(tmp_path / "bad", cells=60, release="2026A01", year="2026",
                tamper=lambda m: m["counts"].update(cells=61))
    d1 = tmp_path / "d1.sqlite"
    loader.load(loader.LocalD1(d1), tmp_path / "old", log=quiet)
    with pytest.raises(SystemExit, match="stays inactive"):
        loader.load(loader.LocalD1(d1), tmp_path / "bad", log=quiet)
    assert rows(d1, "SELECT version FROM active_release") == [(1,)]
    assert rows(d1, "SELECT COUNT(*) FROM cell WHERE version = 1")[0][0] == 50


def test_quote_escapes_literals():
    assert loader.quote(None) == "NULL"
    assert loader.quote(5) == "5"
    assert loader.quote("Drivers' Helpers") == "'Drivers'' Helpers'"
    con = sqlite3.connect(":memory:")
    assert con.execute(f"SELECT {loader.quote(chr(39) * 3 + 'x;--')}").fetchone()[0] == "'''x;--"


def test_schema_statements_apply_twice():
    con = sqlite3.connect(":memory:")
    for _ in range(2):
        for statement in loader.schema_statements():
            assert statement.endswith(";")
            con.execute(statement)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"release", "active_release", "cell", "occupation", "area"}


# ---------- remote mode (D1 HTTP API), with urlopen faked ----------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError("https://api.cloudflare.com", code, "error", {}, io.BytesIO(body))


def test_remote_query_retries_rate_limits_and_server_errors(monkeypatch):
    calls = []
    answers = [http_error(429), http_error(503),
               FakeResponse(json.dumps({"success": True, "result": [{"results": [{"n": 1}]}]}).encode())]

    def urlopen(request, timeout):
        calls.append(request)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(loader.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(loader.time, "sleep", lambda seconds: None)
    db = loader.RemoteD1("acct", "db-id", "token-value")
    assert db.query("SELECT 1 AS n;") == [{"n": 1}]
    assert len(calls) == 3
    request = calls[0]
    assert request.full_url == "https://api.cloudflare.com/client/v4/accounts/acct/d1/database/db-id/query"
    assert request.get_header("Authorization") == "Bearer token-value"
    assert "Python-urllib" not in request.get_header("User-agent")
    assert json.loads(request.data) == {"sql": "SELECT 1 AS n;"}


def test_remote_query_stops_on_client_errors_and_failed_queries(monkeypatch):
    monkeypatch.setattr(loader.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(loader.urllib.request, "urlopen",
                        lambda request, timeout: (_ for _ in ()).throw(http_error(400, b'{"errors":[{"message":"SQLITE_ERROR"}]}')))
    with pytest.raises(SystemExit, match="D1 API error 400"):
        loader.RemoteD1("a", "b", "c").query("SELECT;")
    monkeypatch.setattr(loader.urllib.request, "urlopen",
                        lambda request, timeout: FakeResponse(b'{"success": false, "errors": [{"message": "too big"}]}'))
    with pytest.raises(SystemExit, match="too big"):
        loader.RemoteD1("a", "b", "c").query("SELECT 1;")


def test_remote_mode_needs_a_token_and_a_real_database_id(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_D1_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="CLOUDFLARE_D1_TOKEN"):
        loader.main(["--remote", "--database-id", "abc"])
    monkeypatch.setenv("CLOUDFLARE_D1_TOKEN", "x")
    with pytest.raises(SystemExit, match="database-id"):
        loader.main(["--remote", "--database-id", "REPLACE_WITH_D1_DATABASE_ID"])


def test_bundled_release_loads_and_matches_its_manifest(tmp_path):
    """The real package data: every cell, occupation and area, verified by count."""
    result = loader.load(loader.LocalD1(tmp_path / "d1.sqlite"), log=quiet)
    manifest = json.loads((loader.DATA_DIR / "manifest.json").read_text())
    assert result["rows"] == {"cell": manifest["counts"]["cells"], "occupation": manifest["counts"]["occupations"],
                              "area": manifest["counts"]["areas"]}
