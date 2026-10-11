"""Publish a completed parsed SQLite snapshot to existing Acquisition.gov D1.

Run on the Mac or in GitHub Actions, with the Cloudflare token in the environment.
The source may be copied from the separate Dell raw-cache workspace; raw files
and cache metadata are never read or uploaded. The Worker schema is unchanged.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

import load_acquisition_gov as loader

TABLES = {
    "docs": ("id", "kind", "info"),
    "chunks": ("doc", "stream", "seq", "start", "length", "body"),
    "headings": ("doc", "idx", "key", "start", "end"),
    "pages": ("doc", "page", "seq", "start", "length", "failure", "over_cap", "applicability", "body"),
    "index_parts": ("doc", "ordinal", "part", "updated_date", "deviations", "item"),
    "index_deviations": ("doc", "seq", "part", "agency", "source_id", "url", "item"),
}
SOURCE_COLUMNS = ("snapshot", "key", "url", "final_url", "source_id", "retrieved_at", "content_sha256", "error", "doc")


class PublisherD1(loader.RemoteD1):
    """Keep the serialized API request bounded, including JSON escaping."""

    def execute(self, statements):
        batch = []
        for statement in statements:
            if len(statement.encode("utf-8")) > loader.STATEMENT_BYTES:
                raise ValueError("Publisher SQL statement exceeds its byte limit.")
            candidate = batch + [statement]
            if batch and len(json.dumps({"sql": "\n".join(candidate)}).encode()) > loader.REQUEST_BYTES:
                self._post({"sql": "\n".join(batch)})
                batch = []
            batch.append(statement)
            if len(json.dumps({"sql": "\n".join(batch)}).encode()) > loader.REQUEST_BYTES:
                raise ValueError("Publisher SQL request exceeds its byte limit.")
        if batch:
            self._post({"sql": "\n".join(batch)})


def fingerprint(rows, columns):
    """Order-independent digest of the complete stored shape, including text."""
    encoded = sorted(json.dumps([r[c] for c in columns], ensure_ascii=False, separators=(",", ":")) for r in rows)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def document_rows(db, table, ids):
    column = "id" if table == "docs" else "doc"
    return db.query(f"SELECT {', '.join(TABLES[table])} FROM {table} WHERE {column} IN ({','.join('?' for _ in ids)})", ids)


def all_document_rows(db, ids):
    """One API round trip for six verification queries; retain offline adapters."""
    if not isinstance(db, loader.RemoteD1):
        return {table: document_rows(db, table, ids) for table in TABLES}
    statements = [f"SELECT {', '.join(columns)} FROM {table} WHERE {'id' if table == 'docs' else 'doc'} IN ({','.join(loader.quote(doc) for doc in ids)});"
                  for table, columns in TABLES.items()]
    result = db._post({"sql": "\n".join(statements)})
    if len(result) != len(TABLES) or any(item.get("success") is False for item in result):
        raise loader.Abort("D1 document verification query failed.")
    return {table: item["results"] for table, item in zip(TABLES, result)}


class ReadOnlySnapshot:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        # Hold a consistent view even if a new local load starts during upload.
        self.db.execute("BEGIN")

    def query(self, sql, params=()):
        return [dict(row) for row in self.db.execute(sql, params)]


def validate_local(local):
    current = local.query("SELECT value FROM meta WHERE key='current'")
    if not current:
        raise loader.Abort("Local snapshot has no current generation.")
    snapshot = int(current[0]["value"])
    metadata = local.query("SELECT * FROM snapshots WHERE id=?", [snapshot])
    if not metadata or not metadata[0]["completed_at"] or not metadata[0]["stats"]:
        raise loader.Abort("Local snapshot is incomplete.")
    sources = local.query("SELECT * FROM sources WHERE snapshot=?", [snapshot])
    by_key = {row["key"]: row for row in sources}
    expected = {"index", *(f"part:{n}" for n in loader.PARTS), *(f"guidance:{n}" for n in loader.constants.GUIDANCE_URLS)}
    index = by_key.get("index")
    if not index or index["error"] or not index["doc"]:
        raise loader.Abort("Local snapshot has no usable index.")
    docs = local.query("SELECT * FROM docs WHERE id=?", [index["doc"]])
    if not docs or docs[0]["kind"] != "index" or json.loads(docs[0]["info"]).get("error"):
        raise loader.Abort("Local index document is missing or unusable.")
    urls = {r["url"] for r in local.query("SELECT url FROM index_deviations WHERE doc=?", [index["doc"]])}
    parts = local.query("SELECT part FROM index_parts WHERE doc=?", [index["doc"]])
    if not parts:
        raise loader.Abort("Local index has no parts.")
    expected |= {f"pdf:{url}" for url in urls}
    if expected != set(by_key):
        raise loader.Abort(f"Local snapshot source coverage differs from its index: {len(expected - set(by_key))} missing, {len(set(by_key) - expected)} extra.")
    for source in sources:
        if bool(source["error"]) == bool(source["doc"]):
            raise loader.Abort(f"Source must have either a parsed document or an explicit fetch error: {source['key']}")
        if source["doc"] and not local.query("SELECT id FROM docs WHERE id=?", [source["doc"]]):
            raise loader.Abort(f"Source document is missing: {source['key']}")
    return snapshot, metadata[0], sources, index["doc"], urls


def publish(local, remote, log=print):
    started = time.monotonic()
    original, metadata, sources, index_doc, urls = validate_local(local)
    current_rows = remote.query("SELECT value FROM meta WHERE key='current'")
    current = current_rows[0]["value"] if current_rows else None
    if current is not None:
        old = remote.query("SELECT COUNT(*) AS n FROM sources WHERE snapshot=? AND key LIKE 'pdf:%'", [int(current)])[0]["n"]
        if old and len(urls) < loader.MIN_KEEP_RATIO * old:
            raise loader.Abort(f"Local index shrank to {len(urls)} PDFs from {old}; not publishing.")
    staging = remote.query("SELECT COALESCE(MAX(id),0)+1 AS id FROM snapshots")[0]["id"]
    # INSERT, never replacement: concurrent allocation must fail closed.
    remote.execute([f"INSERT INTO snapshots (id,started_at) VALUES ({staging},{loader.quote(dt.datetime.now(dt.timezone.utc).isoformat())});"])
    ids = sorted({r["doc"] for r in sources if r["doc"]})
    for start in range(0, len(ids), 10):
        batch = ids[start:start + 10]
        existing = {r["id"] for r in document_rows(remote, "docs", batch)}
        new = [doc for doc in batch if doc not in existing]
        existing_rows = all_document_rows(remote, sorted(existing)) if existing else {}
        for table, columns in TABLES.items():
            # Existing content IDs must match every parsed row. Never replace
            # documents reachable by the current serving generation.
            if existing and fingerprint(document_rows(local, table, sorted(existing)), columns) != fingerprint(existing_rows[table], columns):
                raise loader.Abort(f"Existing parsed document differs in {table}; not publishing.")
        if new:
            # Clear only uncommitted documents (docs is the completion marker).
            # This also repairs rows left by an interrupted previous upload.
            statements = []
            for table in TABLES:
                if table != "docs":
                    statements.append(f"DELETE FROM {table} WHERE doc IN ({','.join(loader.quote(d) for d in new)}) AND doc NOT IN (SELECT id FROM docs);")
            for table in [t for t in TABLES if t != "docs"] + ["docs"]:
                columns = TABLES[table]
                rows = document_rows(local, table, new)
                # A nightly loader may have completed this same content ID
                # since our query. Do not replace any of its rows; the complete
                # verification below rejects differences rather than changing
                # content potentially reachable by serving readers.
                statements += [statement.replace("INSERT OR REPLACE INTO", "INSERT OR IGNORE INTO", 1)
                               for statement in loader.inserts(table, list(columns), [[r[c] for c in columns] for r in rows])]
            remote.execute(statements)
        uploaded_rows = all_document_rows(remote, batch)
        for table, columns in TABLES.items():
            if fingerprint(document_rows(local, table, batch), columns) != fingerprint(uploaded_rows[table], columns):
                raise loader.Abort(f"Upload verification failed for {table}; current snapshot is unchanged.")
        log(f"verified {min(start + 10, len(ids))}/{len(ids)} parsed documents")
    remapped = [{**row, "snapshot": staging} for row in sources]
    remote.execute(loader.inserts("sources", list(SOURCE_COLUMNS), [[r[c] for c in SOURCE_COLUMNS] for r in remapped]))
    uploaded = remote.query("SELECT * FROM sources WHERE snapshot=?", [staging])
    if fingerprint(uploaded, SOURCE_COLUMNS) != fingerprint(remapped, SOURCE_COLUMNS):
        raise loader.Abort("Source upload verification failed; current snapshot is unchanged.")
    stats = {**json.loads(metadata["stats"]), "snapshot": staging, "imported_from_snapshot": original,
             "published_at": dt.datetime.now(dt.timezone.utc).isoformat(), "publish_seconds": round(time.monotonic() - started, 1)}
    remote.execute([f"UPDATE snapshots SET completed_at={loader.quote(metadata['completed_at'])}, stats={loader.quote(json.dumps(stats))} WHERE id={staging};"])
    # Compare-and-swap the serving pointer so a nightly load finishing while
    # we upload is not overwritten. Only this statement exposes the new data.
    if current is None:
        switch = f"INSERT INTO meta (key,value) SELECT 'current','{staging}' WHERE NOT EXISTS (SELECT 1 FROM meta WHERE key='current');"
    else:
        switch = f"UPDATE meta SET value='{staging}' WHERE key='current' AND value={loader.quote(current)};"
    remote.execute([switch])
    if remote.query("SELECT value FROM meta WHERE key='current'")[0]["value"] != str(staging):
        raise loader.Abort("Hosted current changed during upload; not switching over the concurrent load.")
    if current is not None:
        remote.execute([f"INSERT INTO meta (key,value) SELECT 'previous',{loader.quote(current)} WHERE EXISTS (SELECT 1 FROM meta WHERE key='current' AND value='{staging}') ON CONFLICT(key) DO UPDATE SET value=excluded.value;"])
    # No cleanup here: preserve nightly loader staging and rollback generations.
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("snapshot", nargs="?", type=Path)
    parser.add_argument("--local", type=Path, help="completed parsed SQLite file copied from Dell")
    parser.add_argument("--database-id")
    args = parser.parse_args(argv)
    if bool(args.local) == bool(args.snapshot):
        parser.error("Pass one snapshot path, either positional or --local PATH.")
    token = os.environ.get("CLOUDFLARE_D1_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise SystemExit("Set CLOUDFLARE_D1_TOKEN on the Mac or in GitHub Actions, not on Dell.")
    local = ReadOnlySnapshot(args.local or args.snapshot)
    try:
        stats = publish(local, PublisherD1(loader.database_id(args.database_id), token), log=lambda message: print(message, file=loader.sys.stderr, flush=True))
        print(json.dumps(stats, indent=2))
    finally:
        local.db.close()


if __name__ == "__main__":
    main()
