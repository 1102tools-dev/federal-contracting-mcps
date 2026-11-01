#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Keep a copy of GSA CALC+ ceiling rates in D1 for the hosted CALC+ Worker.

record: pull every ceiling-rate record from GSA's API into a recording
directory. GSA serves one Elasticsearch index, rebuilt every night at 02:00 UTC
(its name, e.g. ceilingrates-2026-10-31_02-00-02, is the copy's version), and
pages stop at 10,000 hits. So the pull cuts price_range into slices of at most
10,000 records, splitting at GSA's own median until each fits, and pages each
slice 500 at a time. A slice whose pages come back short of its count (sort
ties shifting across page boundaries) is split again until it is complete.
Every answer must carry the same index name; a rebuild mid-pull aborts the run.
One request at a time, --gap seconds apart (default 7.5, about 480 an hour).
Run it on GitHub (gsa-calc-load.yml), never from the Mac: the Mac and the Dell
share the home IP, and the Dell's hosted CALC+ needs GSA's goodwill.

    python3 scripts/load_gsa_calc.py record --out rec

probe: record GSA's answers to a fixed list of query strings
(deploy/gsa-calc/scripts/probes.txt) so the Worker's matching, filter, sort and
paging rules can be pinned to GSA's real behavior. Errors are recorded, not
raised.

    python3 scripts/load_gsa_calc.py probe --out rec/probes

A recording directory holds manifest.jsonl (one line per request: n, query,
status, ms, index, total, relation, count, hits, sha256) and
bodies/NNNNN.json.gz (each raw answer). record also writes records.jsonl.gz
(one {"_id", "_source"} line per distinct record, GSA's key order kept) and
summary.json.

build: turn a recording (the directory holding records.jsonl.gz and
summary.json, or one with them under pull/) into deploy/gsa-calc/schema.sql
rows. Nights as schema.sql's header describes: an empty copy becomes night 1;
a copy whose meta 'version' is another index gets night N+1 change-only (only
records whose (id, hash) is new are written, with v_from = N+1; replaced and
removed rows get v_to = N+1; new terms are added), then one statement moves
meta current, version, timestamp and loaded_at together, then rows no night
>= N can see (v_to <= N: those the previous switch closed), their sources rows
and terms no remaining row uses are deleted. Cleanup runs a night behind: rows
closed at this switch stay until the next one, so an answer that read night N
just before the switch still finds every night-N row. A recording of the
copy's own index writes nothing; an older one is refused. Rows left by an
interrupted run are reused when they still match and deleted when they don't.
--limit N loads only the first N records (a sample). Prints a JSON status with
written_estimate, the rows a D1 load bills: table rows inserted, updated or
deleted plus one per index entry touched (records has 3 indexes; terms is
WITHOUT ROWID, one write per row; meta's TEXT key has an automatic index).

    python3 scripts/load_gsa_calc.py build --rec rec/pull --local calc.sqlite [--limit 10000]

diff: churn between two recordings: records added, removed, changed by content
hash, unchanged; records that came back under a new _id with the same content;
distinct _timestamp values per night; which _source keys changed; and the rows
the change from A to B costs, counted as build counts them: at the switch to B
(inserts, closes, new terms, meta) and at the switch after it (deleting the
rows B retired and the terms only they used). A refresh to B also deletes what
the switch to A retired, which two recordings can't show.

    python3 scripts/load_gsa_calc.py diff --a rec-night1/pull --b rec-night2/pull

refresh: for GitHub. Reads meta 'version'; if GSA's index name is the same,
exits with no writes. Otherwise records the night into a temporary directory
(as record does, on GitHub only) and builds it change-only into the target.
--rec DIR skips the recording and uses DIR (tests, reruns).

    python3 scripts/load_gsa_calc.py refresh --remote [--max-rows 200000]

Targets for build and refresh: --local PATH (a sqlite file with schema.sql) or
--remote (the D1 HTTP API with CLOUDFLARE_D1_TOKEN, CLOUDFLARE_ACCOUNT_ID, and
the database id from --database-id, GSA_CALC_D1_DATABASE_ID or
deploy/gsa-calc/wrangler.jsonc env.production d1_databases). Remote runs add up
every result's meta.rows_written; a run whose projected writes pass --max-rows
(remote default 200,000) writes nothing, and one that passes it while writing
stops before the switch. --json FILE also writes the status there.

Standard library only, so it runs on a bare runner.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

BASE_URL = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"
USER_AGENT = "1102tools-gsa-calc-loader (+https://1102tools.com)"
WINDOW = 10_000          # Elasticsearch's from + size limit
PAGE_SIZE = 500          # GSA's largest page
SLICE_TARGET = 9_000     # split slices above this many records
PRICE_TOP = 999_999      # the Python server's open-ended price sentinel
MAX_RETRY_AFTER = 45 * 60
# Extra sort keys after current_price, so equal prices keep one order from page
# to page. Dropped if GSA refuses repeated ordering pairs.
TIEBREAK = ["vendor_name", "labor_category", "idv_piid", "min_years_experience", "education_level"]
ROOT = Path(__file__).resolve().parent.parent
WORKER_DIR = ROOT / "deploy" / "gsa-calc"
SCHEMA = WORKER_DIR / "schema.sql"
PROBES = WORKER_DIR / "scripts" / "probes.txt"
WHOLE_QUERY = "page=1&page_size=1&ordering=current_price&sort=asc"

# The copy in D1.
OPEN = 9_223_372_036_854_775_807  # records.v_to of a row no night has closed (schema default)
JS_SAFE = 2 ** 53                  # D1 returns integers as JSON numbers, so OPEN comes back rounded
TERM_FIELDS = ("labor_category", "vendor_name", "idv_piid")
RECORD_COLUMNS = ("rid", "id", "v_from", "labor_category", "vendor_name", "idv_piid", "price", "next_year_price",
                  "education_level", "min_years_experience", "worksite", "business_size", "security_clearance",
                  "sin", "hash")
RECORD_INDEXES = 3        # records_labor_category, records_vendor_name, records_idv_piid
STATEMENT_BYTES = 90_000  # D1 allows 100 KB per SQL statement
REQUEST_BYTES = 900_000   # SQL per D1 HTTP API request
PAGE_ROWS = 5_000         # stored rows read per query
MAX_ROWS = 200_000        # default --max-rows for remote runs
CHUNK_RECORDS = 2_000     # records per write batch (their sources rows first, then the records rows)


class IndexChanged(RuntimeError):
    pass


class Recorder:
    """One paced request at a time; every raw answer saved as it arrives."""

    def __init__(self, out: Path, gap: float, max_calls: int):
        self.out = out
        self.gap = gap
        self.max_calls = max_calls
        (out / "bodies").mkdir(parents=True, exist_ok=True)
        self.manifest = open(out / "manifest.jsonl", "a", encoding="utf-8")
        self.n = sum(1 for _ in open(out / "manifest.jsonl", encoding="utf-8"))
        self.calls = 0
        self.last = 0.0
        self.index: str | None = None

    def _fetch(self, url: str) -> tuple[int, bytes, dict[str, str]]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers or {})

    def get(self, query: str, *, strict: bool) -> dict | None:
        """GSA's answer to `query` (parsed), or None for a non-JSON/error answer when not strict."""
        if self.calls >= self.max_calls:
            raise RuntimeError(f"stopped at --max-calls {self.max_calls}")
        url = f"{BASE_URL}?{query}"
        for attempt in range(5):
            wait = self.last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            started = time.monotonic()
            self.last = started
            self.calls += 1
            try:
                status, body, headers = self._fetch(url)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                status, body, headers = 0, str(error).encode(), {}
            ms = round((time.monotonic() - started) * 1000)
            retry = status in (0, 429, 500, 502, 503, 504) and attempt < 4
            self._save(query, status, ms, body, headers, retried=retry)
            if not retry:
                break
            after = headers.get("Retry-After") or headers.get("retry-after")
            delay = min(int(after), MAX_RETRY_AFTER) if after and after.isdigit() else 30 * (attempt + 1)
            print(f"  {status} on {query[:80]}; waiting {delay} s", file=sys.stderr, flush=True)
            time.sleep(delay)
        try:
            data = json.loads(body) if status == 200 else None
        except ValueError:
            data = None
        if data is None and strict:
            raise RuntimeError(f"GSA answered {status} to {query}: {body[:300]!r}")
        if data is not None:
            index = _index_of(data)
            if index:
                if self.index is None:
                    self.index = index
                elif index != self.index:
                    raise IndexChanged(f"GSA index changed mid-recording: {self.index} -> {index}")
        return data

    def _save(self, query: str, status: int, ms: int, body: bytes, headers: dict, *, retried: bool) -> None:
        self.n += 1
        (self.out / "bodies" / f"{self.n:05d}.json.gz").write_bytes(gzip.compress(body, 6))
        line: dict = {"n": self.n, "query": query, "status": status, "ms": ms,
                      "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        if retried:
            line["retried"] = True
        rate = {k.lower(): v for k, v in headers.items() if k.lower().startswith("x-ratelimit")}
        if rate:
            line["ratelimit"] = rate
        try:
            data = json.loads(body) if status == 200 else None
        except ValueError:
            data = None
        if isinstance(data, dict):
            total = (data.get("hits") or {}).get("total")
            if isinstance(total, dict):
                line["total"], line["relation"] = total.get("value"), total.get("relation")
            line["count"] = _count(data)
            line["hits"] = len((data.get("hits") or {}).get("hits") or [])
            line["index"] = _index_of(data)
        self.manifest.write(json.dumps(line) + "\n")
        self.manifest.flush()


def _index_of(data: dict) -> str | None:
    hits = (data.get("hits") or {}).get("hits") or []
    return hits[0].get("_index") if hits and isinstance(hits[0], dict) else None


def _count(data: dict) -> int | None:
    """Records matched (wage_stats.count covers every match, unlike hits.total)."""
    stats = ((data.get("aggregations") or {}).get("wage_stats")) or {}
    count = stats.get("count")
    return count if isinstance(count, int) else None


def _num(x: float) -> str:
    text = f"{x:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _orderings(tiebreak: bool) -> str:
    keys = ["current_price"] + (TIEBREAK if tiebreak else [])
    return "&".join(f"ordering={k}&sort=asc" for k in keys)


# When one price holds more records than a page window, the slice is split by
# these filters instead, one level at a time. Children's counts must add up to
# the parent's, or the run says records were lost.
SUBSLICES = [
    ["business_size:S", "business_size:O"],
    ["experience_range:0,2", "experience_range:3,5", "experience_range:6,9", "experience_range:10,999"],
    ["security_clearance:yes", "security_clearance:no"],
]


def _slice_query(lo: float, hi: float, extra: tuple[str, ...], page: int, tiebreak: bool) -> str:
    filters = [f"price_range:{_num(lo)},{_num(hi)}", *extra]
    encoded = "&".join(f"filter={f.split(':', 1)[0]}:{urllib.parse.quote_plus(f.split(':', 1)[1])}" for f in filters)
    return f"{encoded}&page={page}&page_size={PAGE_SIZE}&{_orderings(tiebreak)}"


def record(args: argparse.Namespace) -> int:
    out = Path(args.out)
    rec = Recorder(out, args.gap, args.max_calls)
    started = time.time()
    whole = rec.get(WHOLE_QUERY, strict=True)
    priced = _count(whole)
    print(f"index {rec.index}; {priced} priced records", flush=True)

    # Repeated ordering pairs: GSA documents them; fall back to price alone if refused.
    tiebreak = rec.get(f"keyword=nurse&page=1&page_size=5&{_orderings(True)}", strict=False) is not None
    print(f"tie-break orderings {'on' if tiebreak else 'off'}", flush=True)

    records = gzip.open(out / "records.jsonl.gz", "wt", encoding="utf-8")
    seen: set[str] = set()
    slices: list[dict] = []
    queue: list[tuple[float, float, tuple[str, ...]]] = [(0.0, float(PRICE_TOP), ())]
    lost = 0
    unresolved = 0
    while queue:
        lo, hi, extra = queue.pop(0)
        first = rec.get(_slice_query(lo, hi, extra, 1, tiebreak), strict=True)
        count = _count(first) or 0
        if count > SLICE_TARGET:
            if hi - lo >= 0.0002:
                queue[:0] = [(a, b, extra) for a, b in _split(lo, hi, first)]
                continue
            level = len(extra)
            if level >= len(SUBSLICES):
                raise RuntimeError(f"cannot split slice {lo}-{hi} {extra} ({count} records) further")
            children = []
            for f in SUBSLICES[level]:
                child = rec.get(_slice_query(lo, hi, (*extra, f), 1, tiebreak), strict=True)
                children.append(((lo, hi, (*extra, f)), _count(child) or 0))
            missing = count - sum(c for _, c in children)
            if missing:
                lost += missing
                print(f"WARNING: splitting {lo}-{hi} {extra} by {SUBSLICES[level]} misses {missing} records",
                      file=sys.stderr)
            queue[:0] = [s for s, _ in children]
            continue
        ids: set[str] = set()
        edges: set[float] = set()  # prices at page boundaries, where ties can shift between pages
        pages = max(1, math.ceil(count / PAGE_SIZE))
        for page in range(1, pages + 1):
            data = first if page == 1 else rec.get(_slice_query(lo, hi, extra, page, tiebreak), strict=True)
            hits = data["hits"]["hits"]
            for hit in hits:
                ids.add(hit["_id"])
                if hit["_id"] not in seen:
                    seen.add(hit["_id"])
                    records.write(json.dumps({"_id": hit["_id"], "_source": hit["_source"]}) + "\n")
            if hits and pages > 1:
                edges.update(h["_source"].get("current_price") for h in (hits[0], hits[-1]))
        complete = len(ids) >= count
        slices.append({"lo": lo, "hi": hi, "extra": list(extra), "count": count, "ids": len(ids),
                       "pages": pages, "complete": complete})
        label = f"{_num(lo)}-{_num(hi)}{' ' + ' '.join(extra) if extra else ''}"
        if not complete:
            if pages == 1:
                raise RuntimeError(f"single page slice {label} returned {len(ids)} of {count}")
            prices = sorted(p for p in edges if isinstance(p, (int, float)) and lo <= p <= hi)
            if lo < hi and prices:
                # Fetch each boundary price on its own: its records then fit one page (or split below).
                print(f"  slice {label}: {len(ids)} of {count}; refetching {len(prices)} boundary prices", flush=True)
                queue[:0] = [(p, p, extra) for p in prices]
            elif len(extra) < len(SUBSLICES):
                print(f"  slice {label}: {len(ids)} of {count}; splitting by {SUBSLICES[len(extra)]}", flush=True)
                queue[:0] = [(lo, hi, (*extra, f)) for f in SUBSLICES[len(extra)]]
            else:
                unresolved += count - len(ids)
                print(f"WARNING: slice {label} stays {len(ids)} of {count}", file=sys.stderr, flush=True)
        print(f"slice {label}: {count} records, {len(seen)} so far, {rec.calls} calls", flush=True)
    records.close()

    summary = {
        "index": rec.index, "priced_records": priced, "records": len(seen), "calls": rec.calls,
        "tiebreak_orderings": tiebreak, "lost_in_subslices": lost, "unresolved": unresolved, "minutes": round((time.time() - started) / 60, 1),
        "slices": slices,
        "whole_index_aggregations": {k: v for k, v in (whole.get("aggregations") or {}).items()
                                     if k in ("business_size", "security_clearance", "education_level_counts",
                                              "worksite", "wage_stats")},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("slices", "whole_index_aggregations")}))
    if priced is not None and len(seen) != priced:
        print(f"WARNING: {len(seen)} records collected, GSA counts {priced} priced records", file=sys.stderr)
    return 0


def _split(lo: float, hi: float, data: dict) -> list[tuple[float, float]]:
    """Two slices cut at GSA's median price (a midpoint when the median sits on an edge)."""
    values = ((data.get("aggregations") or {}).get("median_price") or {}).get("values") or {}
    mid = next((v for v in values.values() if isinstance(v, (int, float))), None)
    if mid is None or not lo < mid < hi:
        mid = (lo + hi) / 2
    # Rounded cut, both slices include it; duplicates are dropped by id.
    mid = round(mid, 4)
    if not lo < mid < hi:
        mid = (lo + hi) / 2
    return [(lo, mid), (mid, hi)]


def probe(args: argparse.Namespace) -> int:
    out = Path(args.out)
    rec = Recorder(out, args.gap, args.max_calls)
    rec.index = None
    done = {json.loads(line)["query"] for line in open(out / "manifest.jsonl", encoding="utf-8")}
    queries = [line.strip() for line in open(args.list, encoding="utf-8")
               if line.strip() and not line.lstrip().startswith("#")]
    for query in queries:
        if query in done and not query.startswith("repeat:"):
            continue
        send = query.removeprefix("repeat:")
        try:
            rec.get(send, strict=False)
        except IndexChanged as error:
            print(f"WARNING: {error}", file=sys.stderr)
            rec.index = None
        print(f"{rec.calls} {send[:100]}", flush=True)
    return 0


# ---------- rows ----------

class Refused(RuntimeError):
    """The recording can't be loaded as asked; nothing was written."""


class RowCap(Exception):
    """A run would pass --max-rows; stop before writing more."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fold(value: str) -> str:
    """terms.folded: a value as GSA compares it case-insensitively. The one place
    the rule lives; when it changes, the next build rewrites every term whose
    folded text differs."""
    return value.lower()


def float32(value: Any) -> float | None:
    """A price as GSA's index holds it (float32), as a double. None when absent or not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        rounded = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (TypeError, ValueError, OverflowError):
        return None
    return rounded if math.isfinite(rounded) else None


def clearance(value: Any) -> int | None:
    """records.security_clearance: 1/0 from GSA's boolean; None when missing or unreadable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    return {"true": 1, "yes": 1, "1": 1, "false": 0, "no": 0, "0": 0}.get(str(value).strip().lower())


def sin_column(value: Any) -> str | None:
    """records.sin: ',' + GSA's comma list + ',', so a whole code matches LIKE '%,code,%'."""
    if value is None:
        return None
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    return f",{value},"


def canonical(source: dict, drop: tuple[str, ...] = ("_timestamp",)) -> str:
    """_source without _timestamp, keys sorted: the text records.hash covers."""
    return json.dumps({k: v for k, v in source.items() if k not in drop},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_hash(source: dict) -> str:
    return sha(canonical(source))


def source_json(source: dict) -> str:
    """sources.json: the parsed _source as Python's json.dumps writes it, GSA's key order kept.
    Its _timestamp is the night the row was written; the Worker puts meta 'timestamp' in its place."""
    return json.dumps(source, ensure_ascii=False, separators=(",", ":"))


def record_id(_id: Any, source: dict) -> int:
    """records.id: GSA's _id (equal to _source.id), as an integer."""
    for value in (_id, source.get("id")):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    raise ValueError(f"a record without a numeric id: _id {_id!r}")


def record_row(rid: int, night: int, ident: int, source: dict, digest: str) -> list:
    """One records row, in RECORD_COLUMNS order."""
    return [rid, ident, night, source.get("labor_category"), source.get("vendor_name"), source.get("idv_piid"),
            float32(source.get("current_price")), float32(source.get("next_year_price")),
            source.get("education_level"), source.get("min_years_experience"), source.get("worksite"),
            source.get("business_size"), clearance(source.get("security_clearance")),
            sin_column(source.get("sin")), digest]


def term_values(source: dict) -> Iterator[tuple[str, str]]:
    """(field, value) for the terms table: each of TERM_FIELDS that is present."""
    for field in TERM_FIELDS:
        value = source.get(field)
        if value is not None:
            yield field, str(value)


class Recording:
    """A directory written by record: records.jsonl.gz and summary.json, here or under pull/."""

    def __init__(self, path: Path | str):
        path = Path(path)
        if not (path / "records.jsonl.gz").exists() and (path / "pull" / "records.jsonl.gz").exists():
            path = path / "pull"
        if not (path / "records.jsonl.gz").exists():
            raise Refused(f"no records.jsonl.gz in {path}")
        self.path = path
        summary = path / "summary.json"
        self.summary: dict = json.loads(summary.read_text()) if summary.exists() else {}
        self.index: str | None = self.summary.get("index")
        if not self.index and (path / "manifest.jsonl").exists():
            # An unfinished recording has no summary; its answers still name the index.
            for line in open(path / "manifest.jsonl", encoding="utf-8"):
                index = json.loads(line).get("index")
                if index:
                    self.index = index
                    break

    def records(self, limit: int | None = None) -> Iterator[tuple[str, dict]]:
        """(_id, _source) in recorded order, each _id once."""
        seen: set[str] = set()
        with gzip.open(self.path / "records.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                if limit is not None and len(seen) >= limit:
                    return
                if not line.strip():
                    continue
                item = json.loads(line)
                _id = str(item["_id"])
                if _id in seen:
                    continue
                seen.add(_id)
                yield _id, item["_source"]


class Scan:
    """What build needs from a first pass over a recording, and what it reports."""

    def __init__(self) -> None:
        self.keys: dict[tuple[int, str], int] = {}   # (id, hash) -> position in the recording
        self.terms: dict[tuple[str, str], str] = {}  # (field, value) -> folded
        self.timestamps: Counter = Counter()
        self.orders: Counter = Counter()             # distinct _source key orders
        self.checks: Counter = Counter()

    @property
    def timestamp(self) -> str | None:
        """The night's _timestamp (the most common one, should a night ever carry several)."""
        best = self.timestamps.most_common(1)
        return best[0][0] if best else None


def scan(recording: Recording, limit: int | None, log: Callable[[str], None]) -> Scan:
    found = Scan()
    for position, (_id, source) in enumerate(recording.records(limit)):
        ident = record_id(_id, source)
        found.keys[(ident, record_hash(source))] = position
        for field, value in term_values(source):
            found.terms[(field, value)] = fold(value)
        found.timestamps[source.get("_timestamp")] += 1
        found.orders[tuple(source)] += 1
        checks = found.checks
        if float32(source.get("current_price")) is None:
            checks["missing_price"] += 1
        if float32(source.get("next_year_price")) is None:
            checks["missing_next_year_price"] += 1
        if str(source.get("id")) != _id:
            checks["id_differs_from__id"] += 1
        if source.get("security_clearance") is None:
            checks["missing_security_clearance"] += 1
        elif clearance(source.get("security_clearance")) is None:
            checks["unreadable_security_clearance"] += 1
        if source.get("sin") is None:
            checks["missing_sin"] += 1
        for field in TERM_FIELDS:
            if not source.get(field):
                checks[f"empty_{field}"] += 1
        if position and position % 50_000 == 0:
            log(f"  read {position:,} records")
    return found


# ---------- D1 ----------

def quote(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # repr() is the shortest text that reads back as the same double (SQLite parses it exactly).
        return repr(value) if math.isfinite(value) else "NULL"
    text = str(value)
    if "\x00" in text:
        return "(" + " || char(0) || ".join(quote(part) for part in text.split("\x00")) + ")"
    return "'" + text.replace("'", "''") + "'"


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def packed(head: str, items: list[str], tail: str) -> list[str]:
    """head + items joined by ', ' + tail, in as many statements as STATEMENT_BYTES needs."""
    fixed = size(head) + size(tail)
    statements: list[str] = []
    batch: list[str] = []
    used = fixed
    for item in items:
        length = size(item) + 2
        if fixed + length > STATEMENT_BYTES:
            raise ValueError(f"one item is too large for a statement: {head[:40]}...")
        if batch and used + length > STATEMENT_BYTES:
            statements.append(head + ", ".join(batch) + tail)
            batch, used = [], fixed
        batch.append(item)
        used += length
    if batch:
        statements.append(head + ", ".join(batch) + tail)
    return statements


def inserts(table: str, columns: tuple[str, ...], rows: list[list[Any]], conflict: str = "", verb: str = "INSERT") -> list[str]:
    head = f"{verb} INTO {table} ({', '.join(columns)}) VALUES "
    return packed(head, ["(" + ", ".join(quote(v) for v in row) + ")" for row in rows], conflict + ";")


def by_rid(head: str, rids: list[int]) -> list[str]:
    """head ends with 'rid IN ('; one statement per STATEMENT_BYTES of ids."""
    return packed(head, [str(r) for r in sorted(rids)], ");")


def meta_upsert(pairs: list[list[str]]) -> list[str]:
    """One statement for all pairs, so they change together."""
    return inserts("meta", ("key", "value"), pairs, " ON CONFLICT (key) DO UPDATE SET value = excluded.value")


class Target:
    """What every database target shares: the rows-written count and its cap."""

    target = "local"

    def __init__(self, max_rows: int | None = None):
        self.max_rows = max_rows
        self.rows_written = 0
        self.rows_read = 0

    def count(self, written: int) -> None:
        self.rows_written += written
        if self.max_rows is not None and self.rows_written > self.max_rows:
            raise RowCap(f"{self.rows_written:,} rows written passed --max-rows {self.max_rows:,}; stopping")

    def room(self, planned: int, what: str) -> None:
        if self.max_rows is not None and self.rows_written + planned > self.max_rows:
            raise RowCap(f"{what} would write about {planned:,} rows; with {self.rows_written:,} written this run "
                         f"that passes --max-rows {self.max_rows:,}. Nothing written for it.")

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        raise NotImplementedError

    def execute(self, statements: list[str]) -> int:
        raise NotImplementedError

    def size(self) -> int | None:
        return None


class LocalD1(Target):
    """A sqlite file with schema.sql applied, for wrangler dev, tests and parity runs.
    rows_written here is SQLite's count of table rows changed (no index entries)."""

    def __init__(self, path: Path | str, max_rows: int | None = None):
        super().__init__(max_rows)
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text())

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.db.execute(sql, params)]
        self.rows_read += len(rows)
        return rows

    def execute(self, statements: list[str]) -> int:
        if not statements:
            return 0
        before = self.db.total_changes
        try:
            self.db.executescript("BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;")
        except sqlite3.Error:
            if self.db.in_transaction:
                self.db.rollback()
            raise
        written = self.db.total_changes - before
        self.count(written)
        return written

    def size(self) -> int | None:
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        return pages * self.db.execute("PRAGMA page_size").fetchone()[0]


class RemoteD1(Target):
    """The D1 HTTP API /query endpoint (what wrangler d1 execute --remote uses).

    Every result's meta.rows_written is added up; a result without it stops the
    run, and so does passing max_rows. Inserts carry rids fixed by the loader and
    are INSERT OR IGNORE, updates and deletes go by rid, so a request retried
    after a lost answer does no harm.
    """

    target = "remote"

    def __init__(self, database_id: str, token: str, account_id: str, max_rows: int | None = MAX_ROWS,
                 post: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        super().__init__(max_rows)
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.token = token
        self.post = post or self._http
        self.sleep = sleep
        self.calls = 0
        self.size_after: int | None = None

    def _http(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(4):
            request = urllib.request.Request(self.url, data=data, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "1102tools-gsa-calc-loader"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:1000].decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    self.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP API returned {exc.code}: {detail}") from None
            except urllib.error.URLError as exc:
                if attempt < 3:
                    self.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP API unreachable: {exc.reason}") from None
        raise AssertionError("unreachable")

    def _results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls += 1
        body = self.post(payload)
        if not body.get("success"):
            raise RuntimeError(f"D1 query failed: {json.dumps(body.get('errors'))[:1000]}")
        results = body.get("result")
        if not isinstance(results, list) or not results or any(
                not isinstance((r.get("meta") or {}).get("rows_written"), int) for r in results):
            raise RuntimeError("D1 write metrics unavailable (no meta.rows_written); stopping before any further writes")
        self.rows_read += sum(int((r.get("meta") or {}).get("rows_read") or 0) for r in results)
        sizes = [r["meta"]["size_after"] for r in results if isinstance(r["meta"].get("size_after"), int)]
        if sizes:
            self.size_after = sizes[-1]
        self.count(sum(r["meta"]["rows_written"] for r in results))
        return results

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        return self._results({"sql": sql, "params": list(params)})[0].get("results") or []

    def execute(self, statements: list[str]) -> int:
        before = self.rows_written
        batch: list[str] = []
        used = 0
        for statement in statements:
            length = size(statement) + 1
            if length > STATEMENT_BYTES + 1:
                raise ValueError(f"statement of {length:,} bytes is over the D1 limit")
            if batch and used + length > REQUEST_BYTES:
                self._results({"sql": "\n".join(batch)})
                batch, used = [], 0
            batch.append(statement)
            used += length
        if batch:
            self._results({"sql": "\n".join(batch)})
        return self.rows_written - before

    def size(self) -> int | None:
        return self.size_after


def wrangler_config() -> dict[str, Any]:
    return json.loads(re.sub(r"^\s*//.*$", "", (WORKER_DIR / "wrangler.jsonc").read_text(), flags=re.M))


def database_id(argument: str | None) -> str:
    value = argument or os.environ.get("GSA_CALC_D1_DATABASE_ID")
    if not value:
        databases = wrangler_config().get("env", {}).get("production", {}).get("d1_databases") or []
        value = next((d.get("database_id") for d in databases if d.get("binding") == "DB"), None) or (
            databases[0].get("database_id") if databases else None)
    if not value or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
        raise SystemExit("Set --database-id or GSA_CALC_D1_DATABASE_ID to the gsa-calc D1 database id "
                         "(or add it to deploy/gsa-calc/wrangler.jsonc env.production d1_databases).")
    return value


def ensure_schema(db: Target) -> None:
    """Remote: apply schema.sql once if the tables aren't there yet."""
    have = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"meta", "records", "sources", "terms"} <= have:
        statements = [s.strip() + ";" for s in re.sub(r"--[^\n]*", "", SCHEMA.read_text()).split(";") if s.strip()]
        db.execute(statements)


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(float(value))


def stored_meta(db: Target) -> dict[str, str]:
    return {r["key"]: r["value"] for r in db.query("SELECT key, value FROM meta")}


def stored_rows(db: Target) -> list[tuple[int, int, str, int, int]]:
    """(rid, id, hash, v_from, v_to) of every records row, read in rid order a page at a time.
    An open row's v_to is OPEN however D1's JSON rounded it."""
    rows: list[tuple[int, int, str, int, int]] = []
    last = -1
    while True:
        page = db.query(f"SELECT rid, id, hash, v_from, v_to FROM records WHERE rid > ? ORDER BY rid LIMIT {PAGE_ROWS}",
                        [last])
        for r in page:
            v_to = as_int(r["v_to"])
            rows.append((as_int(r["rid"]), as_int(r["id"]), r["hash"], as_int(r["v_from"]),
                         OPEN if v_to >= JS_SAFE else v_to))
        if len(page) < PAGE_ROWS:
            return rows
        last = as_int(page[-1]["rid"])


def stored_terms(db: Target) -> dict[tuple[str, str], str]:
    """(field, value) -> folded for every terms row, a page at a time."""
    terms: dict[tuple[str, str], str] = {}
    last = ["", ""]
    while True:
        page = db.query("SELECT field, value, folded FROM terms WHERE (field, value) > (?, ?) "
                        f"ORDER BY field, value LIMIT {PAGE_ROWS}", last)
        for r in page:
            terms[(r["field"], r["value"])] = r["folded"]
        if len(page) < PAGE_ROWS:
            return terms
        last = [page[-1]["field"], page[-1]["value"]]


# ---------- nights ----------

SWITCH_KEYS = ("current", "version", "timestamp", "loaded_at")


def written(*, inserts: int = 0, closes: int = 0, reopens: int = 0, deletes: int = 0, orphans: int = 0,
            terms_added: int = 0, terms_removed: int = 0, meta_inserts: int = 0, meta_updates: int = 0,
            meta_deletes: int = 0) -> dict[str, int]:
    """The rows a D1 run bills: each table row inserted, updated or deleted, plus one per
    index entry touched. A records insert or delete touches its 3 indexes; setting v_to
    touches none (v_to is not indexed); sources is keyed by its rowid; terms is WITHOUT
    ROWID, so its row is its key; meta's TEXT PRIMARY KEY has an automatic index, touched
    when a key is inserted or deleted, not when its value changes."""
    estimate = {
        "records": inserts + closes + reopens + deletes,
        "sources": inserts + deletes + orphans,
        "terms": terms_added + terms_removed,
        "meta": meta_inserts + meta_updates + meta_deletes,
        "index_entries": RECORD_INDEXES * (inserts + deletes) + meta_inserts + meta_deletes,
    }
    estimate["total"] = sum(estimate.values())
    return estimate


def add_up(*parts: dict[str, int]) -> dict[str, int]:
    return {k: sum(p[k] for p in parts) for k in parts[0]}


class Plan:
    """What one build writes, decided before anything is written."""

    def __init__(self, current: int):
        self.current = current
        self.night = current + 1
        self.inserts: set[int] = set()     # recording positions written as new rows (v_from = night)
        self.reopen: list[int] = []        # live rows a stopped run had closed, still in the recording
        self.close: list[int] = []         # live rows replaced or removed whose v_to is set to night now
        self.retire: list[int] = []        # every live row night N+1 no longer has (close + closed by a
                                           # stopped run); kept for night N until the next switch
        self.cleanup: list[int] = []       # rows deleted after the switch: v_to <= N, closed at an earlier one
        self.drop: list[int] = []          # staged rows of a stopped run that no longer match
        self.orphans: list[int] = []       # sources rows a stopped run left without their records row
        self.unchanged = 0
        self.kept_staged = 0
        self.terms_add: list[list[str]] = []   # [field, value, folded]: new, or folded differently
        self.terms_new = 0
        self.terms_drop: list[tuple[str, str]] = []


def make_plan(current: int, found: Scan, rows: list[tuple[int, int, str, int, int]]) -> Plan:
    """Compare the stored rows with the recording. A live row (v_from <= N < v_to) whose
    (id, hash) is in the recording stays; any other live row is retired (v_to = N+1) and
    kept for night N. A staged row (v_from > N, left by a stopped run) is kept when it is
    night N+1 and still matches, and dropped otherwise. Rows no night >= N sees (v_to <= N,
    retired at the previous switch or before) are deleted after this switch."""
    plan = Plan(current)
    matched: set[tuple[int, str]] = set()
    staged: list[tuple[int, tuple[int, str], int, int]] = []
    for rid, ident, digest, v_from, v_to in rows:
        key = (ident, digest)
        if v_to <= current:
            plan.cleanup.append(rid)
        elif v_from > current:
            staged.append((rid, key, v_from, v_to))
        elif key in found.keys and key not in matched:
            matched.add(key)
            plan.unchanged += 1
            if v_to != OPEN:
                plan.reopen.append(rid)
        else:
            if v_to != plan.night:
                plan.close.append(rid)
            plan.retire.append(rid)
    for rid, key, v_from, v_to in staged:
        if v_from == plan.night and key in found.keys and key not in matched:
            matched.add(key)
            plan.kept_staged += 1
            if v_to != OPEN:
                plan.reopen.append(rid)
        else:
            plan.drop.append(rid)
    plan.inserts = {position for key, position in found.keys.items() if key not in matched}
    return plan


def plan_terms(plan: Plan, found: Scan, retired: set[tuple[str, str]], terms: dict[tuple[str, str], str]) -> int:
    """Terms after the switch: night N+1's values plus those of the rows retired now (night N
    still reads them until the next switch). New or refolded ones are written before the
    switch, the rest deleted after it. Returns how many terms the copy then holds."""
    wanted = dict(found.terms)
    for key in retired:
        wanted.setdefault(key, fold(key[1]))
    for key, folded in wanted.items():
        if terms.get(key) != folded:
            plan.terms_add.append([key[0], key[1], folded])
            plan.terms_new += key not in terms
    plan.terms_drop = [key for key in terms if key not in wanted]
    return len(wanted)


def stored_values(db: Target, rids: list[int]) -> set[tuple[str, str]]:
    """(field, value) of TERM_FIELDS for these records rows."""
    values: set[tuple[str, str]] = set()
    for sql in packed(f"SELECT {', '.join(TERM_FIELDS)} FROM records WHERE rid IN (", [str(r) for r in sorted(rids)], ")"):
        for row in db.query(sql):
            values.update(term_values(row))
    return values


def finish(db: Target, status: dict[str, Any], started: tuple[float, int, int]) -> dict[str, Any]:
    """Time, size, and the rows this run wrote and read (started: monotonic time, rows written, rows read)."""
    status["seconds"] = round(time.monotonic() - started[0], 1)
    status["db_bytes"] = db.size()
    status["rows_written"] = db.rows_written - started[1]
    status["rows_read"] = db.rows_read - started[2]
    return status


def build(db: Target, rec: Path | str, limit: int | None = None, log: Callable[[str], None] = print,
          allow_short: bool = False, status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recording -> rows as night N+1, change-only, then the switch and cleanup.
    status (filled in as the build goes, so a stopped run still says what it did) is returned."""
    started = (time.monotonic(), db.rows_written, db.rows_read)
    status = {} if status is None else status
    recording = Recording(rec)
    index = recording.index
    status.update(command="build", index=index, records=None)
    if not index:
        raise Refused(f"{recording.path} names no GSA index (no summary.json or manifest); nothing written")
    meta = stored_meta(db)
    current = int(meta.get("current") or 0)
    status.update(previous={"night": current or None, "version": meta.get("version")})
    if meta.get("version") == index:
        log(f"the copy already holds {index} (night {current}); nothing to write")
        status.update(action="unchanged", night=current, written_estimate=written())
        return finish(db, status, started)
    if meta.get("version") and index < meta["version"]:
        raise Refused(f"recording {index} is older than the copy's {meta['version']}; nothing written")

    log(f"reading {recording.path} ({index})")
    found = scan(recording, limit, log)
    if not found.keys:
        raise Refused(f"{recording.path} holds no records; nothing written")
    priced = recording.summary.get("priced_records")
    status.update(records=len(found.keys), priced_records=priced, timestamp=found.timestamp,
                  distinct_timestamps=len(found.timestamps), timestamps=dict(found.timestamps.most_common(5)),
                  distinct_key_orders=len(found.orders), checks=dict(sorted(found.checks.items())),
                  recording={k: recording.summary.get(k) for k in ("records", "calls", "lost_in_subslices", "unresolved")})
    if len(found.timestamps) > 1:
        log(f"WARNING: {len(found.timestamps)} distinct _timestamp values in one night; meta 'timestamp' gets "
            f"the most common ({found.timestamp}), so the Worker would misreport the others")
    short = (priced is None or len(found.keys) < priced or recording.summary.get("unresolved")
             or recording.summary.get("lost_in_subslices"))
    if short and limit is None:
        message = (f"the recording looks incomplete ({len(found.keys):,} records, GSA counts {priced} priced; "
                   f"unresolved {recording.summary.get('unresolved')}, lost {recording.summary.get('lost_in_subslices')})")
        if current and not allow_short:
            raise Refused(message + "; a change-only build would close the missing records. Nothing written "
                                    "(--allow-short to load it anyway)")
        log("WARNING: " + message)
        status["warning"] = message

    rows = stored_rows(db)
    terms = stored_terms(db)
    plan = make_plan(current, found, rows)
    terms_after = plan_terms(plan, found, stored_values(db, plan.retire), terms)
    if "staging" in meta or plan.drop:
        base = max((rid for rid, _, _, v_from, _ in rows if v_from <= current), default=0)
        plan.orphans = [as_int(r["rid"]) for r in db.query(
            "SELECT rid FROM sources WHERE rid > ? AND rid NOT IN (SELECT rid FROM records WHERE rid > ?)", [base, base])]
    switch_new = sum(k not in meta for k in SWITCH_KEYS)
    stage = written(inserts=len(plan.inserts), closes=len(plan.close), reopens=len(plan.reopen),
                    deletes=len(plan.drop), orphans=len(plan.orphans), terms_added=len(plan.terms_add),
                    meta_inserts=int("staging" not in meta), meta_updates=int("staging" in meta))
    after = written(deletes=len(plan.cleanup), terms_removed=len(plan.terms_drop), meta_inserts=switch_new,
                    meta_updates=len(SWITCH_KEYS) - switch_new, meta_deletes=1)
    estimate = add_up(stage, after)
    status.update(action="loading", night=plan.night, inserted=len(plan.inserts), unchanged=plan.unchanged,
                  kept_staged=plan.kept_staged, retired=len(plan.retire), closed=len(plan.close),
                  reopened=len(plan.reopen), deleted=len(plan.cleanup), dropped_staged=len(plan.drop),
                  orphan_sources=len(plan.orphans),
                  terms={"total": terms_after, "night": len(found.terms), "added": plan.terms_new,
                         "refolded": len(plan.terms_add) - plan.terms_new, "removed": len(plan.terms_drop)},
                  written_estimate=estimate)
    log(f"night {plan.night}: {len(plan.inserts):,} records to write, {plan.unchanged:,} unchanged, "
        f"{plan.kept_staged:,} already staged, {len(plan.retire):,} to retire (kept a night), "
        f"{len(plan.cleanup):,} retired earlier to delete after the switch; about {estimate['total']:,} D1 rows")
    db.room(estimate["total"], f"Night {plan.night} ({index})")

    # Stage night N+1. Readers of night N see none of this.
    db.execute(meta_upsert([["staging", str(plan.night)]]))
    db.execute(by_rid("DELETE FROM sources WHERE rid IN (", plan.drop + plan.orphans)
               + by_rid("DELETE FROM records WHERE rid IN (", plan.drop))
    db.execute(by_rid(f"UPDATE records SET v_to = {OPEN} WHERE rid IN (", plan.reopen))
    db.execute(inserts("terms", ("field", "value", "folded"), plan.terms_add,
                       " ON CONFLICT (field, value) DO UPDATE SET folded = excluded.folded"))
    next_rid = max([rid for rid, *_ in rows] + [as_int(db.query("SELECT MAX(rid) AS m FROM sources")[0]["m"] or 0)]) + 1
    write_records(db, recording, limit, plan, next_rid, log)
    db.execute(by_rid(f"UPDATE records SET v_to = {plan.night} WHERE rid IN (", plan.close))

    # The switch: current, version, timestamp and loaded_at in one statement, once night
    # N+1 holds exactly the recording's records.
    staged = as_int(db.query("SELECT COUNT(*) AS n FROM records WHERE v_from <= ? AND v_to > ?",
                             [plan.night, plan.night])[0]["n"])
    if staged != len(found.keys):
        raise RuntimeError(f"night {plan.night} holds {staged:,} rows, the recording {len(found.keys):,}; "
                           "not switching (the next run reconciles the staged rows)")
    db.room(after["total"], "The switch and cleanup")
    db.execute(meta_upsert([["current", str(plan.night)], ["version", index], ["timestamp", found.timestamp or ""],
                            ["loaded_at", now()]]))
    status["action"] = "switched"
    log(f"switched to night {plan.night} ({index})")

    # Cleanup, a night behind: rows no night >= N reads (v_to <= N), then terms no remaining
    # row uses. Rows retired at this switch stay for answers still reading night N.
    statements = by_rid("DELETE FROM sources WHERE rid IN (", plan.cleanup)
    statements += by_rid("DELETE FROM records WHERE rid IN (", plan.cleanup)
    for field in TERM_FIELDS:
        values = [quote(v) for f, v in plan.terms_drop if f == field]
        statements += packed(f"DELETE FROM terms WHERE field = {quote(field)} AND value IN (", values, ");")
    statements.append("DELETE FROM meta WHERE key = 'staging';")
    db.execute(statements)
    status["action"] = "loaded"
    return finish(db, status, started)


def write_records(db: Target, recording: Recording, limit: int | None, plan: Plan, rid: int,
                  log: Callable[[str], None]) -> None:
    """The second pass: sources then records rows for plan.inserts, CHUNK_RECORDS at a time.
    Sources go first, so every records row has its sources row even if a run stops here."""
    sources: list[list[Any]] = []
    records: list[list[Any]] = []
    done = 0

    def flush() -> None:
        nonlocal done
        if records:
            # OR IGNORE: a request D1 applied but whose answer was lost, sent again, is a no-op.
            db.execute(inserts("sources", ("rid", "json"), sources, verb="INSERT OR IGNORE")
                       + inserts("records", RECORD_COLUMNS, records, verb="INSERT OR IGNORE"))
            done += len(records)
            if done % 50_000 < len(records) or done == len(plan.inserts):
                log(f"  wrote {done:,} of {len(plan.inserts):,} records ({db.rows_written:,} rows so far)")
            sources.clear()
            records.clear()

    for position, (_id, source) in enumerate(recording.records(limit)):
        if position not in plan.inserts:
            continue
        sources.append([rid, source_json(source)])
        records.append(record_row(rid, plan.night, record_id(_id, source), source, record_hash(source)))
        rid += 1
        if len(records) >= CHUNK_RECORDS:
            flush()
    flush()


# ---------- churn ----------

def diff(a: Path | str, b: Path | str, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Two recordings compared record by record, by _id and content hash."""
    started = time.monotonic()
    first, second = Recording(a), Recording(b)
    old: dict[int, tuple[str, str, int, Any]] = {}   # id -> (hash, canonical text, key order, _timestamp)
    orders: dict[tuple, int] = {}
    stamps = (Counter(), Counter())
    term_sets: tuple[set, set] = (set(), set())
    log(f"reading {first.path} ({first.index})")
    for _id, source in first.records():
        text = canonical(source)
        old[record_id(_id, source)] = (sha(text), text, orders.setdefault(tuple(source), len(orders)),
                                       source.get("_timestamp"))
        stamps[0][source.get("_timestamp")] += 1
        term_sets[0].update(term_values(source))
    log(f"reading {second.path} ({second.index})")
    counts: Counter = Counter()
    fields: Counter = Counter()
    seen: set[int] = set()
    added_content: dict[str, int] = {}   # id-less content hash of each added record -> its id
    for _id, source in second.records():
        ident = record_id(_id, source)
        stamps[1][source.get("_timestamp")] += 1
        term_sets[1].update(term_values(source))
        before = old.get(ident)
        if before is None:
            counts["added"] += 1
            added_content.setdefault(sha(canonical(source, ("_timestamp", "id"))), ident)
            continue
        seen.add(ident)
        text = canonical(source)
        if before[0] == sha(text):
            counts["unchanged"] += 1
            counts["unchanged_but__timestamp_differs"] += before[3] != source.get("_timestamp")
            counts["unchanged_but_key_order_differs"] += orders.setdefault(tuple(source), len(orders)) != before[2]
            continue
        counts["changed"] += 1
        was, now_ = json.loads(before[1]), json.loads(text)
        missing = object()
        for key in sorted(set(was) | set(now_)):
            if was.get(key, missing) != now_.get(key, missing):
                fields[key] += 1
    removed = [ident for ident in old if ident not in seen]
    same_content: list[list[int]] = []
    for ident in removed:
        twin = added_content.get(sha(canonical(json.loads(old[ident][1]), ("id",))))
        if twin is not None:
            same_content.append([ident, twin])
    terms_added = term_sets[1] - term_sets[0]
    terms_removed = term_sets[0] - term_sets[1]
    changed = counts["changed"]
    # Cleanup lags a night: the switch to B writes the new rows and closes the old ones; the
    # switch after it deletes the rows B retired and the terms only they used.
    at_switch = written(inserts=counts["added"] + changed, closes=changed + len(removed),
                        terms_added=len(terms_added), meta_inserts=1, meta_updates=len(SWITCH_KEYS), meta_deletes=1)
    next_switch = written(deletes=changed + len(removed), terms_removed=len(terms_removed))

    def side(recording: Recording, records: int, stamp: Counter, terms: set) -> dict[str, Any]:
        return {"index": recording.index, "records": records, "priced_records": recording.summary.get("priced_records"),
                "distinct_timestamps": len(stamp), "timestamps": dict(stamp.most_common(5)),
                "terms": dict(Counter(f for f, _ in terms))}

    return {
        "a": side(first, len(old), stamps[0], term_sets[0]),
        "b": side(second, sum(stamps[1].values()), stamps[1], term_sets[1]),
        "added": counts["added"], "removed": len(removed), "changed": changed, "unchanged": counts["unchanged"],
        "unchanged_but__timestamp_differs": counts["unchanged_but__timestamp_differs"],
        "unchanged_but_key_order_differs": counts["unchanged_but_key_order_differs"],
        "churn_pct": round(100 * (counts["added"] + changed + len(removed)) / max(1, len(old)), 3),
        "same_content_new_id": {"count": len(same_content), "examples": same_content[:5]},
        "changed_keys": dict(fields.most_common()),
        "terms": {"added": dict(Counter(f for f, _ in terms_added)),
                  "removed": dict(Counter(f for f, _ in terms_removed))},
        "projected_rows_written": add_up(at_switch, next_switch),
        "projected_split": {"at_switch": at_switch, "next_switch": next_switch},
        "seconds": round(time.monotonic() - started, 1),
    }


# ---------- refresh ----------

def gsa_index(work: Path, gap: float, max_calls: int) -> str | None:
    """GSA's current index name, from one page_size=1 answer (recorded in work)."""
    rec = Recorder(work, gap, max_calls)
    try:
        rec.get(WHOLE_QUERY, strict=True)
    finally:
        rec.manifest.close()
    return rec.index


def refresh(db: Target, rec: Path | str | None = None, *, work: Path | str | None = None, gap: float = 7.5,
            max_calls: int = 2000, allow_short: bool = False, log: Callable[[str], None] = print,
            status: dict[str, Any] | None = None) -> dict[str, Any]:
    """GSA's index unchanged: no writes. Otherwise record it (or take --rec) and build change-only."""
    started = (time.monotonic(), db.rows_written, db.rows_read)
    status = {} if status is None else status
    version = stored_meta(db).get("version")
    if rec is None:
        work = Path(work) if work else Path(tempfile.mkdtemp(prefix="gsa-calc-refresh-"))
        index = gsa_index(work, gap, max_calls)
    else:
        index = Recording(rec).index
    status.update(command="refresh", index=index, previous={"version": version})
    if index == version:
        log(f"GSA still serves {index}; nothing to do")
        status.update(action="unchanged", written_estimate=written())
        return finish(db, status, started)
    if rec is None:
        log(f"GSA serves {index}; the copy holds {version}. Recording into {work}")
        record(argparse.Namespace(out=str(work), gap=gap, max_calls=max_calls))
        rec = work
    build(db, rec, log=log, allow_short=allow_short, status=status)
    status["command"] = "refresh"
    return finish(db, status, started)


# ---------- command line ----------

def target(args: argparse.Namespace) -> Target:
    if args.remote:
        token = os.environ.get("CLOUDFLARE_D1_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
        if not token:
            raise SystemExit("Set CLOUDFLARE_D1_TOKEN.")
        account = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or wrangler_config().get("account_id")
        db = RemoteD1(database_id(args.database_id), token, account,
                      max_rows=MAX_ROWS if args.max_rows is None else args.max_rows)
        ensure_schema(db)
        return db
    if args.local:
        return LocalD1(args.local, max_rows=args.max_rows)
    raise SystemExit("Pass --remote or --local PATH.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "probe"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--gap", type=float, default=7.5)
        p.add_argument("--max-calls", type=int, default=2000)
        if name == "probe":
            p.add_argument("--list", default=str(PROBES))
    for name, text in (("build", "recording -> database as the next night, change-only"),
                       ("refresh", "GSA's new index -> recording -> database, change-only")):
        p = sub.add_parser(name, help=text)
        where = p.add_mutually_exclusive_group(required=True)
        where.add_argument("--remote", action="store_true", help="write to the gsa-calc D1 database")
        where.add_argument("--local", type=Path, help="write to this sqlite file")
        p.add_argument("--database-id")
        p.add_argument("--max-rows", type=int, help=f"stop before a run passes this many rows (remote default {MAX_ROWS:,})")
        p.add_argument("--allow-short", action="store_true",
                       help="load a recording with fewer records than GSA counts (closes the missing ones)")
        p.add_argument("--json", type=Path, help="also write the run's status here")
        if name == "build":
            p.add_argument("--rec", required=True, type=Path, help="recording directory (or its parent with pull/)")
            p.add_argument("--limit", type=int, help="load only the first N records (a sample)")
        else:
            p.add_argument("--rec", type=Path, help="use this recording instead of recording GSA (tests, reruns)")
            p.add_argument("--work", type=Path, help="record into this directory (default: a new temporary one)")
            p.add_argument("--gap", type=float, default=7.5)
            p.add_argument("--max-calls", type=int, default=2000)
    p = sub.add_parser("diff", help="churn between two recordings")
    p.add_argument("--a", required=True, type=Path, help="the earlier recording")
    p.add_argument("--b", required=True, type=Path, help="the later recording")
    p.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args(argv)

    if args.command in ("record", "probe"):
        try:
            return {"record": record, "probe": probe}[args.command](args)
        except IndexChanged as error:
            print(f"ABORTED: {error}", file=sys.stderr)
            return 3

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def emit(stats: dict[str, Any]) -> None:
        text = json.dumps(stats, indent=2, default=str)
        print(text)
        if args.json:
            args.json.write_text(text + "\n")

    if args.command == "diff":
        emit(diff(args.a, args.b, log))
        return 0

    db = target(args)
    stats: dict[str, Any] = {}
    code = 0
    try:
        if args.command == "build":
            build(db, args.rec, args.limit, log, args.allow_short, stats)
        else:
            refresh(db, args.rec, work=args.work, gap=args.gap, max_calls=args.max_calls,
                    allow_short=args.allow_short, log=log, status=stats)
    except (RowCap, Refused) as exc:
        log(f"stopped: {exc}")
        stats["stopped"] = str(exc)
        code = 2
    except IndexChanged as exc:
        log(f"ABORTED: {exc}")
        stats["stopped"] = str(exc)
        code = 3
    except Exception as exc:  # D1 trouble: still say what was written
        log(traceback.format_exc())
        stats["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    stats["rows_written"] = db.rows_written
    stats["rows_read"] = db.rows_read
    if isinstance(db, RemoteD1):
        stats["d1_requests"] = db.calls
    log(f"rows written: {db.rows_written:,}")
    emit(stats)
    return code


if __name__ == "__main__":
    sys.exit(main())
