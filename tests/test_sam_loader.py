"""Offline cases for the hosted SAM.gov opportunities loader (no wrangler, no network)."""
import csv
import datetime as dt
import importlib.util
import io
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("loader", ROOT / "scripts/load_sam_opportunities.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

TODAY = dt.datetime.now(dt.timezone.utc).date()
FUTURE = (TODAY + dt.timedelta(days=30)).isoformat()
PAST = (TODAY - dt.timedelta(days=3)).isoformat()


def notice(notice_id, **fields):
    row = {column: "" for column in loader.COLUMNS}
    row.update({"NoticeId": notice_id, "Title": f"Notice {notice_id}", "Active": "Yes",
                "PostedDate": "2026-09-01 10:00:00", "Type": "Solicitation", "ArchiveDate": FUTURE})
    row.update(fields)
    return row


def csv_bytes(rows, header=None):
    """Encode like SAM.gov: Windows-1252 text, with raw bytes allowed per field."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header or list(loader.COLUMNS))
    for row in rows:
        writer.writerow([row[c] for c in loader.COLUMNS])
    # Fields are built as latin-1 strings holding the exact source bytes.
    return out.getvalue().encode("latin-1")


class SqliteD1(loader.D1):
    """The loader's D1 interface over an in-memory sqlite3 database."""

    def __init__(self):
        super().__init__("local")
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row

    def query(self, sql):
        return [dict(r) for r in self.db.execute(sql)]

    def execute_file(self, statements):
        self.db.executescript("\n".join(statements))
        self.db.commit()


@pytest.fixture
def d1(monkeypatch):
    db = SqliteD1()
    monkeypatch.setattr(loader, "D1", lambda target: db)
    return db


def load(tmp_path, rows, *args):
    path = tmp_path / "opps.csv"
    path.write_bytes(csv_bytes(rows))
    loader.main(["--local", "--csv", str(path), "--file-date", "2026-09-26", *args])


def status(db):
    return {r["key"]: json.loads(r["value"]) for r in db.query("SELECT key, value FROM load_status")}


def test_text_decoding_mixes_windows_1252_utf8_and_repairs_mojibake():
    assert loader.fix_text("plain") == "plain"
    assert loader.fix_text("Contractor\x92s") == "Contractor’s"  # cp1252 byte
    assert loader.fix_text("Caf\xc3\xa9 \x96 bar") == "Café – bar"  # UTF-8 sequence beside cp1252
    assert loader.fix_text("\xe2\x80\x9cquoted\xe2\x80\x9d") == "“quoted”"
    assert loader.fix_text("don\xc3\xa2\xe2\x82\xac\xe2\x84\xa2t") == "don’t"  # garbled upstream
    assert loader.fix_text("\x81") == "\x81"  # byte undefined in cp1252 falls back to latin-1


def test_set_aside_codes_and_amounts_normalize():
    assert loader.set_aside_code('["SBA"]') == "SBA"
    assert loader.set_aside_code('[""]') is None
    assert loader.set_aside_code("[bad") is None
    assert loader.set_aside_code("8A") == "8A"
    assert loader.set_aside_code("") is None
    assert loader.amount("$1,250,000.50") == 1250000.5
    assert loader.amount("n/a") is None


def test_deadlines_convert_to_utc_with_eastern_default():
    assert loader.utc_deadline("2026-10-01T14:00:00-04:00") == "2026-10-01T18:00:00Z"
    assert loader.utc_deadline("2026-12-31T12:00:00+01:00") == "2026-12-31T11:00:00Z"
    assert loader.utc_deadline("2026-10-01T14:00:00") == "2026-10-01T18:00:00Z"  # EDT
    assert loader.utc_deadline("2026-12-01T14:00:00") == "2026-12-01T19:00:00Z"  # EST
    assert loader.utc_deadline("2026-10-01") == "2026-10-02T03:59:59Z"  # end of day Eastern
    assert loader.utc_deadline("") is None
    assert loader.utc_deadline("TBD") is None


def test_deadlines_without_an_offset_use_the_contracting_office_time_zone():
    # HC101326QA336 (DISA, Scott AFB IL): sam.gov's API gives responseTz America/Chicago.
    rows = [notice("1d5b93726acd4b6ab971f09a16948a67", ResponseDeadLine="2026-10-12T16:00:00", State="IL"),
            notice("449ef17b" + "0" * 24, ResponseDeadLine="2026-10-16T08:00:00", State="CA"),
            notice("fccafe1a" + "0" * 24, ResponseDeadLine="2026-11-05T10:00:00", State="AE"),
            notice("df1edaa1" + "0" * 24, ResponseDeadLine="2026-11-21T21:00:00", State="PA"),
            notice("e" * 32, ResponseDeadLine="2026-10-12T16:00:00", State=""),
            notice("f" * 32, ResponseDeadLine="2026-10-12T16:00:00-04:00", State="IL")]
    parsed, _ = loader.parse(csv_bytes(rows), TODAY.isoformat())
    utc = {i[:8]: r["response_deadline_utc"] for i, r in parsed.items()}
    assert utc == {"1d5b9372": "2026-10-12T21:00:00Z", "449ef17b": "2026-10-16T15:00:00Z",
                   "fccafe1a": "2026-11-05T09:00:00Z", "df1edaa1": "2026-11-22T02:00:00Z",
                   "e" * 8: "2026-10-12T20:00:00Z", "f" * 8: "2026-10-12T20:00:00Z"}


def test_parse_skips_inactive_blank_and_past_archive_notices():
    rows = [
        notice("a" * 32, SetASideCode='["SBA"]', ResponseDeadLine="2026-10-01"),
        notice("b" * 32, Active="No"),
        notice(""),
        notice("c" * 32, ArchiveDate=PAST),
        notice("d" * 32, ArchiveDate=""),
    ]
    parsed, skipped = loader.parse(b"\xef\xbb\xbf" + csv_bytes(rows), TODAY.isoformat())
    assert sorted(parsed) == ["a" * 32, "d" * 32]
    assert skipped == 1
    assert parsed["a" * 32]["set_aside_code"] == "SBA"
    assert parsed["a" * 32]["posted_date"] == "2026-09-01"
    assert parsed["a" * 32]["response_deadline_utc"] == "2026-10-02T03:59:59Z"


def test_earlier_versions_are_flagged_but_separate_awards_are_not():
    rows = [
        notice("a" * 32, **{"Sol#": "W91-26-R-0001", "Sub-Tier": "ARMY", "PostedDate": "2026-08-01 09:00:00"}),
        notice("b" * 32, **{"Sol#": "w91-26-r-0001", "Sub-Tier": "ARMY", "PostedDate": "2026-09-01 09:00:00"}),
        notice("c" * 32, **{"Sol#": "W91-26-R-0001", "Sub-Tier": "NAVY", "PostedDate": "2026-07-01 09:00:00"}),
        notice("d" * 32, **{"Sol#": "47QSMD20R0001", "Type": "Award Notice", "Awardee": "Acme"}),
        notice("e" * 32, **{"Sol#": "47QSMD20R0001", "Type": "Award Notice", "Awardee": "Beta"}),
        notice("f" * 32, **{"Sol#": "47QSMD20R0001", "Type": "Award Notice", "Awardee": "Beta", "PostedDate": "2026-09-02 10:00:00"}),
        notice("1" * 32, **{"Sol#": "47QSMD20R0001", "Type": "Award Notice"}),
        notice("2" * 32, **{"Sol#": "47QSMD20R0001", "Type": "Award Notice"}),
        notice("3" * 32),
        notice("4" * 32),
    ]
    parsed, _ = loader.parse(csv_bytes(rows), TODAY.isoformat())
    stale = sorted(i[0] for i, r in parsed.items() if not r["is_latest"])
    assert stale == ["a", "e"]


def test_separate_notices_of_other_types_sharing_a_solicitation_number_stay_latest():
    # Real cases from the 2026-10-10 file, all latest: true on sam.gov's API.
    tomah = {"Sol#": "36C25227Q0035", "Sub-Tier": "VETERANS AFFAIRS, DEPARTMENT OF", "Office": "252-NETWORK CONTRACT OFFICE 12"}
    wilmington = {"Sol#": "W912PM27BA002", "Sub-Tier": "DEPT OF THE ARMY", "Office": "W074 ENDIST WILMINGTON"}
    rows = [
        # The Tomah solicitation, then a separate presolicitation chain 25-29 minutes later.
        notice("b3bbb65fa234403598d9cceb8f2dfb24", **tomah, Type="Solicitation", BaseType="Solicitation", PostedDate="2026-10-08 09:08:00"),
        notice("7bd34e5ed23844f2aa2487540e9960de", **tomah, Type="Presolicitation", BaseType="Presolicitation", PostedDate="2026-10-08 09:33:30"),
        notice("304e92aa89ac4dbd94107bfe42e95101", **tomah, Type="Presolicitation", BaseType="Presolicitation", PostedDate="2026-10-08 09:37:16"),
        # A consolidation notice, then a presolicitation under the same number.
        notice("60c3f2a8dc834bfb972cf0e1c54536b6", **wilmington, Type="Special Notice", BaseType="Special Notice", PostedDate="2026-10-05 14:21:00"),
        notice("5b2b99c1e01246e4ac13b25f808c66cd", **wilmington, Type="Presolicitation", BaseType="Special Notice", PostedDate="2026-10-05 14:52:19"),
    ]
    parsed, _ = loader.parse(csv_bytes(rows), TODAY.isoformat())
    latest = {i[:8] for i, r in parsed.items() if r["is_latest"]}
    assert latest == {"b3bbb65f", "304e92aa", "60c3f2a8", "5b2b99c1"}  # 7bd34e5e is the earlier presolicitation


def test_new_amendment_flips_the_previous_version(tmp_path, d1):
    original = notice("a" * 32, **{"Sol#": "SOL-9", "PostedDate": "2026-08-01 09:00:00"})
    load(tmp_path, [original], "--allow-small")
    amended = notice("b" * 32, **{"Sol#": "SOL-9", "PostedDate": "2026-09-01 09:00:00"})
    load(tmp_path, [original, amended], "--allow-small")
    s = status(d1)
    assert {k: s[k] for k in ("added", "updated", "latest_versions", "notices")} == {"added": 1, "updated": 1, "latest_versions": 1, "notices": 2}
    assert d1.query("SELECT notice_id, is_latest FROM opportunities ORDER BY notice_id") == [
        {"notice_id": "a" * 32, "is_latest": 0}, {"notice_id": "b" * 32, "is_latest": 1}]


def test_parse_refuses_changed_columns():
    header = list(loader.COLUMNS)
    header[1] = "NoticeTitle"
    with pytest.raises(SystemExit, match="changed the file's columns"):
        loader.parse(csv_bytes([notice("a" * 32)], header=header), TODAY.isoformat())


def test_load_mirrors_file_adds_updates_and_deletes(tmp_path, d1):
    first = [notice("a" * 32, Description="zero trust architecture"), notice("b" * 32), notice("c" * 32)]
    load(tmp_path, first, "--allow-small")
    assert status(d1)["added"] == 3
    assert d1.query("SELECT notice_id FROM opportunities_fts JOIN opportunities o ON o.rowid = opportunities_fts.rowid "
                    "WHERE opportunities_fts MATCH '\"zero trust\"'") == [{"notice_id": "a" * 32}]

    load(tmp_path, first, "--allow-small")
    assert {k: status(d1)[k] for k in ("added", "updated", "removed")} == {"added": 0, "updated": 0, "removed": 0}

    second = [notice("a" * 32, Description="cloud migration"), notice("b" * 32), notice("d" * 32)]
    load(tmp_path, second, "--allow-small")
    s = status(d1)
    assert {k: s[k] for k in ("added", "updated", "removed", "notices")} == {"added": 1, "updated": 1, "removed": 1, "notices": 3}
    assert s["file_date"] == "2026-09-26"
    assert sorted(r["notice_id"] for r in d1.query("SELECT notice_id FROM opportunities")) == ["a" * 32, "b" * 32, "d" * 32]
    # The FTS index follows updates and deletes.
    match = lambda q: d1.query(f"SELECT rowid FROM opportunities_fts WHERE opportunities_fts MATCH '{q}'")
    assert match('"zero trust"') == []
    assert len(match('"cloud migration"')) == 1
    assert d1.query("SELECT COUNT(*) AS n FROM opportunities_fts")[0]["n"] == 3


def test_load_refuses_small_or_shrunken_files(tmp_path, d1, monkeypatch):
    with pytest.raises(SystemExit, match="refusing to load"):
        load(tmp_path, [notice("a" * 32)])
    monkeypatch.setattr(loader, "MIN_ROWS", 1)
    load(tmp_path, [notice(f"{i:032x}") for i in range(10)])
    with pytest.raises(SystemExit, match="database has 10"):
        load(tmp_path, [notice(f"{i:032x}") for i in range(5)])
    assert d1.query("SELECT COUNT(*) AS n FROM opportunities")[0]["n"] == 10


def test_chunks_split_statements_by_size(monkeypatch):
    monkeypatch.setattr(loader, "SQL_CHUNK_BYTES", 10)
    assert list(loader.chunks(["aaaa", "bbbb", "cccc"])) == [["aaaa", "bbbb"], ["cccc"]]
    assert list(loader.chunks([])) == []
