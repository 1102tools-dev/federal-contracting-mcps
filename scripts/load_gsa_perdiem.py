"""Load the gsa-perdiem-mcp package's bundled GSA files into the hosted D1 database.

The package's data directory (manifest.json, fyYYYY.json.gz, places.json.gz)
is the single source of truth: the Python server reads those files, and the
hosted Worker reads the same content from D1. Each source file becomes an
immutable "part" named by a hash of the file. A load writes the parts that
are missing, checks their row counts, and only then repoints the one-row
release table at them in a single statement, so readers move from one
complete release to the next and never see a half-loaded one. Re-running is
safe: a finished load is a no-op, and an interrupted one resumes. Parts of
the previous release are kept until the next load, then removed.

    python scripts/load_gsa_perdiem.py --local perdiem.sqlite      # tests, parity
    python scripts/load_gsa_perdiem.py --remote --database-id ID    # production

Remote mode uses the Cloudflare D1 HTTP API with the API token in
CLOUDFLARE_D1_TOKEN; the database id comes from --database-id or
GSA_PERDIEM_D1_DATABASE_ID. Prints a JSON summary on stdout.
"""
from __future__ import annotations

import argparse, datetime as dt, gzip, hashlib, json, os, sqlite3, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "servers/gsa-perdiem-mcp/src/gsa_perdiem_mcp/data"
SCHEMA = ROOT / "deploy/gsa-perdiem/schema.sql"
ACCOUNT_ID = "846d3e41e48446abcd3570c0959f9fb5"
# Bump when the stored layout of a part changes, so every part is rewritten.
LAYOUT = 1
# D1 limits: 100 KB per SQL statement, 100 bound parameters. Rows are written
# as literals in multi-row INSERTs kept under STATEMENT_BYTES.
STATEMENT_BYTES = 90_000
REQUEST_BYTES = 900_000
# Refuse obviously broken data rather than replacing a good release with it.
MIN_ZIPS = 30_000
MIN_PLACES = 30_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quote(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if "\x00" in text:
        raise SystemExit("Refusing to load a NUL character")
    return "'" + text.replace("'", "''") + "'"


def compact(value) -> str:
    # Floats keep their decimal point (16.0), so the Worker can tell them from
    # integers exactly as Python does when it reads the same file.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def year_source(fiscal_year: int, meta: dict) -> dict:
    """The source block snapshot.load_year() attaches to bundled results, in its key order."""
    return {
        "kind": "bundled_gsa_files",
        "fiscal_year": fiscal_year,
        "zip_file": meta["zip"]["url"],
        "zip_file_published": meta["zip"].get("published"),
        "zip_file_sha256": meta["zip"]["sha256"],
        "rate_file": meta["rates"]["url"],
        "mie_file": meta["mie"]["url"],
        "mie_file_covers": meta["mie"].get("covers"),
    }


class Part:
    def __init__(self, name, kind, source, raw, tables):
        self.name = name                       # key in release.parts
        self.kind = kind
        self.source = source
        self.id = sha256(f"{LAYOUT}\0".encode() + raw)[:16]
        self.tables = tables                   # {table: [(columns...), ...]}

    @property
    def expected_rows(self):
        return sum(len(rows) for rows in self.tables.values())


def read_parts(data: Path = DATA):
    """Parse the bundled files into parts. Returns (manifest text, manifest, parts)."""
    manifest_text = (data / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    parts = []
    for fy_text, meta in sorted(manifest["fiscal_years"].items()):
        fiscal_year = int(fy_text)
        raw = (data / meta["file"]).read_bytes()
        if sha256(raw) != meta["file_sha256"]:
            raise SystemExit(f"{meta['file']} does not match manifest.json; rebuild the package data")
        year = json.loads(gzip.decompress(raw))
        if year.get("fiscal_year") != fiscal_year or year.get("schema") != 1:
            raise SystemExit(f"{meta['file']}: unexpected fiscal year or schema")
        zips = year.pop("zips")
        if len(zips) < MIN_ZIPS:
            raise SystemExit(f"{meta['file']} lists only {len(zips)} ZIP codes; refusing to load")
        year["source"] = year_source(fiscal_year, meta)
        part = Part(f"fy{fiscal_year}", "year", meta["file"], raw, {})
        part.tables = {
            "years": [(part.id, fiscal_year, compact(year))],
            "zips": [(part.id, z, compact(entries)) for z, entries in sorted(zips.items())],
        }
        parts.append(part)
    raw = (data / "places.json.gz").read_bytes()
    if manifest.get("places_sha256") and sha256(raw) != manifest["places_sha256"]:
        raise SystemExit("places.json.gz does not match manifest.json; rebuild the package data")
    places = json.loads(gzip.decompress(raw))
    if len(places) < MIN_PLACES:
        raise SystemExit(f"places.json.gz lists only {len(places)} names; refusing to load")
    part = Part("places", "places", "places.json.gz", raw, {})
    part.tables = {"places": [(part.id, k, compact(v)) for k, v in sorted(places.items())]}
    parts.append(part)
    return manifest_text, manifest, parts


COLUMNS = {"years": ("part", "fiscal_year", "data"), "zips": ("part", "zip", "entries"),
           "places": ("part", "key", "hits")}


def insert_statements(table, rows):
    """Multi-row INSERTs under the D1 statement limit. Existing rows are kept,
    so a resumed load only writes what an interrupted one missed."""
    head = f"INSERT INTO {table} ({', '.join(COLUMNS[table])}) VALUES "
    tail = " ON CONFLICT DO NOTHING;"
    values, size = [], len(head) + len(tail)
    for row in rows:
        literal = "(" + ", ".join(quote(v) for v in row) + ")"
        if len(head) + len(literal) + len(tail) > STATEMENT_BYTES:
            raise SystemExit(f"A {table} row is larger than D1's statement limit; split it")
        if values and size + len(literal) + 1 > STATEMENT_BYTES:
            yield head + ",".join(values) + tail
            values, size = [], len(head) + len(tail)
        values.append(literal)
        size += len(literal) + 1
    if values:
        yield head + ",".join(values) + tail


class LocalD1:
    """A plain SQLite file with the D1 schema, for tests and the parity harness."""

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.requests = 0

    def execute(self, statements):
        self.requests += 1
        with self.db:
            for statement in statements:
                self.db.execute(statement)

    def script(self, sql):
        self.requests += 1
        self.db.executescript(sql)

    def query(self, sql, params=()):
        self.requests += 1
        return [dict(r) for r in self.db.execute(sql, params)]


class RemoteD1:
    """The Cloudflare D1 HTTP API (POST .../d1/database/{id}/query)."""

    def __init__(self, database_id, token, account_id=ACCOUNT_ID):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.token = token
        self.requests = 0

    def _post(self, body):
        data = json.dumps(body).encode()
        for attempt in range(6):
            self.requests += 1
            request = urllib.request.Request(self.url, data=data, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "1102tools-gsa-perdiem-loader"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = json.loads(response.read())
            except urllib.error.HTTPError as error:
                detail = error.read()[:500].decode("utf-8", "replace")
                if error.code in (429, 500, 502, 503, 504) and attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                raise SystemExit(f"D1 API HTTP {error.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                raise SystemExit(f"D1 API unreachable: {error}") from None
            if not payload.get("success"):
                raise SystemExit(f"D1 API error: {json.dumps(payload.get('errors'))[:500]}")
            return payload["result"]
        raise AssertionError("unreachable")

    def execute(self, statements):
        # Several statements per request, run by D1 as one batch.
        self._post({"sql": "\n".join(statements)})

    def script(self, sql):
        self._post({"sql": sql})

    def query(self, sql, params=()):
        return self._post({"sql": sql, "params": list(params)})[0]["results"]


def requests_of(statements):
    batch, size = [], 0
    for statement in statements:
        if batch and size + len(statement) > REQUEST_BYTES:
            yield batch
            batch, size = [], 0
        batch.append(statement)
        size += len(statement) + 1
    if batch:
        yield batch


def count_rows(db, part):
    tables = list(part.tables)
    sql = "SELECT " + " + ".join(f"(SELECT COUNT(*) FROM {t} WHERE part = ?)" for t in tables) + " AS n"
    return db.query(sql, [part.id] * len(tables))[0]["n"]


def load(db, data: Path = DATA, now=None):
    """Make the database's active release match the bundled files. Returns a summary."""
    manifest_text, manifest, parts = read_parts(data)
    target = {p.name: p.id for p in parts}
    release_id = sha256((manifest_text + compact(target)).encode())[:16]
    db.script(SCHEMA.read_text())
    current = db.query("SELECT release, parts, previous_parts FROM release WHERE id = 1")
    summary = {"release": release_id, "parts": target,
               "rows": {p.name: p.expected_rows for p in parts}, "written_parts": []}
    if current and current[0]["release"] == release_id:
        summary["status"] = "already_current"
        return summary

    done = {r["part"]: r for r in db.query("SELECT part, expected_rows, complete FROM parts")}
    for part in parts:
        if done.get(part.id, {}).get("complete"):
            continue
        db.execute([f"INSERT INTO parts (part, kind, source, expected_rows, complete) VALUES "
                    f"({quote(part.id)}, {quote(part.kind)}, {quote(part.source)}, {part.expected_rows}, 0) "
                    "ON CONFLICT(part) DO NOTHING;"])
        statements = [s for table, rows in part.tables.items() for s in insert_statements(table, rows)]
        for batch in requests_of(statements):
            db.execute(batch)
        found = count_rows(db, part)
        if found != part.expected_rows:
            raise SystemExit(f"{part.source}: wrote {found} rows, expected {part.expected_rows}; "
                             "the release was not switched. Re-run to resume.")
        db.execute([f"UPDATE parts SET complete = 1 WHERE part = {quote(part.id)};"])
        summary["written_parts"].append(part.name)

    # One statement switches readers to the new release.
    loaded_at = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute([
        "INSERT INTO release (id, release, manifest, parts, previous_parts, loaded_at) VALUES "
        f"(1, {quote(release_id)}, {quote(manifest_text)}, {quote(compact(target))}, '{{}}', {quote(loaded_at)}) "
        "ON CONFLICT(id) DO UPDATE SET release = excluded.release, manifest = excluded.manifest, "
        "parts = excluded.parts, previous_parts = release.parts, loaded_at = excluded.loaded_at;"])

    # Drop parts that neither this release nor the previous one uses.
    row = db.query("SELECT parts, previous_parts FROM release WHERE id = 1")[0]
    keep = set(json.loads(row["parts"]).values()) | set(json.loads(row["previous_parts"]).values())
    removed = []
    for stale in db.query("SELECT part FROM parts"):
        part_id = stale["part"]
        if part_id in keep:
            continue
        db.execute([f"DELETE FROM {t} WHERE part = {quote(part_id)};" for t in ("years", "zips", "places")]
                   + [f"DELETE FROM parts WHERE part = {quote(part_id)};"])
        removed.append(part_id)
    summary.update(status="loaded", loaded_at=loaded_at, removed_parts=removed,
                   fiscal_years=sorted(int(y) for y in manifest["fiscal_years"]))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--local", type=Path, metavar="SQLITE", help="load into this SQLite file")
    target.add_argument("--remote", action="store_true", help="load into the production D1 database")
    parser.add_argument("--database-id", default=os.environ.get("GSA_PERDIEM_D1_DATABASE_ID"),
                        help="D1 database id (default: GSA_PERDIEM_D1_DATABASE_ID)")
    parser.add_argument("--data", type=Path, default=DATA, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.local:
        db = LocalD1(args.local)
    else:
        token = os.environ.get("CLOUDFLARE_D1_TOKEN", "").strip()
        if not token:
            raise SystemExit("Set CLOUDFLARE_D1_TOKEN to a Cloudflare API token with D1 edit access")
        if not args.database_id or args.database_id.startswith("REPLACE_"):
            raise SystemExit("Pass --database-id or set GSA_PERDIEM_D1_DATABASE_ID")
        db = RemoteD1(args.database_id, token, os.environ.get("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID))
    summary = load(db, args.data)
    summary["requests"] = db.requests
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
