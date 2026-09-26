#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Build the bundled BLS OEWS database from BLS's published flat files.

Run from servers/bls-oews-mcp:

    uv run python scripts/build_oews_db.py --cache ~/.cache/bls-oews-sources

No API key is used. Every source is a public file under
https://download.bls.gov/pub/time.series/oe/ whose URL, size, SHA-256, and
Last-Modified date are recorded in data/manifest.json. The build fails
loudly on schema drift: changed headers, an unexpected datatype set, more
than one release in the data file, codes missing from the mapping files, or
row counts that move more than 10% from the previous bundled build.

The output is one SQLite database, gzipped, with a row per OEWS estimate
cell (area type + area + industry + occupation) and a value and footnote
column per datatype. The series ID minus its two-digit datatype suffix is
the primary key, so a tool's 25-character series ID maps to one row and
one column.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "src" / "bls_oews_mcp"

SCHEMA_VERSION = 1
BUILDER_VERSION = 1
BASE = "https://download.bls.gov/pub/time.series/oe/"
# download.bls.gov answers 403 to clients without a descriptive User-Agent.
USER_AGENT = "1102tools research (james@1102tools.com)"

DATATYPES = tuple(f"{i:02d}" for i in range(1, 18))
HEADERS = {
    "oe.data.0.Current": ["series_id", "year", "period", "value", "footnote_codes"],
    "oe.area": ["state_code", "area_code", "areatype_code", "area_name"],
    "oe.industry": ["industry_code", "industry_name", "display_level", "selectable", "sort_sequence"],
    "oe.occupation": ["occupation_code", "occupation_name", "occupation_description",
                      "display_level", "selectable", "sort_sequence"],
    "oe.datatype": ["datatype_code", "datatype_name"],
    "oe.footnote": ["footnote_code", "footnote_text"],
    "oe.release": ["release_date", "description"],
}
AREATYPES = {"N", "S", "M"}


class BuildError(RuntimeError):
    pass


def fail(msg: str) -> None:
    raise BuildError(msg)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})


def head(url: str) -> dict[str, object]:
    with urllib.request.urlopen(_request(url, "HEAD"), timeout=60) as r:
        modified = r.headers.get("Last-Modified")
        length = r.headers.get("Content-Length")
        return {
            "last_modified": parsedate_to_datetime(modified).date().isoformat() if modified else None,
            "etag": r.headers.get("ETag"),
            "bytes": int(length) if length else None,
        }


def fetch(name: str, cache: Path) -> tuple[Path, dict[str, object]]:
    """Download one BLS file into the cache (reusing a cached copy whose size
    matches the server's), and return its path and manifest metadata."""
    url = BASE + name
    info = head(url)
    path = cache / name
    if not path.exists() or (info["bytes"] is not None and path.stat().st_size != info["bytes"]):
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(_request(url), timeout=600) as r, tmp.open("wb") as out:
            shutil.copyfileobj(r, out, 1 << 20)
        tmp.replace(path)
    size = path.stat().st_size
    if not size:
        fail(f"Empty download: {url}")
    if info["bytes"] is not None and size != info["bytes"]:
        fail(f"{name}: downloaded {size} bytes but the server reports {info['bytes']}")
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return path, {"url": url, "bytes": size, "sha256": digest.hexdigest(),
                  "last_modified": info["last_modified"], "etag": info["etag"]}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def read_table(path: Path):
    """Yield stripped fields of a BLS tab-separated file after checking its header."""
    name = path.name
    with path.open(encoding="utf-8", newline="") as f:
        header = [h.strip() for h in f.readline().rstrip("\r\n").split("\t")]
        if header != HEADERS[name]:
            fail(f"{name}: header changed. Expected {HEADERS[name]}, got {header}")
        for lineno, line in enumerate(f, start=2):
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            fields = [x.strip() for x in line.split("\t")]
            if len(fields) != len(header):
                fail(f"{name}:{lineno}: expected {len(header)} fields, got {len(fields)}")
            yield fields


def load_mapping(path: Path, key_index: int = 0) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for fields in read_table(path):
        key = fields[key_index]
        if key in out:
            fail(f"{path.name}: duplicate code {key!r}")
        out[key] = fields
    if not out:
        fail(f"{path.name}: no rows")
    return out


def load_release(path: Path) -> dict[str, str]:
    rows = list(read_table(path))
    if len(rows) != 1:
        fail(f"oe.release: expected one release row, got {len(rows)}")
    code, description = rows[0]
    if len(code) != 7 or not code[:4].isdigit() or code[4:] != "A01":
        fail(f"oe.release: unexpected release code {code!r}")
    return {"code": code, "description": description, "year": code[:4], "period": code[4:]}


def load_cells(path: Path, release: dict[str, str], areas, industries, occupations, footnotes):
    """Pivot the long data file into {cell_key: {datatype: (value, footnote_codes)}}."""
    cells: dict[str, dict[str, tuple[str, str]]] = {}
    seen_datatypes: set[str] = set()
    rows = 0
    for sid, year, period, value, codes in read_table(path):
        rows += 1
        if len(sid) != 25 or not sid.startswith("OEU") or sid[3] not in AREATYPES:
            fail(f"{path.name}: malformed series ID {sid!r}")
        if year != release["year"] or period != release["period"]:
            fail(f"{path.name}: {sid} is {year} {period}, not the {release['code']} release")
        key, datatype = sid[:23], sid[23:]
        if datatype not in DATATYPES:
            fail(f"{path.name}: {sid} has unknown datatype {datatype!r}")
        area, industry, occupation = sid[4:11], sid[11:17], sid[17:23]
        if area not in areas:
            fail(f"{path.name}: {sid} uses area {area} missing from oe.area")
        if industry not in industries:
            fail(f"{path.name}: {sid} uses industry {industry} missing from oe.industry")
        if occupation not in occupations:
            fail(f"{path.name}: {sid} uses occupation {occupation} missing from oe.occupation")
        if areas[area][2] != sid[3]:
            fail(f"{path.name}: {sid} area type {sid[3]} disagrees with oe.area ({areas[area][2]})")
        for code in filter(None, (c.strip() for c in codes.split(","))):
            if code not in footnotes:
                fail(f"{path.name}: {sid} uses footnote {code!r} missing from oe.footnote")
        if not value:
            fail(f"{path.name}: {sid} has an empty value")
        cell = cells.setdefault(key, {})
        if datatype in cell:
            fail(f"{path.name}: duplicate series {sid}")
        cell[datatype] = (value, codes)
        seen_datatypes.add(datatype)
    if seen_datatypes != set(DATATYPES):
        fail(f"{path.name}: datatypes {sorted(seen_datatypes)} differ from 01-17")
    return cells, rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_database(path: Path, cells, areas, industries, occupations, datatypes, footnotes, release) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("PRAGMA page_size = 4096")
    con.execute("PRAGMA journal_mode = OFF")
    value_cols = ", ".join(f"v{d} TEXT" for d in DATATYPES)
    note_cols = ", ".join(f"f{d} TEXT" for d in DATATYPES)
    con.executescript(f"""
        CREATE TABLE cell (key TEXT PRIMARY KEY, {value_cols}, {note_cols}) WITHOUT ROWID;
        CREATE TABLE area (area_code TEXT PRIMARY KEY, areatype_code TEXT NOT NULL,
                           state_code TEXT NOT NULL, area_name TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE industry (industry_code TEXT PRIMARY KEY, industry_name TEXT NOT NULL,
                               display_level INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE occupation (occupation_code TEXT PRIMARY KEY, occupation_name TEXT NOT NULL,
                                 display_level INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE datatype (datatype_code TEXT PRIMARY KEY, datatype_name TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE footnote (footnote_code TEXT PRIMARY KEY, footnote_text TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
    """)
    placeholders = ", ".join("?" * (1 + 2 * len(DATATYPES)))
    con.executemany(
        f"INSERT INTO cell VALUES ({placeholders})",
        (
            (key,
             *(cells[key].get(d, (None, None))[0] for d in DATATYPES),
             *((cells[key].get(d, (None, ""))[1] or None) for d in DATATYPES))
            for key in sorted(cells)
        ),
    )
    con.executemany("INSERT INTO area VALUES (?, ?, ?, ?)",
                    ((c, v[2], v[0], v[3]) for c, v in sorted(areas.items())))
    con.executemany("INSERT INTO industry VALUES (?, ?, ?)",
                    ((c, v[1], int(v[2])) for c, v in sorted(industries.items())))
    con.executemany("INSERT INTO occupation VALUES (?, ?, ?)",
                    ((c, v[1], int(v[3])) for c, v in sorted(occupations.items())))
    con.executemany("INSERT INTO datatype VALUES (?, ?)", ((c, v[1]) for c, v in sorted(datatypes.items())))
    con.executemany("INSERT INTO footnote VALUES (?, ?)", ((c, v[1]) for c, v in sorted(footnotes.items())))
    con.executemany("INSERT INTO meta VALUES (?, ?)", sorted({
        "schema": str(SCHEMA_VERSION),
        "release_code": release["code"],
        "release": release["description"],
        "data_year": release["year"],
        "period": release["period"],
    }.items()))
    con.commit()
    con.execute("VACUUM")
    con.close()


def write_gz(src: Path, dest: Path) -> None:
    with src.open("rb") as f, dest.open("wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as gz:
            shutil.copyfileobj(f, gz, 1 << 20)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_prior(counts: dict[str, int], prior_manifest: Path) -> None:
    if not prior_manifest.exists():
        return
    prior = json.loads(prior_manifest.read_text()).get("counts", {})
    for label in ("data_rows", "cells", "areas", "occupations"):
        before, now = prior.get(label), counts[label]
        if before and abs(now - before) > 0.1 * before:
            fail(f"{label} changed by more than 10% from the bundled build ({before} -> {now})")


def build(cache: Path, out: Path) -> dict[str, object]:
    sources: dict[str, dict[str, object]] = {}
    paths: dict[str, Path] = {}
    for name in HEADERS:
        paths[name], sources[name] = fetch(name, cache)
    release = load_release(paths["oe.release"])
    areas = load_mapping(paths["oe.area"], key_index=1)
    industries = load_mapping(paths["oe.industry"])
    occupations = load_mapping(paths["oe.occupation"])
    datatypes = load_mapping(paths["oe.datatype"])
    footnotes = load_mapping(paths["oe.footnote"])
    if set(datatypes) != set(DATATYPES):
        fail(f"oe.datatype: codes {sorted(datatypes)} differ from 01-17")
    bad_types = {v[2] for v in areas.values()} - AREATYPES
    if bad_types:
        fail(f"oe.area: unexpected area types {sorted(bad_types)}")
    cells, rows = load_cells(paths["oe.data.0.Current"], release, areas, industries, occupations, footnotes)
    counts = {
        "data_rows": rows,
        "cells": len(cells),
        "areas": len({k[4:11] for k in cells}),
        "industries": len({k[11:17] for k in cells}),
        "occupations": len({k[17:23] for k in cells}),
    }
    check_prior(counts, out / "manifest.json")

    year = release["year"]
    db_name, gz_name = f"oews-{year}.sqlite", f"oews-{year}.sqlite.gz"
    staged_db, staged_gz = out / f".{db_name}.tmp", out / f".{gz_name}.tmp"
    write_database(staged_db, cells, areas, industries, occupations, datatypes, footnotes, release)
    write_gz(staged_db, staged_gz)
    manifest = {
        "schema": SCHEMA_VERSION,
        "builder": BUILDER_VERSION,
        "data_year": year,
        "release": release,
        "retrieved": dt.date.today().isoformat(),
        "file": gz_name,
        "file_sha256": sha256_file(staged_gz),
        "database_sha256": sha256_file(staged_db),
        "database_bytes": staged_db.stat().st_size,
        "counts": counts,
        "sources": sources,
    }
    staged_db.unlink()
    # Publish atomically only after everything validated.
    for old in out.glob("oews-*.sqlite.gz"):
        if old.name != gz_name:
            old.unlink()
    staged_gz.replace(out / gz_name)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache", type=Path, required=True, help="directory for downloaded source files")
    p.add_argument("--out", type=Path, default=PKG / "data")
    args = p.parse_args(argv)
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        manifest = build(args.cache, args.out)
    except BuildError as e:
        for tmp in args.out.glob(".oews-*.tmp"):
            tmp.unlink()
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 1
    print(f"{manifest['release']['description']}: {manifest['counts']} -> {manifest['file']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
