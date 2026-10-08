"""Load the OEWS release bundled with bls-oews-mcp into the hosted D1 database.

The only source is the package's own data directory
(servers/bls-oews-mcp/src/bls_oews_mcp/data/): manifest.json and the gzipped
SQLite file the Python server reads. The file is checked against the
manifest's SHA-256 before anything is written.

Each load writes the release under a new version number, checks its row
counts against the manifest, then points active_release at it in one
statement and deletes older versions. The Worker reads only the active
version, so a failed or interrupted load is never visible; re-running cleans
up the partial version and starts over. When the bundled release is already
active the run changes nothing (--force reloads it).

    python scripts/load_bls_oews.py --local /tmp/bls-oews.sqlite   # tests, parity
    python scripts/load_bls_oews.py --remote --database-id <uuid>  # workflow

Remote mode calls the Cloudflare D1 HTTP API, one statement per request,
with the token in CLOUDFLARE_D1_TOKEN. Statements are plain SQL with quoted
literals (no bound parameters) and stay under D1's 100 KB statement limit.
"""
import argparse, datetime as dt, gzip, hashlib, json, os, shutil, sqlite3, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "servers/bls-oews-mcp/src/bls_oews_mcp/data"
SCHEMA = ROOT / "deploy/bls-oews/schema.sql"
ACCOUNT_ID = "846d3e41e48446abcd3570c0959f9fb5"
API = "https://api.cloudflare.com/client/v4"
# D1 rejects statements over 100,000 bytes; leave room for the statement head.
MAX_STATEMENT_BYTES = 90_000
# Old versions are deleted in key ranges of about this many rows per statement.
DELETE_RANGE_ROWS = 25_000
DATATYPES = [f"{i:02d}" for i in range(1, 18)]
CELL_COLUMNS = ["version", "key", *(f"v{d}" for d in DATATYPES), *(f"f{d}" for d in DATATYPES)]


def quote(value):
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def schema_statements():
    """schema.sql split into single statements (it has no triggers or literals with ';')."""
    lines = [line for line in SCHEMA.read_text().splitlines() if not line.lstrip().startswith("--")]
    return [s.strip() + ";" for s in "\n".join(lines).split(";") if s.strip()]


def insert_statements(table, columns, rows):
    """Multi-row INSERT OR REPLACE statements, each under MAX_STATEMENT_BYTES.

    OR REPLACE makes a retried request harmless: the rows are identical.
    """
    head = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES "
    chunk, size = [], len(head)
    for row in rows:
        values = "(" + ",".join(quote(v) for v in row) + ")"
        if len(values.encode()) + len(head) + 1 > MAX_STATEMENT_BYTES:
            raise SystemExit(f"A {table} row is too large for one D1 statement.")
        if chunk and size + len(values.encode()) + 1 > MAX_STATEMENT_BYTES:
            yield head + ",".join(chunk) + ";"
            chunk, size = [], len(head)
        chunk.append(values)
        size += len(values.encode()) + 1
    if chunk:
        yield head + ",".join(chunk) + ";"


class Bundle:
    """The bundled release, decompressed to a temporary file and verified."""

    def __init__(self, data_dir: Path):
        self.manifest = json.loads((data_dir / "manifest.json").read_text())
        self._tmp = tempfile.TemporaryDirectory(prefix="bls-oews-load-")
        path = Path(self._tmp.name) / "oews.sqlite"
        digest = hashlib.sha256()
        with gzip.open(data_dir / self.manifest["file"], "rb") as gz, path.open("wb") as out:
            for block in iter(lambda: gz.read(1 << 20), b""):
                digest.update(block)
                out.write(block)
        if digest.hexdigest() != self.manifest["database_sha256"]:
            raise SystemExit("The bundled OEWS database does not match its manifest; refusing to load.")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        code = self.con.execute("SELECT value FROM meta WHERE name = 'release_code'").fetchone()
        if not code or code[0] != self.manifest["release"]["code"]:
            raise SystemExit("The bundled OEWS database release does not match its manifest; refusing to load.")

    def close(self):
        self.con.close()
        self._tmp.cleanup()

    def footnotes(self):
        return dict(self.con.execute("SELECT footnote_code, footnote_text FROM footnote ORDER BY footnote_code"))

    def keys(self):
        return [k for (k,) in self.con.execute("SELECT key FROM cell ORDER BY key")]

    def statements(self, version):
        """Every INSERT for one release version: occupations, areas, then cells."""
        cells = self.con.execute(f"SELECT {', '.join(CELL_COLUMNS[1:])} FROM cell ORDER BY key")
        yield from insert_statements("occupation", ["version", "code", "name"],
                                     ((version, c, n) for c, n in self.con.execute(
                                         "SELECT occupation_code, occupation_name FROM occupation ORDER BY occupation_code")))
        yield from insert_statements("area", ["version", "code", "name"],
                                     ((version, c, n) for c, n in self.con.execute(
                                         "SELECT area_code, area_name FROM area ORDER BY area_code")))
        yield from insert_statements("cell", CELL_COLUMNS, ((version, *row) for row in cells))


class LocalD1:
    """A SQLite file standing in for D1 (tests, the parity harness, wrangler dev)."""

    def __init__(self, path: Path):
        self.con = sqlite3.connect(path, isolation_level=None)
        self.con.row_factory = sqlite3.Row

    def query(self, sql):
        return [dict(r) for r in self.con.execute(sql).fetchall()]


class RemoteD1:
    """The Cloudflare D1 HTTP API, one statement per request, with retries."""

    def __init__(self, account_id, database_id, token):
        self.url = f"{API}/accounts/{account_id}/d1/database/{database_id}/query"
        self.token = token

    def query(self, sql):
        body = json.dumps({"sql": sql}).encode()
        for attempt in range(6):
            request = urllib.request.Request(self.url, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "1102tools-bls-oews-loader"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = json.loads(response.read())
                break
            except urllib.error.HTTPError as e:
                detail = e.read()[:500].decode("utf-8", "replace")
                if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise SystemExit(f"D1 API error {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 5:
                    raise SystemExit(f"D1 API unreachable: {e}")
            time.sleep(2 ** attempt)
        if not payload.get("success"):
            raise SystemExit(f"D1 API error: {json.dumps(payload.get('errors'))[:500]}")
        return payload["result"][0].get("results") or []


def delete_version(db, version, keys):
    """Delete one version's rows, cells in key ranges so no statement runs long."""
    bounds = keys[DELETE_RANGE_ROWS::DELETE_RANGE_ROWS]
    ranges = [f"key < {quote(bounds[0])}"] if bounds else ["1 = 1"]
    ranges += [f"key >= {quote(a)} AND key < {quote(b)}" for a, b in zip(bounds, bounds[1:])]
    if bounds:
        ranges.append(f"key >= {quote(bounds[-1])}")
    for clause in ranges:
        db.query(f"DELETE FROM cell WHERE version = {version} AND {clause};")
    db.query(f"DELETE FROM occupation WHERE version = {version};")
    db.query(f"DELETE FROM area WHERE version = {version};")
    db.query(f"DELETE FROM release WHERE version = {version};")


def count(db, table, version):
    return db.query(f"SELECT COUNT(*) AS n FROM {table} WHERE version = {version};")[0]["n"]


def load(db, data_dir=DATA_DIR, force=False, log=lambda message: print(message, file=sys.stderr)):
    bundle = Bundle(data_dir)
    try:
        return _load(db, bundle, force, log)
    finally:
        bundle.close()


def _load(db, bundle, force, log):
    manifest = bundle.manifest
    for statement in schema_statements():
        db.query(statement)
    active = db.query("SELECT r.version, r.database_sha256 FROM active_release a "
                      "JOIN release r ON r.version = a.version WHERE a.id = 1;")
    active = active[0] if active else None
    summary = {"release": manifest["release"]["description"], "data_year": manifest["data_year"],
               "database_sha256": manifest["database_sha256"]}
    if active and active["database_sha256"] == manifest["database_sha256"] and not force:
        log(f"Release {manifest['release']['code']} is already active (version {active['version']}); nothing to do.")
        return {**summary, "status": "unchanged", "version": active["version"]}

    keys = bundle.keys()
    # Remove anything an interrupted earlier load left behind.
    for row in db.query("SELECT version FROM release;"):
        if not active or row["version"] != active["version"]:
            log(f"Removing unfinished version {row['version']}.")
            delete_version(db, row["version"], keys)

    version = db.query("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM release;")[0]["v"]
    loaded_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.query("INSERT INTO release (version, database_sha256, manifest, footnotes, loaded_at) VALUES ("
             f"{version}, {quote(manifest['database_sha256'])}, "
             f"{quote(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')))}, "
             f"{quote(json.dumps(bundle.footnotes(), ensure_ascii=False, separators=(',', ':')))}, "
             f"{quote(loaded_at)});")
    statements = sent_bytes = 0
    started = time.monotonic()
    for statement in bundle.statements(version):
        db.query(statement)
        statements += 1
        sent_bytes += len(statement.encode())
        if statements % 100 == 0:
            log(f"  {statements} statements, {sent_bytes / 1e6:.1f} MB, {time.monotonic() - started:.0f}s")

    expected = {"cell": manifest["counts"]["cells"], "occupation": manifest["counts"]["occupations"],
                "area": manifest["counts"]["areas"]}
    loaded = {table: count(db, table, version) for table in expected}
    if loaded != expected:
        raise SystemExit(f"Version {version} has {loaded} rows but the manifest lists {expected}; "
                         "it stays inactive. Re-run to retry.")

    db.query(f"INSERT INTO active_release (id, version) VALUES (1, {version}) "
             "ON CONFLICT(id) DO UPDATE SET version = excluded.version;")
    log(f"Version {version} ({manifest['release']['code']}) is active.")
    if active:
        delete_version(db, active["version"], keys)
    return {**summary, "status": "loaded", "version": version, "previous_version": active and active["version"],
            "loaded_at": loaded_at, "rows": loaded, "insert_statements": statements, "sql_bytes": sent_bytes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--local", type=Path, metavar="PATH", help="load into this SQLite file")
    target.add_argument("--remote", action="store_true", help="load into the hosted D1 database")
    parser.add_argument("--database-id", default=os.environ.get("BLS_OEWS_D1_DATABASE_ID"),
                        help="D1 database ID (default: $BLS_OEWS_D1_DATABASE_ID)")
    parser.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ACCOUNT_ID)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="bundled data directory (default: the package's)")
    parser.add_argument("--force", action="store_true", help="reload even if this release is already active")
    args = parser.parse_args(argv)

    if args.remote:
        token = os.environ.get("CLOUDFLARE_D1_TOKEN", "").strip()
        if not token:
            raise SystemExit("Set CLOUDFLARE_D1_TOKEN to a Cloudflare API token with D1 edit access.")
        if not args.database_id or args.database_id.startswith("REPLACE_WITH"):
            raise SystemExit("Pass --database-id or set BLS_OEWS_D1_DATABASE_ID.")
        db = RemoteD1(args.account_id, args.database_id, token)
    else:
        db = LocalD1(args.local)
    print(json.dumps(load(db, args.data_dir, args.force), indent=2))


if __name__ == "__main__":
    main()
