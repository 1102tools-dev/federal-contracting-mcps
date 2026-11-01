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

Standard library only, so it runs on a bare runner.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

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
PROBES = ROOT / "deploy" / "gsa-calc" / "scripts" / "probes.txt"


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
    whole = rec.get("page=1&page_size=1&ordering=current_price&sort=asc", strict=True)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "probe"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--gap", type=float, default=7.5)
        p.add_argument("--max-calls", type=int, default=2000)
        if name == "probe":
            p.add_argument("--list", default=str(PROBES))
    args = parser.parse_args()
    try:
        return {"record": record, "probe": probe}[args.command](args)
    except IndexChanged as error:
        print(f"ABORTED: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
