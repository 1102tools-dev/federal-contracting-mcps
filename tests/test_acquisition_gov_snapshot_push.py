"""Offline regression tests for parsed-only D1 snapshot publication."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import push_acquisition_gov_snapshot as push

loader = push.loader


def seed(path, snapshot=7):
    db = loader.LocalD1(path)
    db.execute([(loader.WORKER_DIR / "schema.sql").read_text()])
    stats = {"snapshot": snapshot, "parser_version": loader.PARSER_VERSION, "pdfs": 1}
    db.execute(loader.inserts("snapshots", ["id", "started_at", "completed_at", "stats"],
                             [[snapshot, "2026-10-10", "2026-10-10", json.dumps(stats)]]))
    db.execute(loader.inserts("meta", ["key", "value"], [["current", str(snapshot)]]))
    part = {"part": 19, "updated_date": None, "agency_deviations": [{"agency": "GSA", "source_id": "gsa", "source_url": "https://www.acquisition.gov/example.pdf"}]}
    db.execute(loader.doc_statements("index-doc", {"kind": "index", "info": {"parts": 1}, "parts": [part]}))
    db.execute(loader.doc_statements("pdf-doc", {"kind": "pdf", "info": {"total_pages": 1, "dates": {}},
             "pages": [{"page": 1, "start": 0, "text": "new FAR part 19 – café", "failure": None, "over_cap": False, "applicability": [[0, 4]]}]}))
    db.execute(loader.doc_statements("html-doc", {"kind": "html", "info": {}, "streams": {"text": "FAR overhaul", "sections": "19.1\nSmall business"}, "headings": [[0, "19.1", 0, 19]]}))
    sources = []
    keys = ["index", *(f"part:{n}" for n in loader.PARTS), *(f"guidance:{n}" for n in loader.constants.GUIDANCE_URLS), "pdf:https://www.acquisition.gov/example.pdf"]
    for key in keys:
        doc = "index-doc" if key == "index" else "pdf-doc" if key.startswith("pdf:") else "html-doc"
        error = "Acquisition.gov returned HTTP 404" if key in ("part:20", "part:21") else None
        sources.append([snapshot, key, "https://www.acquisition.gov/" + key, None, None, "2026-10-10", "f" * 64, error, None if error else doc])
    db.execute(loader.inserts("sources", list(push.SOURCE_COLUMNS), sources))
    # Extra local tables/files are excluded from the explicitly allowlisted transfer.
    db.execute(["CREATE TABLE raw_cache (body BLOB);", "INSERT INTO raw_cache VALUES (X'25504446');"])
    (path.parent / "raw.pdf").write_bytes(b"%PDF-RAW-CACHE")
    return db


def empty(path):
    db = loader.LocalD1(path)
    db.execute([(loader.WORKER_DIR / "schema.sql").read_text()])
    return db


def test_complete_transfer_remaps_snapshot_and_preserves_all_parsed_rows(tmp_path):
    local = seed(tmp_path / "local.sqlite")
    remote = empty(tmp_path / "remote.sqlite")
    stats = push.publish(local, remote, log=lambda _: None)
    assert stats["snapshot"] == 1
    assert stats["imported_from_snapshot"] == 7
    assert remote.query("SELECT value FROM meta WHERE key='current'") == [{"value": "1"}]
    for table, columns in push.TABLES.items():
        assert push.fingerprint(local.query(f"SELECT * FROM {table}"), columns) == push.fingerprint(remote.query(f"SELECT * FROM {table}"), columns)
    assert all(row["snapshot"] == 1 for row in remote.query("SELECT * FROM sources"))
    assert not remote.query("SELECT name FROM sqlite_master WHERE name='raw_cache'")
    assert remote.query("SELECT error FROM sources WHERE key='part:20'")[0]["error"]


def test_interrupted_upload_keeps_current_and_retry_repairs_partial_rows(tmp_path):
    local = seed(tmp_path / "local.sqlite")
    remote = empty(tmp_path / "remote.sqlite")
    remote.execute(loader.inserts("snapshots", ["id", "started_at"], [[40, "earlier"]]))
    remote.execute(loader.inserts("meta", ["key", "value"], [["current", "40"], ["staging", "39"]]))
    execute = remote.execute
    def fail_at_completion(statements):
        for position, statement in enumerate(statements):
            if "INSERT OR IGNORE INTO docs" in statement:
                execute(statements[:position])
                raise RuntimeError("connection interrupted")
        execute(statements)
    remote.execute = fail_at_completion
    with pytest.raises(RuntimeError, match="interrupted"):
        push.publish(local, remote, log=lambda _: None)
    assert remote.query("SELECT value FROM meta WHERE key='current'") == [{"value": "40"}]
    assert remote.query("SELECT * FROM pages")  # partial parsed content was uploaded
    remote.execute = execute
    push.publish(local, remote, log=lambda _: None)
    assert remote.query("SELECT value FROM meta WHERE key='current'") == [{"value": "42"}]
    assert remote.query("SELECT value FROM meta WHERE key='previous'") == [{"value": "40"}]
    assert remote.query("SELECT value FROM meta WHERE key='staging'") == [{"value": "39"}]


def test_existing_document_mismatch_fails_closed(tmp_path):
    local = seed(tmp_path / "local.sqlite")
    remote = seed(tmp_path / "remote.sqlite", snapshot=3)
    remote.execute(["UPDATE pages SET body='different text' WHERE doc='pdf-doc';"])
    with pytest.raises(loader.Abort, match="differs in pages"):
        push.publish(local, remote, log=lambda _: None)
    assert remote.query("SELECT value FROM meta WHERE key='current'") == [{"value": "3"}]
    assert remote.query("SELECT body FROM pages")[0]["body"] == "different text"


@pytest.mark.parametrize("change", ["DELETE FROM sources WHERE key LIKE 'pdf:%'", "UPDATE snapshots SET completed_at=NULL", "DELETE FROM docs WHERE id='pdf-doc'"])
def test_incomplete_local_aborts_before_remote_writes(tmp_path, change):
    local = seed(tmp_path / "local.sqlite")
    local.execute([change])
    remote = empty(tmp_path / "remote.sqlite")
    with pytest.raises(loader.Abort):
        push.publish(local, remote, log=lambda _: None)
    assert remote.query("SELECT * FROM snapshots") == []


def test_concurrent_nightly_switch_is_not_overwritten(tmp_path):
    local = seed(tmp_path / "local.sqlite")
    remote = empty(tmp_path / "remote.sqlite")
    remote.execute(loader.inserts("snapshots", ["id", "started_at"], [[40, "earlier"]]))
    remote.execute(loader.inserts("meta", ["key", "value"], [["current", "40"]]))
    execute = remote.execute
    def nightly_finishes(statements):
        if any(statement.startswith("UPDATE meta SET value=") for statement in statements):
            execute(["UPDATE meta SET value='99' WHERE key='current';"])
        execute(statements)
    remote.execute = nightly_finishes
    with pytest.raises(loader.Abort, match="concurrent load"):
        push.publish(local, remote, log=lambda _: None)
    assert remote.query("SELECT value FROM meta WHERE key='current'") == [{"value": "99"}]


def test_source_snapshot_is_opened_read_only(tmp_path):
    path = tmp_path / "local.sqlite"
    seed(path).db.close()
    source = push.ReadOnlySnapshot(path)
    try:
        assert push.validate_local(source)[0] == 7
        with pytest.raises(loader.sqlite3.OperationalError, match="readonly"):
            source.db.execute("DELETE FROM meta")
    finally:
        source.db.close()


def test_unicode_api_payloads_stay_under_request_limit():
    remote = push.PublisherD1("test-database", "unused-offline-token")
    payloads = []
    remote._post = lambda payload: payloads.append(payload)
    statements = ["SELECT '" + "\\雪" * 12000 + "';" for _ in range(12)]
    remote.execute(statements)
    assert len(payloads) > 1
    assert all(len(json.dumps(payload).encode()) <= loader.REQUEST_BYTES for payload in payloads)
    assert sum(payload["sql"].count("SELECT") for payload in payloads) == 12


def test_remote_verification_batches_all_tables_and_quotes_ids():
    remote = push.PublisherD1("test-database", "unused-offline-token")
    payloads = []
    def respond(payload):
        payloads.append(payload)
        return [{"success": True, "results": []} for _ in push.TABLES]
    remote._post = respond
    assert push.all_document_rows(remote, ["doc'quoted"]) == {table: [] for table in push.TABLES}
    assert len(payloads) == 1
    assert payloads[0]["sql"].count("SELECT") == len(push.TABLES)
    assert "'doc''quoted'" in payloads[0]["sql"]
