"""Sync the SAM trigram name index (sam-gov-name-index) with sam-gov-entities.

Reads every entity and exclusion name from sam-gov-entities (reads only),
compares fingerprints, and writes only rows whose names changed. The index
only narrows name searches; the Worker still checks every match exactly.

Cost rules (D1 bills rows written past 50M per billing cycle):
- A sync estimated at SMALL_SYNC_ROWS or less always runs (daily exclusion
  changes are a few hundred rows).
- A larger sync (first build, or a full reload that changed rowids) runs only
  when this cycle's account writes plus the estimate stay under
  MONTHLY_CEILING, unless --allow-paid-rows explicitly covers it.
- --max-rows is a hard stop on measured rows written for the whole run.
"""
import argparse, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_sam_public import D1, quote, WORKER_DIR  # noqa: E402

SMALL_SYNC_ROWS = 250_000
MONTHLY_CEILING = 40_000_000
DEFAULT_MAX_ROWS = 3_000_000
READ_PAGE = 5000
WRITE_BYTES = 60_000

# Must mirror deploy/sam-gov/src/name-matching.ts nameWords()/normalizedName().
PUNCTUATION = "!\"#$%'()*+,-./:;<=>?@[\\]^_`{|}~" + "‐‑‒–—―−‘’‚‛“”„‟«»‹›·•…，。、（）［］｛｝：；！？／＼"
SPACES = "\t\n\r\v\f              　"
SUFFIXES = {"inc", "llc", "corp", "corporation", "co", "company", "ltd", "lp", "pllc", "the"}

KINDS = {
    "entities": (["legal", "dba"], "legal_business_name AS a, dba_name AS b"),
    "exclusions": (["name", "full_name", "short_name"],
                   "name AS a, coalesce(first_name,'')||' '||coalesce(middle_name,'')||' '||coalesce(last_name,'') AS b, "
                   "coalesce(first_name,'')||' '||coalesce(last_name,'') AS c"),
}


def compact(value):
    if not value:
        return ""
    s = value.lower().replace("&", "and")
    for c in PUNCTUATION:
        s = s.replace(c, "")
    for c in SPACES:
        s = s.replace(c, " ")
    return "".join(w for w in s.split(" ") if w and w not in SUFFIXES)


def names_hash(names):
    return hashlib.sha256(json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:16]


def snapshot(source, kind):
    status = source.query(f"SELECT sha256, loaded_at FROM extract_status WHERE kind={quote(kind)}")
    refreshing = source.query(f"SELECT count(*) AS n FROM public_refresh_runs WHERE kind={quote(kind)} AND state='applying'")[0]["n"]
    return (status[0]["sha256"], status[0]["loaded_at"]) if status and not refreshing else None


def read_source(source, kind):
    """rowid -> compact names, paged by rowid. Reads only."""
    columns = KINDS[kind][1]
    rows, last = {}, 0
    while True:
        page = source.query(f"SELECT rowid AS r, {columns} FROM {kind} WHERE rowid > {last} ORDER BY rowid LIMIT {READ_PAGE}")
        for row in page:
            rows[row["r"]] = [compact(row[k]) for k in ("a", "b", "c") if k in row]
        if len(page) < READ_PAGE:
            return rows
        last = page[-1]["r"]


def read_keys(index, kind):
    keys, last = {}, -1
    while True:
        page = index.query(f"SELECT source_rowid AS r, names_hash AS h FROM name_index_keys WHERE kind={quote(kind)} AND source_rowid > {last} ORDER BY source_rowid LIMIT 10000")
        keys.update((row["r"], row["h"]) for row in page)
        if len(page) < 10000:
            return keys
        last = page[-1]["r"]


def plan(source_rows, keys):
    removed = sorted(set(keys) - set(source_rows))
    added = sorted(r for r in source_rows if r not in keys)
    changed = sorted(r for r in source_rows if r in keys and keys[r] != names_hash(source_rows[r]))
    # Measured on D1: one FTS insert, update or delete is one row written.
    # Fingerprints add one per row; changed rows pay delete + insert + replace.
    estimate = 2 * len(added) + 4 * len(changed) + 2 * len(removed) + 10
    return removed, added, changed, estimate


def batches(kind, source_rows, removed, added, changed):
    """Atomic D1 batches that keep index rows and fingerprints in step."""
    columns = KINDS[kind][0]
    for start in range(0, len(removed), 500):
        ids = ",".join(str(r) for r in removed[start:start + 500])
        yield [f"DELETE FROM {kind}_name_index WHERE rowid IN ({ids});",
               f"DELETE FROM name_index_keys WHERE kind={quote(kind)} AND source_rowid IN ({ids});"]
    pending, size = [], 0
    rewrite = set(changed)
    for r in sorted(set(added) | rewrite):
        names = source_rows[r]
        row_bytes = sum(len(n.encode()) for n in names) + 64
        if pending and size + row_bytes > WRITE_BYTES:
            yield write_batch(kind, columns, pending, rewrite, source_rows)
            pending, size = [], 0
        pending.append(r)
        size += row_bytes
    if pending:
        yield write_batch(kind, columns, pending, rewrite, source_rows)


def write_batch(kind, columns, rowids, rewrite, source_rows):
    statements = []
    old = [str(r) for r in rowids if r in rewrite]
    if old:
        statements.append(f"DELETE FROM {kind}_name_index WHERE rowid IN ({','.join(old)});")
    values = ",".join(f"({r},{','.join(quote(n) for n in source_rows[r])})" for r in rowids)
    statements.append(f"INSERT INTO {kind}_name_index(rowid,{','.join(columns)}) VALUES {values};")
    keys = ",".join(f"({quote(kind)},{r},{quote(names_hash(source_rows[r]))})" for r in rowids)
    statements.append(f"INSERT OR REPLACE INTO name_index_keys VALUES {keys};")
    return statements


def account_written():
    from sam_public_incremental import account_month_written, billing_period
    return account_month_written(billing_period())


def sync(source, index, kind, max_rows, allow_paid_rows, written_so_far, account=None):
    result = {"kind": kind}
    before = snapshot(source, kind)
    if before is None:
        return dict(result, skipped="source refreshing or not loaded; index left as is")
    status = index.query(f"SELECT source_sha, source_loaded_at FROM name_index_status WHERE kind={quote(kind)}")
    if status and (status[0]["source_sha"], status[0]["source_loaded_at"]) == before:
        return dict(result, skipped="index current")
    source_rows = read_source(source, kind)
    removed, added, changed, estimate = plan(source_rows, read_keys(index, kind))
    result.update(source_rows=len(source_rows), added=len(added), changed=len(changed), removed=len(removed), estimated_rows_written=estimate)
    if estimate > SMALL_SYNC_ROWS:
        account = account if account is not None else account_written()
        result["account_month_written"] = account
        if not (account + estimate <= MONTHLY_CEILING or estimate <= allow_paid_rows):
            return dict(result, skipped=f"waiting: {estimate} rows would take this billing cycle past the {MONTHLY_CEILING:,} ceiling; runs after the cycle resets")
    if written_so_far + estimate > max_rows:
        raise RuntimeError(f"{kind}: estimate {estimate} exceeds the remaining hard cap ({max_rows - written_so_far}); nothing written")
    written = 0
    for statements in batches(kind, source_rows, removed, added, changed):
        response = index.api({"sql": "\n".join(statements)})
        written += sum(int(r.get("meta", {}).get("rows_written", 0)) for r in response)
        if written_so_far + written > max_rows or written > 2 * estimate + 1000:
            raise RuntimeError(f"{kind}: measured {written} rows written passed the cap or twice the {estimate} estimate; stopped, status not marked current")
    after = snapshot(source, kind)
    if after != before:
        return dict(result, rows_written=written, skipped="source changed during sync; status not marked current, next run finishes the diff")
    response = index.api({"sql": f"INSERT OR REPLACE INTO name_index_status VALUES ({quote(kind)},{quote(before[0])},{quote(before[1])},{len(source_rows)},datetime('now'));"})
    written += sum(int(r.get("meta", {}).get("rows_written", 0)) for r in response)
    return dict(result, rows_written=written, current=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--remote", action="store_true", required=True)
    parser.add_argument("--kind", choices=["entities", "exclusions", "all"], default="all")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS, help="hard stop on measured rows written for the run")
    parser.add_argument("--allow-paid-rows", type=int, default=0, help="run a sync up to this many rows even past the monthly ceiling")
    args = parser.parse_args(argv)
    source, index = D1("remote", "sam-gov-entities"), D1("remote", "sam-gov-name-index")
    schema = (WORKER_DIR / "name-index-schema.sql").read_text()
    index.api({"sql": "\n".join(line for line in schema.splitlines() if not line.startswith("--"))})
    output, written = [], 0
    for kind in ["entities", "exclusions"] if args.kind == "all" else [args.kind]:
        result = sync(source, index, kind, args.max_rows, args.allow_paid_rows, written)
        written += result.get("rows_written", 0)
        output.append(result)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
