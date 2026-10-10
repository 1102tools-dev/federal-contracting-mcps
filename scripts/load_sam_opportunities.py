"""Mirror SAM.gov's public contract opportunities file into the hosted D1 database.

SAM.gov publishes ContractOpportunitiesFullCSV.csv daily without a key. It is a
full list of every active notice, not a daily delta, so each run makes D1 match
the file: new notices are inserted, changed notices updated, and notices no
longer in the file (archived by SAM.gov) deleted. Notices already past their
archive date are skipped even if the file still lists them.

The file also lists every earlier version of a notice (each amendment is its
own row, still marked active), so each row is flagged is_latest; the tools
show only the latest version by default.

    python scripts/load_sam_opportunities.py --remote            # nightly job
    python scripts/load_sam_opportunities.py --local --csv f.csv  # wrangler dev

Only changed rows are written. The run aborts before writing if the file's
columns change or it holds far fewer notices than the database.
"""
import argparse, codecs, csv, datetime as dt, hashlib, io, json, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "deploy/sam-gov"
DATABASE = "sam-gov-opportunities"
SOURCE_URL = ("https://sam.gov/api/prod/fileextractservices/v1/api/download/"
              "Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv?privacy=Public")
# Refuse to replace the table with a file this much smaller than what is loaded.
MIN_KEEP_RATIO = 0.6
MIN_ROWS = 20000
SQL_CHUNK_BYTES = 20_000_000
DELETE_BATCH = 500
PAGE = 20000

# Source column -> D1 column. None means the column is read but not stored.
COLUMNS = {
    "NoticeId": "notice_id", "Title": "title", "Sol#": "solicitation_number",
    "Department/Ind.Agency": "department", "CGAC": "cgac", "Sub-Tier": "sub_tier",
    "FPDS Code": "fpds_code", "Office": "office", "AAC Code": "aac_code",
    "PostedDate": "posted_at", "Type": "notice_type", "BaseType": "base_type",
    "ArchiveType": "archive_type", "ArchiveDate": "archive_date",
    "SetASideCode": "set_aside_code", "SetASide": "set_aside",
    "ResponseDeadLine": "response_deadline", "NaicsCode": "naics_code",
    "ClassificationCode": "psc_code", "PopStreetAddress": "pop_street", "PopCity": "pop_city",
    "PopState": "pop_state", "PopZip": "pop_zip", "PopCountry": "pop_country", "Active": None,
    "AwardNumber": "award_number", "AwardDate": "award_date", "Award$": "award_amount",
    "Awardee": "awardee", "PrimaryContactTitle": "primary_contact_title",
    "PrimaryContactFullname": "primary_contact_name", "PrimaryContactEmail": "primary_contact_email",
    "PrimaryContactPhone": "primary_contact_phone", "PrimaryContactFax": "primary_contact_fax",
    "SecondaryContactTitle": "secondary_contact_title",
    "SecondaryContactFullname": "secondary_contact_name",
    "SecondaryContactEmail": "secondary_contact_email",
    "SecondaryContactPhone": "secondary_contact_phone", "SecondaryContactFax": "secondary_contact_fax",
    "OrganizationType": "organization_type", "State": "office_state", "City": "office_city",
    "ZipCode": "office_zip", "CountryCode": "office_country",
    "AdditionalInfoLink": "additional_info_link", "Link": None, "Description": "description",
}
FIELDS = [c for c in COLUMNS.values() if c] + ["posted_date", "response_deadline_utc", "is_latest"]

EASTERN = ZoneInfo("America/New_York")
# Contracting office state -> time zone, for deadlines published without one.
# sam.gov's API carries the zone (responseTz); the file does not.
OFFICE_ZONES = {
    "America/New_York": {"CT", "DC", "DE", "FL", "GA", "IN", "KY", "MA", "MD", "ME", "MI", "NC", "NH", "NJ",
                         "NY", "OH", "PA", "RI", "SC", "VA", "VT", "WV"},
    "America/Chicago": {"AL", "AR", "IA", "IL", "KS", "LA", "MN", "MO", "MS", "ND", "NE", "OK", "SD", "TN",
                        "TX", "WI"},
    "America/Denver": {"CO", "ID", "MT", "NM", "UT", "WY"},
    "America/Phoenix": {"AZ"},
    "America/Los_Angeles": {"CA", "NV", "OR", "WA"},
    "America/Anchorage": {"AK"},
    "Pacific/Honolulu": {"HI"},
    "America/Puerto_Rico": {"PR", "VI"},
    "Pacific/Guam": {"GU", "MP"},
    "Europe/Berlin": {"AE"},  # Armed Forces Europe; DISA/DITCO Europe deadlines are Europe/Berlin
}
UTF8_SEQUENCE = re.compile(rb"[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3}")
MOJIBAKE = [("â€™", "’"), ("â€˜", "‘"), ("â€œ", "“"), ("â€?", "”"), ("â€“", "–"), ("â€”", "—"),
            ("â€¢", "•"), ("â€¦", "…"), ("Â§", "§"), ("Â°", "°"), ("Â®", "®"), ("Â ", " ")]
codecs.register_error("sam_latin1", lambda e: (e.object[e.start:e.end].decode("latin-1"), e.end))


def fix_text(value):
    """The file is mostly Windows-1252, but some fields mix in UTF-8 sequences.

    Decode valid UTF-8 sequences as UTF-8 and every other byte as Windows-1252.
    """
    if value.isascii():
        return value
    raw, out, last = value.encode("latin-1"), [], 0
    for match in UTF8_SEQUENCE.finditer(raw):
        out.append(raw[last:match.start()].decode("cp1252", errors="sam_latin1"))
        try:
            out.append(match.group().decode("utf-8"))
        except UnicodeDecodeError:
            out.append(match.group().decode("cp1252", errors="sam_latin1"))
        last = match.end()
    out.append(raw[last:].decode("cp1252", errors="sam_latin1"))
    text = "".join(out)
    # Some notices arrive already garbled upstream (UTF-8 punctuation read as
    # Windows-1252, with undefined bytes replaced by '?'). Repair the common ones.
    for garbled, fixed in MOJIBAKE:
        text = text.replace(garbled, fixed)
    return text


def office_zone(state):
    """Time zone of a contracting office's state (most of the state, where it
    has two), or None when unknown."""
    for zone, states in OFFICE_ZONES.items():
        if state in states:
            return ZoneInfo(zone)
    return None


def utc_deadline(value, office_state=None):
    """UTC timestamp for comparisons. The file drops the time zone from some
    deadlines; those are read in the contracting office's time zone (Eastern
    when the office state is unknown), and date-only deadlines as the end of
    that day."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if len(value) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=office_zone(office_state) or EASTERN)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(value):
    return value[:10] if value and re.match(r"\d{4}-\d{2}-\d{2}", value) else None


def set_aside_code(value):
    # A few rows carry JSON-looking codes such as ["SBA"] or [""].
    if value and value.startswith("["):
        try:
            codes = [c for c in json.loads(value) if c]
        except ValueError:
            codes = []
        value = codes[0] if codes else None
    return value or None


def amount(value):
    if not value:
        return None
    try:
        return float(value.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def normalize(source):
    row = {}
    for column, field in COLUMNS.items():
        if field:
            text = fix_text(source[column]).replace("\r\n", "\n").replace("\x00", "").strip()
            row[field] = text or None
    row["posted_date"] = day(row["posted_at"])
    row["archive_date"] = day(row["archive_date"])
    row["award_date"] = day(row["award_date"])
    row["award_amount"] = amount(row["award_amount"])
    row["set_aside_code"] = set_aside_code(row["set_aside_code"])
    row["response_deadline_utc"] = utc_deadline(row["response_deadline"], row["office_state"])
    return row


def version_key(row):
    """Rows sharing a key are versions of one notice. Versions share a
    solicitation number, sub-tier, and notice type: offices often post a
    solicitation, presolicitation, or special notice as separate current
    notices under one number, and the file has no link between versions.
    Award notices must also share the award number and awardee, since one
    solicitation can have thousands of awards."""
    if not row["solicitation_number"]:
        return None
    key = (row["solicitation_number"].upper(), row["sub_tier"], row["notice_type"])
    if row["notice_type"] == "Award Notice":
        if not (row["award_number"] or row["awardee"]):
            return None
        key += (row["award_number"], row["awardee"])
    return key


def mark_latest(rows):
    """Flag the most recently posted version of each notice and hash every row."""
    latest = {}
    for row in rows.values():
        key = version_key(row)
        if key is not None:
            rank = (row["posted_at"] or "", row["notice_id"])
            if key not in latest or rank > latest[key][0]:
                latest[key] = (rank, row["notice_id"])
    newest = {notice_id for _, notice_id in latest.values()}
    for row in rows.values():
        row["is_latest"] = 1 if version_key(row) is None or row["notice_id"] in newest else 0
        row["row_hash"] = hashlib.sha256(json.dumps([row[f] for f in FIELDS]).encode()).hexdigest()
    return rows


def parse(raw, today):
    """Return (rows by notice ID, count skipped as past their archive date)."""
    text = raw.decode("latin-1")
    if text.startswith("\xef\xbb\xbf"):
        text = text[3:]
    csv.field_size_limit(sys.maxsize)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != list(COLUMNS):
        raise SystemExit(f"SAM.gov changed the file's columns; review before loading: {reader.fieldnames}")
    rows, skipped = {}, 0
    for source in reader:
        if source["Active"] != "Yes" or not source["NoticeId"]:
            continue
        row = normalize(source)
        if row["archive_date"] and row["archive_date"] < today:
            skipped += 1
            continue
        rows[row["notice_id"]] = row
    return mark_latest(rows), skipped


def download():
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "1102tools-sam-loader"})
    with urllib.request.urlopen(request, timeout=600) as response:
        modified = response.headers.get("Last-Modified")
        raw = response.read()
    file_date = (dt.datetime.strptime(modified, "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
                 if modified else dt.date.today().isoformat())
    return raw, file_date


def quote(value):
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def upsert_sql(row):
    columns = FIELDS + ["row_hash"]
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "notice_id")
    return (f"INSERT INTO opportunities ({', '.join(columns)}) VALUES "
            f"({', '.join(quote(row[c]) for c in columns)}) "
            f"ON CONFLICT(notice_id) DO UPDATE SET {updates};")


def plan(rows, existing):
    """Statements that make the table match rows, plus change counts."""
    added = [r for i, r in rows.items() if i not in existing]
    changed = [r for i, r in rows.items() if i in existing and existing[i] != r["row_hash"]]
    removed = sorted(set(existing) - set(rows))
    statements = [upsert_sql(r) for r in added + changed]
    for start in range(0, len(removed), DELETE_BATCH):
        ids = ", ".join(quote(i) for i in removed[start:start + DELETE_BATCH])
        statements.append(f"DELETE FROM opportunities WHERE notice_id IN ({ids});")
    return statements, {"added": len(added), "updated": len(changed), "removed": len(removed)}


def status_sql(status):
    return [f"INSERT INTO load_status (key, value) VALUES ({quote(k)}, {quote(json.dumps(v))}) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value;" for k, v in status.items()]


def chunks(statements):
    chunk, size = [], 0
    for statement in statements:
        if chunk and size + len(statement) > SQL_CHUNK_BYTES:
            yield chunk
            chunk, size = [], 0
        chunk.append(statement)
        size += len(statement) + 1
    if chunk:
        yield chunk


class D1:
    """Runs SQL through wrangler so local and remote loads share one path."""

    def __init__(self, target):
        self.target = target

    def run(self, *args, capture=False):
        cmd = ["npx", "--no-install", "wrangler", "d1", "execute", DATABASE, f"--{self.target}", "--yes", *args]
        result = subprocess.run(cmd, cwd=WORKER_DIR, check=True, text=True,
                                stdout=subprocess.PIPE if capture else sys.stderr)
        return result.stdout

    def query(self, sql):
        return json.loads(self.run("--json", "--command", sql, capture=True))[0]["results"]

    def execute_file(self, statements):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", encoding="utf-8") as f:
            f.write("\n".join(statements))
            f.flush()
            self.run("--file", f.name)

    def existing_hashes(self):
        hashes, last = {}, 0
        while True:
            page = self.query(f"SELECT rowid, notice_id, row_hash FROM opportunities WHERE rowid > {last} "
                              f"ORDER BY rowid LIMIT {PAGE}")
            hashes.update((r["notice_id"], r["row_hash"]) for r in page)
            if len(page) < PAGE:
                return hashes
            last = page[-1]["rowid"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--remote", action="store_const", dest="target", const="remote")
    target.add_argument("--local", action="store_const", dest="target", const="local")
    parser.add_argument("--csv", type=Path, help="load this file instead of downloading")
    parser.add_argument("--file-date", help="YYYY-MM-DD date of --csv (default: today)")
    parser.add_argument("--allow-small", action="store_true", help="skip the minimum row check (fixtures)")
    args = parser.parse_args(argv)

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if args.csv:
        raw, file_date = args.csv.read_bytes(), args.file_date or today
    else:
        raw, file_date = download()
    rows, skipped = parse(raw, today)
    if len(rows) < MIN_ROWS and not args.allow_small:
        raise SystemExit(f"Only {len(rows)} active notices in the file; refusing to load.")

    db = D1(args.target)
    db.execute_file([(WORKER_DIR / "schema.sql").read_text()])
    existing = db.existing_hashes()
    if existing and len(rows) < MIN_KEEP_RATIO * len(existing) and not args.allow_small:
        raise SystemExit(f"File has {len(rows)} notices but the database has {len(existing)}; refusing to load.")

    statements, counts = plan(rows, existing)
    types = {}
    for row in rows.values():
        if row["is_latest"]:
            types[row["notice_type"] or "Unknown"] = types.get(row["notice_type"] or "Unknown", 0) + 1
    status = {"file_date": file_date, "loaded_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "source_url": SOURCE_URL, "notices": len(rows),
              "latest_versions": sum(r["is_latest"] for r in rows.values()), "skipped_past_archive_date": skipped,
              "by_notice_type": dict(sorted(types.items(), key=lambda kv: -kv[1])), **counts}
    for chunk in chunks(statements):
        db.execute_file(chunk)
    db.execute_file(status_sql(status))
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
