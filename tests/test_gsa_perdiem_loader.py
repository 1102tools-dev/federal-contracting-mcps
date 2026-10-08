"""Offline cases for the hosted GSA Per Diem D1 loader (no Cloudflare, no network)."""
import gzip
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("perdiem_loader", ROOT / "scripts/load_gsa_perdiem.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def counts(path):
    db = sqlite3.connect(path)
    try:
        return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("years", "zips", "places", "parts")}
    finally:
        db.close()


def release(path):
    db = sqlite3.connect(path)
    try:
        row = db.execute("SELECT release, parts, previous_parts FROM release WHERE id = 1").fetchone()
        return row and (row[0], json.loads(row[1]), json.loads(row[2]))
    finally:
        db.close()


def copy_data(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(loader.DATA, data)
    return data


def edit_year(data, fiscal_year, change):
    """Rewrite one bundled year file and its manifest hash, as a data refresh would."""
    manifest = json.loads((data / "manifest.json").read_text())
    meta = manifest["fiscal_years"][str(fiscal_year)]
    year = json.loads(gzip.decompress((data / meta["file"]).read_bytes()))
    change(year)
    raw = gzip.compress(json.dumps(year).encode(), mtime=0)
    (data / meta["file"]).write_bytes(raw)
    meta["file_sha256"] = hashlib.sha256(raw).hexdigest()
    (data / "manifest.json").write_text(json.dumps(manifest, indent=2))


def test_load_is_complete_then_idempotent(tmp_path):
    path = tmp_path / "d1.sqlite"
    first = loader.load(loader.LocalD1(path))
    assert first["status"] == "loaded"
    assert first["written_parts"] == sorted(first["parts"], key=lambda n: (n == "places", n))
    assert first["fiscal_years"] == [2021, 2022, 2023, 2024, 2025, 2026, 2027]
    n = counts(path)
    assert n["years"] == 7 and n["parts"] == 8
    assert n["years"] + n["zips"] + n["places"] == sum(first["rows"].values())
    assert release(path)[1] == first["parts"]

    db = loader.LocalD1(path)
    second = loader.load(db)
    assert second["status"] == "already_current" and second["written_parts"] == []
    assert db.requests == 2, "a current release costs the schema statement and one read"
    assert counts(path) == n


def test_statements_fit_d1_limits():
    _, _, parts = loader.read_parts()
    for part in parts:
        for table, rows in part.tables.items():
            for statement in loader.insert_statements(table, rows):
                assert len(statement.encode()) < 100_000
    for row in parts[0].tables["years"]:
        assert len(row[2].encode()) < 2_000_000


def test_interrupted_load_resumes_without_switching(tmp_path, monkeypatch):
    path = tmp_path / "d1.sqlite"
    real = loader.LocalD1.execute
    calls = {"n": 0}

    def flaky(self, statements):
        calls["n"] += 1
        if calls["n"] == 12:
            raise RuntimeError("connection dropped")
        return real(self, statements)

    monkeypatch.setattr(loader.LocalD1, "execute", flaky)
    with pytest.raises(RuntimeError):
        loader.load(loader.LocalD1(path))
    assert release(path) is None, "readers never see a partial release"
    monkeypatch.setattr(loader.LocalD1, "execute", real)
    resumed = loader.load(loader.LocalD1(path))
    assert resumed["status"] == "loaded"
    assert 0 < len(resumed["written_parts"]) < 8, "finished parts are not rewritten"
    fresh = tmp_path / "fresh.sqlite"
    loader.load(loader.LocalD1(fresh))
    assert counts(path) == counts(fresh)


def test_bad_row_count_keeps_the_previous_release(tmp_path, monkeypatch):
    path = tmp_path / "d1.sqlite"
    data = copy_data(tmp_path)
    loader.load(loader.LocalD1(path), data)
    before = release(path)
    edit_year(data, 2027, lambda y: y["destinations"][0].update(meals=y["destinations"][0]["meals"] + 1))
    real = loader.insert_statements

    def lossy(table, rows):
        statements = list(real(table, rows))
        return statements[:-1] if table == "zips" else statements

    monkeypatch.setattr(loader, "insert_statements", lossy)
    with pytest.raises(SystemExit, match="the release was not switched"):
        loader.load(loader.LocalD1(path), data)
    assert release(path) == before


def test_new_release_keeps_previous_parts_then_collects_them(tmp_path):
    path = tmp_path / "d1.sqlite"
    data = copy_data(tmp_path)
    first = loader.load(loader.LocalD1(path), data)
    edit_year(data, 2026, lambda y: y["destinations"][0].update(meals=1))
    second = loader.load(loader.LocalD1(path), data)
    assert second["written_parts"] == ["fy2026"] and second["removed_parts"] == []
    _, parts, previous = release(path)
    assert previous == first["parts"] and parts["fy2026"] != first["parts"]["fy2026"]
    edit_year(data, 2026, lambda y: y["destinations"][0].update(meals=2))
    third = loader.load(loader.LocalD1(path), data)
    assert third["removed_parts"] == [first["parts"]["fy2026"]]
    db = sqlite3.connect(path)
    for table in ("years", "zips", "parts"):
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE part = ?", [first["parts"]["fy2026"]]).fetchone()[0] == 0


def test_rejects_data_that_does_not_match_its_manifest(tmp_path):
    data = copy_data(tmp_path)
    (data / "fy2025.json.gz").write_bytes(gzip.compress(b"{}"))
    with pytest.raises(SystemExit, match="does not match manifest.json"):
        loader.load(loader.LocalD1(tmp_path / "d1.sqlite"), data)


class FakeD1Api:
    """The D1 HTTP API's /query endpoint over a local SQLite database."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.requests = []

    def urlopen(self, request, timeout=None):
        body = json.loads(request.data)
        self.requests.append((request.full_url, dict(request.header_items()), body))
        if "params" in body:
            results = [dict(r) for r in self.db.execute(body["sql"], body["params"])]
        else:
            with self.db:
                self.db.executescript(body["sql"])
            results = []
        payload = json.dumps({"success": True, "errors": [], "result": [{"results": results, "success": True}]}).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return payload

        return Response()


def test_remote_mode_uses_the_d1_http_api(monkeypatch, capsys):
    api = FakeD1Api()
    monkeypatch.setattr(urllib.request, "urlopen", api.urlopen)
    monkeypatch.setenv("CLOUDFLARE_D1_TOKEN", "test-token")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    loader.main(["--remote", "--database-id", "db-123"])
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "loaded" and summary["requests"] == len(api.requests)
    for url, headers, body in api.requests:
        assert url == "https://api.cloudflare.com/client/v4/accounts/846d3e41e48446abcd3570c0959f9fb5/d1/database/db-123/query"
        assert headers["Authorization"] == "Bearer test-token"
        assert len(json.dumps(body).encode()) < 1_000_000
        for statement in body["sql"].split(";\n"):
            assert len(statement.encode()) < 100_000
        assert len(body.get("params", [])) <= 100
    year_rows = sum(n for name, n in summary["rows"].items() if name != "places")
    assert api.db.execute("SELECT COUNT(*) FROM zips").fetchone()[0] == year_rows - 7, "one years row per part"
    loader.main(["--remote", "--database-id", "db-123"])
    assert json.loads(capsys.readouterr().out)["status"] == "already_current"


def test_remote_mode_needs_token_and_real_database_id(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_D1_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="CLOUDFLARE_D1_TOKEN"):
        loader.main(["--remote", "--database-id", "db-123"])
    monkeypatch.setenv("CLOUDFLARE_D1_TOKEN", "test-token")
    with pytest.raises(SystemExit, match="database-id"):
        loader.main(["--remote", "--database-id", "REPLACE_WITH_D1_DATABASE_ID"])
    monkeypatch.delenv("GSA_PERDIEM_D1_DATABASE_ID", raising=False)
    with pytest.raises(SystemExit, match="database-id"):
        loader.main(["--remote"])
