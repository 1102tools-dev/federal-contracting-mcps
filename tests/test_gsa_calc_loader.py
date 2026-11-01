"""Offline cases for the hosted GSA CALC+ D1 loader (no Cloudflare, no GSA, no network).

Writes tiny recordings shaped like `load_gsa_calc.py record` output (night 1, and a
night 2 with a record unchanged, one changed, one removed, one whose only change
is _timestamp, one added, and one that came back under a new _id), then runs
build, diff and refresh against local sqlite and a fake D1 HTTP API.

    uv run --project servers/gsa-calc-mcp --with pytest pytest -q tests/test_gsa_calc_loader.py
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


loader = module("load_gsa_calc", ROOT / "scripts/load_gsa_calc.py")

NIGHT1, TS1 = "ceilingrates-2026-11-01_02-00-02", "2026-11-01T02:00:03Z"
NIGHT2, TS2 = "ceilingrates-2026-11-02_02-00-02", "2026-11-02T02:00:04Z"
NIGHT3, TS3 = "ceilingrates-2026-11-03_02-00-01", "2026-11-03T02:00:02Z"
NIGHT4, TS4 = "ceilingrates-2026-11-04_02-00-02", "2026-11-04T02:00:03Z"
OPEN = loader.OPEN


def quiet(message):
    pass


def source(ident, labor, vendor, piid, price, ts, **extra):
    """A _source in GSA's key order (as the 2026-10-10 fixtures show it)."""
    row = {"contract_end": "2027-01-17", "security_clearance": False, "next_year_price": round(price * 1.03, 2),
           "second_year_price": round(price * 1.06, 2), "vendor_name": vendor, "idv_piid": piid,
           "business_size": "S", "contract_start": "2022-01-18", "data_source": "ACR", "labor_category": labor,
           "schedule": "MAS", "cont_end_dtg": "20270117", "min_years_experience": 1, "sin": "541620,541611",
           "worksite": "Customer_Facility", "education_level": "Bachelors", "id": ident, "current_price": price,
           "dt_termg": "", "category": "Professional Services", "subcategory": "Business Administrative Services",
           "_timestamp": ts, "cont_beg_dtg": "20220118"}
    row.update(extra)
    return row


def night_one():
    return {
        "1001": source(1001, "Registered Nurse I", "T47 INTERNATIONAL, INC.", "47QRAA22D004N", 28.9, TS1),
        "1002": source(1002, "Engineer II", "Acme Corp", "GS-35F-0001A", 101.37, TS1),
        "1003": source(1003, "Analyst", "Gone LLC", "47QTCA19D00AB", 77.5, TS1),
        "1004": source(1004, "Program Manager", "Acme Corp", "GS-35F-0001A", 150.0, TS1,
                       security_clearance=True, sin="54151S", business_size="O", min_years_experience=10),
        "1007": source(1007, "Retired Role", "Old Vendor Inc", "GS-00F-0000X", 60.0783, TS1, worksite="Both"),
    }


def night_two():
    """1001 unchanged; 1002 price changed; 1003 removed but back as 1006; 1004 only
    _timestamp moved; 1005 added (non-ASCII); 1007 removed."""
    before = night_one()
    after = {k: copy.deepcopy(v) for k, v in before.items() if k in ("1001", "1002", "1004")}
    for row in after.values():
        row["_timestamp"] = TS2
    after["1002"]["current_price"] = 104.41
    after["1005"] = source(1005, "Développeur Senior", "Nouveau S.A.", "47QTCA26D0001", 88.12, TS2)
    after["1006"] = dict(before["1003"], id=1006, _timestamp=TS2)
    return after


def night_three(ts=TS3):
    """Night two's records with a new _timestamp only."""
    after = night_two()
    for row in after.values():
        row["_timestamp"] = ts
    return after


def write_recording(path, index, records, priced=None, pull=False):
    """records.jsonl.gz + summary.json as record writes them (under pull/ when asked)."""
    where = path / "pull" if pull else path
    where.mkdir(parents=True)
    with gzip.open(where / "records.jsonl.gz", "wt", encoding="utf-8") as fh:
        for _id, row in records.items():
            fh.write(json.dumps({"_id": _id, "_source": row}) + "\n")
    summary = {"index": index, "priced_records": len(records) if priced is None else priced,
               "records": len(records), "calls": 4, "lost_in_subslices": 0, "unresolved": 0, "slices": []}
    (where / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return path


@pytest.fixture
def recs(tmp_path):
    return (write_recording(tmp_path / "n1", NIGHT1, night_one()),
            write_recording(tmp_path / "n2", NIGHT2, night_two()),
            write_recording(tmp_path / "n3", NIGHT3, night_three()),
            write_recording(tmp_path / "n4", NIGHT4, night_three(TS4)))


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def expected_hash(row):
    text = json.dumps({k: v for k, v in row.items() if k != "_timestamp"}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def conn(db):
    return db.db if isinstance(db, loader.LocalD1) else db


def view(db, night):
    """What the Worker reads for a night: {id: (hash, price, sources json)}."""
    rows = conn(db).execute("SELECT r.id, r.hash, r.price, s.json FROM records r JOIN sources s ON s.rid = r.rid "
                            "WHERE r.v_from <= ? AND ? < r.v_to", (night, night)).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def meta(db):
    return {r[0]: r[1] for r in conn(db).execute("SELECT key, value FROM meta")}


def dump(db):
    """Tables without rids: records by (id, v_from), sources by id, terms, meta minus loaded_at."""
    c = conn(db)
    records = sorted(tuple(r)[1:] for r in c.execute(f"SELECT {', '.join(loader.RECORD_COLUMNS)}, v_to FROM records"))
    sources = sorted(tuple(r) for r in c.execute("SELECT r.id, r.v_from, s.json FROM records r JOIN sources s USING (rid)"))
    terms = sorted(tuple(r) for r in c.execute("SELECT field, value, folded FROM terms"))
    return records, sources, terms, {k: v for k, v in meta(db).items() if k != "loaded_at"}


def counts(db):
    c = conn(db)
    return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("records", "sources", "terms", "meta")}


# ---------- night 1 ----------

def test_night_one_rows(recs):
    db = loader.LocalD1(":memory:")
    status = loader.build(db, recs[0], log=quiet)
    rows = night_one()
    assert status["action"] == "loaded" and status["night"] == 1 and status["records"] == 5
    stored = {r["id"]: r for r in db.query("SELECT * FROM records")}
    assert sorted(stored) == [1001, 1002, 1003, 1004, 1007]
    assert all(r["v_from"] == 1 and r["v_to"] == OPEN for r in stored.values())
    nurse = stored[1001]
    assert nurse["price"] == f32(28.9) == 28.899999618530273 and nurse["price"] != 28.9
    assert nurse["next_year_price"] == f32(29.77)
    assert stored[1007]["price"] == f32(60.0783)
    assert nurse["sin"] == ",541620,541611," and stored[1004]["sin"] == ",54151S,"
    assert (nurse["security_clearance"], stored[1004]["security_clearance"]) == (0, 1)
    assert (stored[1004]["business_size"], stored[1004]["min_years_experience"]) == ("O", 10)
    assert (nurse["education_level"], nurse["worksite"], stored[1007]["worksite"]) == ("Bachelors", "Customer_Facility", "Both")
    assert (nurse["labor_category"], nurse["vendor_name"], nurse["idv_piid"]) == (
        "Registered Nurse I", "T47 INTERNATIONAL, INC.", "47QRAA22D004N")
    for ident, r in stored.items():
        assert r["hash"] == expected_hash(rows[str(ident)])
        text = db.query("SELECT json FROM sources WHERE rid = ?", [r["rid"]])[0]["json"]
        assert text == json.dumps(rows[str(ident)], ensure_ascii=False, separators=(",", ":"))
        assert list(json.loads(text)) == list(rows[str(ident)])  # GSA's key order
    terms = {(r["field"], r["value"]): r["folded"] for r in db.query("SELECT * FROM terms")}
    assert len(terms) == 13 and terms[("vendor_name", "T47 INTERNATIONAL, INC.")] == "t47 international, inc."
    assert {f for f, _ in terms} == set(loader.TERM_FIELDS)
    m = meta(db)
    assert (m["current"], m["version"], m["timestamp"]) == ("1", NIGHT1, TS1) and "staging" not in m
    assert m["loaded_at"].endswith("+00:00")
    assert status["timestamp"] == TS1 and status["distinct_timestamps"] == 1
    assert status["checks"] == {}
    # 5 records rows + 5 sources + 13 terms + 6 meta (staging in, 4 switch keys in, staging out)
    # + 15 index entries for the records rows + 6 for meta keys inserted or deleted.
    assert status["written_estimate"] == {"records": 5, "sources": 5, "terms": 13, "meta": 6,
                                          "index_entries": 21, "total": 50}
    est = status["written_estimate"]
    assert status["rows_written"] == db.rows_written == est["total"] - est["index_entries"]
    assert status["db_bytes"] > 0 and status["seconds"] >= 0


def test_rebuilding_the_same_night_writes_nothing(recs):
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    before = dump(db)
    db.rows_written = 0
    status = loader.build(db, recs[0], log=quiet)
    assert status["action"] == "unchanged" and status["rows_written"] == 0 and db.rows_written == 0
    assert status["written_estimate"]["total"] == 0 and dump(db) == before


def test_pull_subdirectory_and_limit(tmp_path):
    rec = write_recording(tmp_path / "rec", NIGHT1, night_one(), pull=True)
    db = loader.LocalD1(":memory:")
    status = loader.build(db, rec, limit=2, log=quiet)
    assert status["records"] == 2 and counts(db)["records"] == 2
    assert sorted(view(db, 1)) == [1001, 1002] and meta(db)["version"] == NIGHT1


def test_older_recording_is_refused(recs):
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[1], log=quiet)
    before = dump(db)
    with pytest.raises(loader.Refused, match="older"):
        loader.build(db, recs[0], log=quiet)
    assert dump(db) == before


def test_short_recording_is_refused_for_a_change_only_night(recs, tmp_path):
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    short = write_recording(tmp_path / "short", NIGHT2, night_two(), priced=9)
    before = dump(db)
    with pytest.raises(loader.Refused, match="incomplete"):
        loader.build(db, short, log=quiet)
    assert dump(db) == before
    assert loader.build(db, short, log=quiet, allow_short=True)["action"] == "loaded"


# ---------- night 2: change-only ----------

def test_night_two_change_only(recs):
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    rids = {r["id"]: r["rid"] for r in db.query("SELECT id, rid FROM records")}
    status = loader.build(db, recs[1], log=quiet)
    rows = night_two()
    assert status["action"] == "loaded" and status["night"] == 2
    assert (status["inserted"], status["unchanged"], status["retired"], status["closed"], status["deleted"]) == (
        3, 2, 3, 3, 0)
    stored = {(r["id"], r["v_from"]): r for r in db.query("SELECT * FROM records")}
    # Unchanged and _timestamp-only rows stay as they were; the changed and new ones are night 2's;
    # the replaced and removed ones are closed at night 2 and kept for night 1 until the next switch.
    assert sorted(stored) == [(1001, 1), (1002, 1), (1002, 2), (1003, 1), (1004, 1), (1005, 2), (1006, 2), (1007, 1)]
    assert stored[(1001, 1)]["rid"] == rids[1001] and stored[(1004, 1)]["rid"] == rids[1004]
    assert stored[(1002, 2)]["price"] == f32(104.41) and stored[(1002, 2)]["hash"] == expected_hash(rows["1002"])
    assert {k: r["v_to"] for k, r in stored.items() if r["v_to"] != OPEN} == {(1002, 1): 2, (1003, 1): 2, (1007, 1): 2}
    assert counts(db)["sources"] == 8
    assert {i: h for i, (h, _, _) in view(db, 2).items()} == {int(k): expected_hash(v) for k, v in rows.items()}
    # A _timestamp-only change is not rewritten: its stored JSON keeps night 1's stamp, and the
    # Worker puts meta 'timestamp' in its place.
    assert json.loads(view(db, 2)[1004][2])["_timestamp"] == TS1 and meta(db)["timestamp"] == TS2
    assert json.loads(view(db, 2)[1005][2])["labor_category"] == "Développeur Senior"
    terms = {(r["field"], r["value"]): r["folded"] for r in db.query("SELECT * FROM terms")}
    assert ("labor_category", "Retired Role") in terms  # night 1's 1007 is kept a night, so its terms are
    assert ("labor_category", "Analyst") in terms  # 1006 still uses it
    assert terms[("labor_category", "Développeur Senior")] == "développeur senior"
    assert status["terms"] == {"total": 16, "night": 13, "added": 3, "refolded": 0, "removed": 0}
    m = meta(db)
    assert (m["current"], m["version"], m["timestamp"]) == ("2", NIGHT2, TS2) and "staging" not in m
    # 3 inserts (each with 3 index entries and a sources row) and 3 closes on records, 3 new terms,
    # meta: staging in, 4 switch updates, staging out. The deletes come at the next switch.
    assert status["written_estimate"] == {"records": 6, "sources": 3, "terms": 3, "meta": 6,
                                          "index_entries": 11, "total": 29}
    est = status["written_estimate"]
    assert status["rows_written"] == est["total"] - est["index_entries"]
    db.rows_written = 0
    assert loader.build(db, recs[1], log=quiet)["action"] == "unchanged" and db.rows_written == 0


def test_a_night_with_only_new_timestamps_writes_meta_only(recs):
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[1], log=quiet)
    before = dump(db)[:3]
    status = loader.build(db, recs[2], log=quiet)
    assert status["inserted"] == 0 and status["closed"] == 0 and status["deleted"] == 0
    assert status["written_estimate"]["total"] == 8 and dump(db)[:3] == before  # staging in/out + 4 switch keys
    assert (meta(db)["current"], meta(db)["timestamp"]) == ("2", TS3)


def test_fold_rule_change_refolds_terms(recs, monkeypatch):
    db = loader.LocalD1(":memory:")
    monkeypatch.setattr(loader, "fold", lambda value: value.upper())
    loader.build(db, recs[0], log=quiet)
    monkeypatch.undo()
    status = loader.build(db, recs[1], log=quiet)
    # 10 of night 2's terms existed, plus 3 kept for night 1's retired 1007: all refolded.
    assert status["terms"]["refolded"] == 13 and status["terms"]["added"] == 3
    assert all(r["folded"] == r["value"].lower() for r in db.query("SELECT * FROM terms"))


def test_a_reader_of_night_n_still_sees_it_after_the_switch(recs):
    """Cleanup runs a night behind: an answer that read current = N just before the switch to
    N+1 still finds every night-N row, its sources JSON and its terms afterwards."""
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    night1 = view(db, 1)
    assert sorted(night1) == [1001, 1002, 1003, 1004, 1007]
    loader.build(db, recs[1], log=quiet)
    assert meta(db)["current"] == "2" and view(db, 1) == night1
    terms = {(r["field"], r["value"]) for r in db.query("SELECT field, value FROM terms")}
    assert all(set(loader.term_values(row)) <= terms for rows in (night_one(), night_two()) for row in rows.values())
    night2 = view(db, 2)
    status = loader.build(db, recs[2], log=quiet)
    assert meta(db)["current"] == "3" and view(db, 2) == night2
    # Night 1's retired rows go at the switch after the one that retired them, with their terms.
    assert status["deleted"] == 3 and status["terms"]["removed"] == 3 and sorted(view(db, 1)) == [1001, 1004]
    assert counts(db)["records"] == counts(db)["sources"] == 5
    assert ("labor_category", "Retired Role") not in {(r["field"], r["value"]) for r in db.query("SELECT * FROM terms")}
    assert status["written_estimate"] == {"records": 3, "sources": 3, "terms": 3, "meta": 6,
                                          "index_entries": 11, "total": 26}


def test_cleanup_left_by_a_stopped_run_is_finished_next_night(recs, monkeypatch):
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    loader.build(db, recs[1], log=quiet)
    real = loader.LocalD1.execute

    def stop_at_cleanup(self, statements):
        if any("DELETE FROM meta WHERE key = 'staging'" in s for s in statements):
            raise RuntimeError("lost the connection")
        return real(self, statements)

    monkeypatch.setattr(loader.LocalD1, "execute", stop_at_cleanup)
    with pytest.raises(RuntimeError, match="lost"):
        loader.build(db, recs[2], log=quiet)
    monkeypatch.undo()
    m = meta(db)
    assert (m["current"], m["staging"]) == ("3", "3")  # switched; cleanup not done
    assert {i for i in view(db, 3)} == {int(k) for k in night_two()}
    assert conn(db).execute("SELECT COUNT(*) FROM records WHERE v_to = 2").fetchone()[0] == 3
    status = loader.build(db, recs[3], log=quiet)
    assert status["deleted"] == 3 and status["inserted"] == 0 and status["terms"]["removed"] == 3
    assert conn(db).execute("SELECT COUNT(*) FROM records WHERE v_to != ?", (OPEN,)).fetchone()[0] == 0
    assert counts(db)["records"] == counts(db)["sources"] == 5 and "staging" not in meta(db)


# ---------- the D1 HTTP API (faked) ----------

class FakeD1:
    """The D1 /query endpoint over an in-memory sqlite: one result per request with meta.
    fail(payload) -> True raises before applying it; bill multiplies rows_written;
    js_numbers returns integers past 2**53 rounded, as D1's JSON does."""

    def __init__(self, fail=None, bill=1, js_numbers=False):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(loader.SCHEMA.read_text())
        self.payloads = []
        self.fail = fail
        self.bill = bill
        self.js_numbers = js_numbers

    def execute(self, sql, params=()):
        return self.db.execute(sql, params)

    def __call__(self, payload):
        self.payloads.append(payload)
        if self.fail and self.fail(payload):
            raise RuntimeError("connection reset")
        if "params" in payload:
            rows = [dict(r) for r in self.db.execute(payload["sql"], payload["params"])]
            if self.js_numbers:
                rows = [{k: int(float(v)) if isinstance(v, int) and abs(v) >= 2 ** 53 else v for k, v in r.items()}
                        for r in rows]
            return {"success": True, "result": [{"results": rows, "meta": {"rows_read": len(rows), "rows_written": 0}}]}
        before = self.db.total_changes
        self.db.executescript(payload["sql"])
        meta_ = {"rows_written": (self.db.total_changes - before) * self.bill, "size_after": 12288}
        return {"success": True, "result": [{"results": [], "meta": meta_}]}


def remote(fake, max_rows=None):
    return loader.RemoteD1("db", "token", "account", max_rows=max_rows, post=fake, sleep=lambda s: None)


def nth(marker, n):
    """fail on the n-th write request containing marker."""
    seen = [0]

    def check(payload):
        if "params" not in payload and marker in payload["sql"]:
            seen[0] += 1
            return seen[0] == n
        return False
    return check


def test_remote_matches_local_and_sums_rows_written(recs):
    local = loader.LocalD1(":memory:")
    fake = FakeD1()
    for rec in recs:
        a = loader.build(local, rec, log=quiet)
        b = loader.build(remote(fake), rec, log=quiet)
        assert a["rows_written"] == b["rows_written"] and a["written_estimate"] == b["written_estimate"]
        assert dump(local) == dump(fake)
    assert b["db_bytes"] == 12288


def test_remote_reads_open_rows_that_d1_rounded(recs):
    fake = FakeD1(js_numbers=True)
    loader.build(remote(fake), recs[0], log=quiet)
    assert loader.stored_rows(remote(fake))[0][4] == OPEN
    status = loader.build(remote(fake), recs[1], log=quiet)
    assert status["reopened"] == 0 and status["closed"] == 3


def test_remote_stops_without_rows_written_meta(recs):
    class NoMeta(FakeD1):
        def __call__(self, payload):
            body = super().__call__(payload)
            for r in body["result"]:
                r["meta"].pop("rows_written")
            return body

    with pytest.raises(RuntimeError, match="rows_written"):
        loader.build(remote(NoMeta()), recs[0], log=quiet)


def test_max_rows_refuses_before_writing(recs):
    fake = FakeD1()
    loader.build(remote(fake), recs[0], log=quiet)
    before = dump(fake)
    with pytest.raises(loader.RowCap, match="Nothing written"):
        loader.build(remote(fake, max_rows=28), recs[1], log=quiet)
    assert dump(fake) == before and "staging" not in meta(fake)
    assert loader.build(remote(fake, max_rows=29), recs[1], log=quiet)["action"] == "loaded"


def test_a_stopped_refresh_never_switches_and_the_next_run_reuses_its_rows(recs, monkeypatch):
    """D1 bills more than projected: the cap stops the run mid-staging. Night 1 keeps
    serving exactly; the next run keeps the staged rows that still match."""
    local = loader.LocalD1(":memory:")
    for rec in recs[:2]:
        loader.build(local, rec, log=quiet)
    fake = FakeD1()
    loader.build(remote(fake), recs[0], log=quiet)
    night1 = view(fake, 1)
    monkeypatch.setattr(loader, "CHUNK_RECORDS", 1)
    fake.bill = 10  # staging meta 10 + terms 30, then the first record's 2 rows pass 50
    with pytest.raises(loader.RowCap, match="passed --max-rows"):
        loader.build(remote(fake, max_rows=50), recs[1], log=quiet)
    m = meta(fake)
    assert (m["current"], m["version"], m["staging"]) == ("1", NIGHT1, "2")
    assert view(fake, 1) == night1
    staged = fake.execute("SELECT id FROM records WHERE v_from = 2").fetchall()
    assert len(staged) == 1
    fake.bill = 1
    status = loader.build(remote(fake), recs[1], log=quiet)
    assert status["kept_staged"] == 1 and status["inserted"] == 2 and status["action"] == "loaded"
    assert dump(fake) == dump(local)


def test_an_interrupted_load_leaves_orphans_that_the_next_run_removes(recs, monkeypatch):
    local = loader.LocalD1(":memory:")
    for rec in recs[:2]:
        loader.build(local, rec, log=quiet)
    fake = FakeD1()
    loader.build(remote(fake), recs[0], log=quiet)
    monkeypatch.setattr(loader, "CHUNK_RECORDS", 1)
    monkeypatch.setattr(loader, "REQUEST_BYTES", 100)  # every statement its own request
    fake.fail = nth("INTO records", 2)                  # 1005's sources row lands, its records row doesn't
    with pytest.raises(RuntimeError, match="connection reset"):
        loader.build(remote(fake), recs[1], log=quiet)
    assert meta(fake)["current"] == "1"
    assert fake.execute("SELECT COUNT(*) FROM sources WHERE rid NOT IN (SELECT rid FROM records)").fetchone()[0] == 1
    fake.fail = None
    status = loader.build(remote(fake), recs[1], log=quiet)
    assert (status["orphan_sources"], status["kept_staged"], status["inserted"]) == (1, 1, 2)
    assert dump(fake) == dump(local)
    assert fake.execute("SELECT COUNT(*) FROM sources WHERE rid NOT IN (SELECT rid FROM records)").fetchone()[0] == 0


def test_a_first_load_interrupted_part_way_resumes(recs, monkeypatch):
    local = loader.LocalD1(":memory:")
    loader.build(local, recs[0], log=quiet)
    fake = FakeD1()
    monkeypatch.setattr(loader, "CHUNK_RECORDS", 2)
    fake.fail = nth("INTO records", 2)
    with pytest.raises(RuntimeError):
        loader.build(remote(fake), recs[0], log=quiet)
    assert "current" not in meta(fake) and meta(fake)["staging"] == "1"
    fake.fail = None
    status = loader.build(remote(fake), recs[0], log=quiet)
    assert (status["kept_staged"], status["inserted"]) == (2, 3)
    assert dump(fake) == dump(local)


def test_cli_remote_build_applies_schema(recs, tmp_path, monkeypatch, capsys):
    fake = FakeD1()
    fake.db.executescript("DROP TABLE records; DROP TABLE sources; DROP TABLE terms; DROP TABLE meta;")
    monkeypatch.setattr(loader.RemoteD1, "_http", lambda self, payload: fake(payload))
    monkeypatch.setenv("CLOUDFLARE_D1_TOKEN", "token")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "846d3e41e48446abcd3570c0959f9fb5")
    out = tmp_path / "status.json"
    args = ["build", "--remote", "--database-id", "00000000-0000-4000-8000-000000000000",
            "--rec", str(recs[0]), "--json", str(out)]
    assert loader.main(args) == 0
    status = json.loads(out.read_text())
    assert status["records"] == 5 and status["d1_requests"] > 3 and counts(fake)["records"] == 5
    assert loader.main(args + ["--max-rows", "10"]) == 0  # same night: nothing to write
    assert json.loads(out.read_text())["action"] == "unchanged"
    assert loader.main(["build", "--remote", "--database-id", "00000000-0000-4000-8000-000000000000",
                        "--rec", str(recs[1]), "--max-rows", "10", "--json", str(out)]) == 2
    assert "passes --max-rows" in json.loads(out.read_text())["stopped"]


def test_database_id_sources(monkeypatch):
    monkeypatch.delenv("GSA_CALC_D1_DATABASE_ID", raising=False)
    monkeypatch.setattr(loader, "wrangler_config", lambda: {"env": {"production": {"d1_databases": [
        {"binding": "DB", "database_id": "11111111-2222-4333-8444-555555555555"}]}}})
    assert loader.database_id(None) == "11111111-2222-4333-8444-555555555555"
    monkeypatch.setenv("GSA_CALC_D1_DATABASE_ID", "aaaaaaaa-2222-4333-8444-555555555555")
    assert loader.database_id(None) == "aaaaaaaa-2222-4333-8444-555555555555"
    monkeypatch.setattr(loader, "wrangler_config", lambda: {})
    monkeypatch.delenv("GSA_CALC_D1_DATABASE_ID")
    with pytest.raises(SystemExit):
        loader.database_id(None)


def test_statement_limits(monkeypatch):
    rows = [[i, "x" * 2000] for i in range(200)]
    statements = loader.inserts("sources", ("rid", "json"), rows)
    assert len(statements) > 3 and max(loader.size(s) for s in statements) <= loader.STATEMENT_BYTES
    ids = loader.by_rid("DELETE FROM records WHERE rid IN (", list(range(100_000)))
    assert len(ids) > 1 and all(s.endswith(");") for s in ids)
    assert loader.quote("a\x00b'") == "('a' || char(0) || 'b''')"
    assert loader.quote(f32(28.9)) == "28.899999618530273" and loader.quote(float("nan")) == "NULL"


# ---------- values ----------

def test_value_rules():
    assert loader.float32(None) is None and loader.float32("x") is None and loader.float32(True) is None
    assert loader.float32(100) == 100.0 and loader.float32("28.9") == f32(28.9)
    assert [loader.clearance(v) for v in (True, False, None, "true", "No", "maybe")] == [1, 0, None, 1, 0, None]
    assert loader.sin_column("541611") == ",541611," and loader.sin_column(None) is None
    assert loader.sin_column(["1", "2"]) == ",1,2,"
    assert loader.record_id("17", {}) == 17 and loader.record_id("x", {"id": 9}) == 9
    a = source(1, "A", "B", "C", 1.0, TS1)
    b = dict(a, _timestamp=TS2)
    assert loader.record_hash(a) == loader.record_hash(b)
    assert loader.record_hash(dict(reversed(list(a.items())))) == loader.record_hash(a)  # canonical: key order ignored
    db = loader.LocalD1(":memory:")
    values = [f32(x / 7) for x in range(1, 2000)]
    db.execute(loader.inserts("records", ("rid", "id", "v_from", "price", "hash"),
                              [[i, i, 1, v, "h"] for i, v in enumerate(values)]))
    assert [r["price"] for r in db.query("SELECT price FROM records ORDER BY rid")] == values


# ---------- diff ----------

def test_diff_counts_churn_and_projects_the_build(recs):
    report = loader.diff(recs[0], recs[1], log=quiet)
    assert (report["added"], report["removed"], report["changed"], report["unchanged"]) == (2, 2, 1, 2)
    assert report["unchanged_but__timestamp_differs"] == 2 and report["unchanged_but_key_order_differs"] == 0
    assert report["changed_keys"] == {"current_price": 1}
    assert report["same_content_new_id"] == {"count": 1, "examples": [[1003, 1006]]}
    assert report["a"]["distinct_timestamps"] == report["b"]["distinct_timestamps"] == 1
    assert report["a"]["timestamps"] == {TS1: 5} and report["a"]["index"] == NIGHT1
    assert report["terms"] == {"added": {"labor_category": 1, "vendor_name": 1, "idv_piid": 1},
                               "removed": {"labor_category": 1, "vendor_name": 1, "idv_piid": 1}}
    assert report["churn_pct"] == 100.0
    # Per change, the same total as deleting at the switch (47); cleanup just lands a night later.
    split = report["projected_split"]
    assert report["projected_rows_written"] == loader.add_up(split["at_switch"], split["next_switch"])
    assert report["projected_rows_written"]["total"] == 47
    assert (split["at_switch"]["total"], split["next_switch"]["total"]) == (29, 18)
    same = loader.diff(recs[1], recs[2], log=quiet)
    assert same["changed"] == same["added"] == same["removed"] == 0
    assert same["projected_rows_written"]["total"] == same["projected_split"]["at_switch"]["total"] == 8
    # build agrees: the switch to night 2 costs at_switch; the switch to night 3 deletes what
    # night 2 retired (next_switch) on top of its own meta writes.
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    assert loader.build(db, recs[1], log=quiet)["written_estimate"] == split["at_switch"]
    assert loader.build(db, recs[2], log=quiet)["written_estimate"] == loader.add_up(
        split["next_switch"], same["projected_split"]["at_switch"])


def test_diff_key_order_change(tmp_path):
    first = night_one()
    second = {k: dict(reversed(list(dict(v, _timestamp=TS2).items()))) for k, v in first.items()}
    report = loader.diff(write_recording(tmp_path / "a", NIGHT1, first), write_recording(tmp_path / "b", NIGHT2, second),
                         log=quiet)
    assert report["unchanged"] == 5 and report["unchanged_but_key_order_differs"] == 5


def test_cli_diff(recs, tmp_path, capsys):
    out = tmp_path / "diff.json"
    assert loader.main(["diff", "--a", str(recs[0]), "--b", str(recs[1]), "--json", str(out)]) == 0
    assert json.loads(out.read_text())["changed"] == 1
    assert json.loads(capsys.readouterr().out)["added"] == 2


# ---------- refresh ----------

def test_refresh_from_a_recording(recs, tmp_path):
    path = tmp_path / "copy.sqlite"
    db = loader.LocalD1(path)
    assert loader.refresh(db, recs[0], log=quiet)["action"] == "loaded"
    db.rows_written = 0
    status = loader.refresh(db, recs[0], log=quiet)
    assert status["action"] == "unchanged" and db.rows_written == 0 and status["command"] == "refresh"
    status = loader.refresh(db, recs[1], log=quiet)
    assert status["action"] == "loaded" and status["night"] == 2 and meta(db)["version"] == NIGHT2
    out = tmp_path / "status.json"
    assert loader.main(["refresh", "--local", str(path), "--rec", str(recs[1]), "--json", str(out)]) == 0
    assert json.loads(out.read_text())["action"] == "unchanged"
    assert loader.main(["refresh", "--local", str(path), "--rec", str(recs[2]), "--max-rows", "3",
                        "--json", str(out)]) == 2
    assert "passes --max-rows" in json.loads(out.read_text())["stopped"] and meta(db)["current"] == "2"


def test_refresh_checks_gsa_index_before_recording(recs, tmp_path, monkeypatch):
    """Live mode with GSA faked: an unchanged index costs one call and writes nothing."""
    db = loader.LocalD1(":memory:")
    loader.build(db, recs[0], log=quiet)
    calls = []

    def fake_fetch(self, url):
        calls.append(url)
        body = {"hits": {"total": {"value": 5, "relation": "eq"}, "hits": [{"_index": NIGHT1, "_id": "1001",
                "_source": night_one()["1001"]}]}, "aggregations": {"wage_stats": {"count": 5}}}
        return 200, json.dumps(body).encode(), {}

    monkeypatch.setattr(loader.Recorder, "_fetch", fake_fetch)
    monkeypatch.setattr(loader, "record", lambda args: pytest.fail("recorded although the index is unchanged"))
    db.rows_written = 0
    status = loader.refresh(db, work=tmp_path / "work", gap=0, log=quiet)
    assert status["action"] == "unchanged" and len(calls) == 1 and db.rows_written == 0


def test_cli_build_local_json(recs, tmp_path, capsys):
    out = tmp_path / "status.json"
    path = tmp_path / "calc.sqlite"
    assert loader.main(["build", "--local", str(path), "--rec", str(recs[0]), "--json", str(out)]) == 0
    status = json.loads(out.read_text())
    assert {"index", "records", "written_estimate", "seconds", "db_bytes"} <= set(status)
    assert status["db_bytes"] == path.stat().st_size
    assert json.loads(capsys.readouterr().out)["index"] == NIGHT1
