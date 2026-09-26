#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Build the bundled GSA per diem snapshot from GSA's published files.

Run from servers/gsa-perdiem-mcp:

    uv run --with openpyxl --with xlrd python scripts/build_snapshot.py \
        --cache ~/.cache/gsa-perdiem-sources

No API key is used. Every source is a public GSA or Census download whose
URL and SHA-256 are recorded in data/manifest.json. The build fails loudly
on schema drift or on any internal inconsistency between GSA's rate
workbook and ZIP workbook for the same fiscal year.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "src" / "gsa_perdiem_mcp"
sys.path.insert(0, str(PKG.parent))

from gsa_perdiem_mcp._geo import (  # noqa: E402
    COUNTY_ALIASES,
    county_key,
    norm,
    parse_location_defined,
    place_key,
)

SCHEMA_VERSION = 1
BUILDER_VERSION = 1
GSA = "https://www.gsa.gov/system/files/"
CENSUS = "https://www2.census.gov/geo/docs/reference/codes2020/"

# Published dates are from https://www.gsa.gov/travel/plan-a-trip/per-diem-rates/per-diem-files
SOURCES: dict[int, dict[str, str]] = {
    2021: {"rates": GSA + "FY2021_PerDiemMasterRatesFile.xlsx",
           "zip": GSA + "Zip_Code_at_7-10-2020_91805_AM.xls", "zip_published": "2020-07-10",
           "mie": GSA + "MIE_Breakdown_FY2019-present.docx"},
    2022: {"rates": GSA + "FY2022_PerDiemMasterRatesFile.xlsx",
           "zip": GSA + "FY2022_ZipCodeFile.xlsx", "zip_published": "2021-08-12",
           "mie": GSA + "FY%202022%20MIE%20Breakdown_0.docx"},
    2023: {"rates": GSA + "FY2023_PerDiemMasterRatesFile.xlsx",
           "zip": GSA + "FY2023_ZIPCodeFile_081122.xlsx", "zip_published": "2022-07-19",
           "mie": GSA + "FY%202022%20MIE%20Breakdown_0.docx"},
    2024: {"rates": GSA + "FY2024_PerDiemMasterRatesFile_correction.xlsx",
           "zip": GSA + "FY2024_ZIPCodeFile_071123.xlsx", "zip_published": "2023-07-11",
           "mie": GSA + "FY%202022%20MIE%20Breakdown_0.docx"},
    2025: {"rates": GSA + "FY2025_PerDiemMasterRatesFile.xlsx",
           "zip": GSA + "FY2025_ZipCodeFile_080824.xlsx", "zip_published": "2024-08-16",
           "mie": GSA + "FY%202025%20MIE%20Breakdown.docx"},
    2026: {"rates": GSA + "FY2026_PerDiemMasterRatesFile.xlsx",
           "zip": GSA + "FY2026_ZipCodeFile.xlsx", "zip_published": "2025-08-14",
           "mie": GSA + "FY%202025%20MIE%20Breakdown.docx"},
    2027: {"rates": GSA + "FY2027_PerDiemRates_Validated090126.xlsx",
           "zip": GSA + "FY2027PerDiemZipCode_Validated090126.xlsx", "zip_published": "2026-09-03",
           "mie": GSA + "FY%202025%20MIE%20Breakdown.docx"},
}
CENSUS_FILES = {
    "county": CENSUS + "national_county2020.txt",
    "place_by_county": CENSUS + "national_place_by_county2020.txt",
    "cousub": CENSUS + "national_cousub2020.txt",
}

MONTHS = ("Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep")
_MONTH_NUM = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_FY_ORDER = {m: i for i, m in enumerate(MONTHS)}

# ZIP workbook county labels that differ from Census names (validation only).
ZIP_COUNTY_ALIASES = {
    "NY|manhattan": "NY|new york",
    "NY|staten island": "NY|richmond",
    "NY|brooklyn": "NY|kings",
    "FL|miami dade": "FL|miami dade",
    "LA|jeff n davis": "LA|jefferson davis",
    "LA|e baton rouge": "LA|east baton rouge",
    "MT|lewis & clark": "MT|lewis and clark",
    "VA|virginia beach": "VA|virginia beach city",
    "VA|alexandria": "VA|alexandria city",
    "VA|falls church": "VA|falls church city",
    "VA|charlottesville": "VA|charlottesville city",
    "VA|williamsburg": "VA|williamsburg city",
    "VA|richmond": "VA|richmond city",
    "VA|roanoke": "VA|roanoke city",
    "VA|lynchburg": "VA|lynchburg city",
    "VA|fairfax city": "VA|fairfax city",
    "MD|baltimore city": "MD|baltimore city",
    "MO|st louis city": "MO|st louis city",
}

_PLACE_SUFFIX_RE = re.compile(
    r"\s+(city and borough|consolidated government|metropolitan government|unified government|"
    r"urban county|city|town|village|borough|CDP|municipality|township|plantation|gore|grant|"
    r"purchase|location|charter township|corporation)$",
    re.IGNORECASE,
)
_COUSUB_CLASSES = frozenset({"T1", "T5", "T9", "C5", "C7"})


class BuildError(RuntimeError):
    pass


def fail(msg: str) -> None:
    raise BuildError(msg)


# ---------------------------------------------------------------------------
# Download and table reading
# ---------------------------------------------------------------------------

def fetch(url: str, cache: Path) -> tuple[bytes, dict[str, object]]:
    name = urllib.parse.unquote(url.rsplit("/", 1)[1])
    path = cache / name
    if not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "gsa-perdiem-mcp snapshot builder"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        if not data:
            fail(f"Empty download: {url}")
        path.write_bytes(data)
    data = path.read_bytes()
    return data, {"url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_rows(data: bytes, url: str) -> list[list[object]]:
    if url.endswith(".xls"):
        import xlrd

        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
        return [sheet.row_values(i) for i in range(sheet.nrows)]
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if len(wb.worksheets) != 1:
        fail(f"{url}: expected one worksheet, found {[w.title for w in wb.worksheets]}")
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def _text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _int(v: object, field: str, where: str) -> int:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        fail(f"{where}: {field} is not numeric: {v!r}")
    if not f.is_integer() or f <= 0:
        fail(f"{where}: {field} must be a positive whole-dollar amount: {v!r}")
    return int(f)


# ---------------------------------------------------------------------------
# Rate workbook
# ---------------------------------------------------------------------------

def _season_point(v: object, where: str) -> tuple[int, int] | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime | dt.date):
        return v.month, v.day
    s = _text(v)
    if not s:
        return None
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:,\s*\d{4})?$", s)
    if not m or m.group(1)[:3].title() not in _MONTH_NUM:
        fail(f"{where}: unparseable season date {v!r}")
    return _MONTH_NUM[m.group(1)[:3].title()], int(m.group(2))


def _months_between(begin: tuple[int, int], end: tuple[int, int], where: str) -> list[str]:
    last_day = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    if begin[1] != 1:
        fail(f"{where}: season begins mid-month ({begin}); monthly model cannot represent it")
    if end[1] < last_day[end[0]]:
        fail(f"{where}: season ends mid-month ({end}); monthly model cannot represent it")
    names = [k for k, _ in sorted(_MONTH_NUM.items(), key=lambda kv: kv[1])]
    out, m = [], begin[0]
    while True:
        out.append(names[m - 1])
        if m == end[0]:
            return out
        m = m % 12 + 1


def parse_rate_workbook(rows: list[list[object]], fy: int, url: str) -> dict[str, object]:
    header_idx = next(
        (i for i, r in enumerate(rows[:10]) if any(_text(c).upper() == "DESTINATION" for c in r)), None)
    if header_idx is None:
        fail(f"{url}: no DESTINATION header in the first 10 rows")
    hdr = [_text(c).upper() for c in rows[header_idx]]

    def col(pred, label):
        hits = [i for i, h in enumerate(hdr) if pred(h)]
        if len(hits) != 1:
            fail(f"{url}: expected exactly one {label} column, header={hdr}")
        return hits[0]

    c_state = col(lambda h: h == "STATE", "STATE")
    c_dest = col(lambda h: h == "DESTINATION", "DESTINATION")
    c_loc = col(lambda h: h.startswith("COUNTY"), "COUNTY/LOCATION DEFINED")
    c_begin = col(lambda h: h == "SEASON BEGIN", "SEASON BEGIN")
    c_end = col(lambda h: h == "SEASON END", "SEASON END")
    c_lodging = col(lambda h: "LODGING" in h, "Lodging")
    c_mie = col(lambda h: "M&IE" in h, "M&IE")
    fy_tag = f"FY{fy % 100:02d}"
    if fy_tag not in hdr[c_lodging] or fy_tag not in hdr[c_mie]:
        fail(f"{url}: lodging/M&IE headers {hdr[c_lodging]!r}/{hdr[c_mie]!r} are not {fy_tag}")

    standard = None
    dests: dict[tuple[str, str], dict[str, object]] = {}
    for n, r in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        r = list(r) + [None] * (len(hdr) - len(r))
        state, dest = _text(r[c_state]).upper(), _text(r[c_dest])
        where = f"{url} row {n}"
        if not dest and not state:
            continue
        if not state:
            if not dest.lower().startswith("standard conus rate"):
                fail(f"{where}: row without state is not the standard-rate row: {dest!r}")
            if standard is not None:
                fail(f"{where}: duplicate standard-rate row")
            standard = {"lodging": _int(r[c_lodging], "lodging", where), "meals": _int(r[c_mie], "M&IE", where)}
            continue
        key = (state, re.sub(r"\s+", " ", dest))
        loc = re.sub(r"\s+", " ", _text(r[c_loc]))
        d = dests.setdefault(key, {"location_defined": loc, "meals": None, "months": {}})
        if d["location_defined"] != loc:
            fail(f"{where}: {key} has inconsistent location text")
        meals = _int(r[c_mie], "M&IE", where)
        if d["meals"] not in (None, meals):
            fail(f"{where}: {key} has more than one M&IE amount")
        d["meals"] = meals
        lodging = _int(r[c_lodging], "lodging", where)
        begin, end = _season_point(r[c_begin], where), _season_point(r[c_end], where)
        if (begin is None) != (end is None):
            fail(f"{where}: season has only one boundary")
        # FY2027 spells out the full-year season (October 1 - September 30).
        months = list(MONTHS) if begin is None else _months_between(begin, end, where)
        for m in months:
            if m in d["months"]:
                fail(f"{where}: {key} month {m} covered by more than one season")
            d["months"][m] = lodging
    if standard is None:
        fail(f"{url}: no standard-rate row")
    for key, d in dests.items():
        if set(d["months"]) != set(MONTHS):
            fail(f"{url}: {key} seasons do not cover all 12 months: {sorted(d['months'])}")
    return {"standard": standard, "destinations": dests}


# ---------------------------------------------------------------------------
# ZIP workbook
# ---------------------------------------------------------------------------

_ZIP_FIELDS = {"DESTINATIONID": "id", "NAME": "name", "COUNTY": "county", "LOCATIONDEFINED": "location",
               "STATE": "state", "ZIP": "zip", "FISCALYEAR": "fy", "MEALS": "meals"}


def parse_zip_workbook(rows: list[list[object]], fy: int, url: str) -> list[dict[str, object]]:
    hdr = [_text(c).upper().replace(" ", "") for c in rows[0]]
    cols: dict[str, int] = {}
    for i, h in enumerate(hdr):
        if h in _ZIP_FIELDS:
            cols[_ZIP_FIELDS[h]] = i
        elif h.title() in _FY_ORDER:
            cols[h.title()] = i
    missing = [f for f in list(_ZIP_FIELDS.values()) + list(MONTHS) if f not in cols]
    if missing:
        fail(f"{url}: ZIP workbook missing columns {missing}; header={hdr}")
    out = []
    for n, r in enumerate(rows[1:], start=2):
        where = f"{url} row {n}"
        z = _text(r[cols["zip"]])
        if not z and not _text(r[cols["name"]]):
            continue
        if not re.fullmatch(r"\d{5}", z):
            fail(f"{where}: ZIP {z!r} is not a 5-digit string (leading zeros lost?)")
        if _int(r[cols["fy"]], "FiscalYear", where) != fy:
            fail(f"{where}: FiscalYear is not {fy}")
        out.append({
            "id": int(float(r[cols["id"]])),
            "name": re.sub(r"\s+", " ", _text(r[cols["name"]])),
            "county": _text(r[cols["county"]]),
            "state": _text(r[cols["state"]]).upper(),
            "zip": z,
            "months": [_int(r[cols[m]], m, where) for m in MONTHS],
            "meals": _int(r[cols["meals"]], "Meals", where),
        })
    return out


# ---------------------------------------------------------------------------
# M&IE breakdown (.docx)
# ---------------------------------------------------------------------------

def parse_mie_docx(data: bytes, url: str) -> list[dict[str, float]]:
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    tiers = []
    for tr in re.findall(r"<w:tr[ >].*?</w:tr>", xml, re.S):
        cells = ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", tc)) for tc in re.findall(r"<w:tc>.*?</w:tc>", tr, re.S)]
        vals = [c.strip().replace("$", "").replace(",", "") for c in cells]
        if len(vals) != 6 or not all(re.fullmatch(r"\d+(\.\d+)?", v) for v in vals):
            continue
        total, b, l, d, inc, fl = (float(v) for v in vals)
        if abs(b + l + d + inc - total) > 0.001:
            fail(f"{url}: tier {total} components do not sum ({b}+{l}+{d}+{inc})")
        if abs(total * 0.75 - fl) > 0.001:
            fail(f"{url}: tier {total} first/last day {fl} is not 75%")
        tiers.append({"total": total, "breakfast": b, "lunch": l, "dinner": d,
                      "incidental": inc, "first_last_day": fl})
    if len(tiers) < 4:
        fail(f"{url}: found only {len(tiers)} M&IE tier rows")
    return tiers


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------

def _read_pipe(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("latin-1")), delimiter="|"))


def _place_aliases(name: str) -> set[str]:
    base = re.sub(r"\s*\(balance\)$", "", name).strip()
    stripped = _PLACE_SUFFIX_RE.sub("", base).strip()
    out = {stripped}
    # Census names like "Boise City city" / "Carson City": also index "Boise".
    if stripped.lower().endswith(" city") and stripped != base:
        out.add(stripped[: -len(" city")])
    # Consolidated governments: "Nashville-Davidson metropolitan government" -> "Nashville"
    if stripped != base and "-" in stripped and re.search(r"government|urban county", base, re.I):
        out.add(stripped.split("-", 1)[0])
    return {a for a in out if a}


def build_census(files: dict[str, bytes]) -> tuple[set[str], dict[str, list[list[str]]]]:
    counties = {county_key(r["STATE"], r["COUNTYNAME"]) for r in _read_pipe(files["county"])}
    places: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for r in _read_pipe(files["place_by_county"]):
        ck = county_key(r["STATE"], r["COUNTYNAME"])
        for alias in _place_aliases(r["PLACENAME"]):
            places[place_key(r["STATE"], alias)].add((ck, "place"))
    for r in _read_pipe(files["cousub"]):
        if r["CLASSFP"] not in _COUSUB_CLASSES:
            continue
        ck = county_key(r["STATE"], r["COUNTYNAME"])
        for alias in _place_aliases(r["COUSUBNAME"]):
            places[place_key(r["STATE"], alias)].add((ck, "town"))
    for ck in counties:
        places.setdefault(ck, set()).add((ck, "county"))
    index = {k: sorted([list(t) for t in v]) for k, v in sorted(places.items())}
    return counties, index


# ---------------------------------------------------------------------------
# Fiscal-year assembly
# ---------------------------------------------------------------------------

def build_year(fy: int, cache: Path, census_counties: set[str], prior: dict | None) -> tuple[dict, dict]:
    src = SOURCES[fy]
    rate_data, rate_meta = fetch(src["rates"], cache)
    zip_data, zip_meta = fetch(src["zip"], cache)
    mie_data, mie_meta = fetch(src["mie"], cache)
    rates = parse_rate_workbook(read_rows(rate_data, src["rates"]), fy, src["rates"])
    zrows = parse_zip_workbook(read_rows(zip_data, src["zip"]), fy, src["zip"])
    tiers = parse_mie_docx(mie_data, src["mie"])
    std = rates["standard"]

    # Destinations keyed by GSA DestinationID; rates cross-checked across both files.
    by_id: dict[int, dict] = {}
    for z in zrows:
        if z["id"] == 0:
            if z["months"] != [std["lodging"]] * 12 or z["meals"] != std["meals"]:
                fail(f"FY{fy}: ZIP {z['zip']} standard row differs from the rate workbook standard rate")
            continue
        d = by_id.setdefault(z["id"], {"name": z["name"], "months": z["months"], "meals": z["meals"], "states": set()})
        if (d["name"], d["months"], d["meals"]) != (z["name"], z["months"], z["meals"]):
            fail(f"FY{fy}: DestinationID {z['id']} has inconsistent rows (ZIP {z['zip']})")
        d["states"].add(z["state"])

    name_to_id: dict[tuple[str, str], int] = {}
    for did, d in by_id.items():
        for st in d["states"]:
            name_to_id[(st, d["name"])] = did
    destinations = []
    county_map: dict[str, int] = {}
    place_map: dict[str, int] = {}
    excluded: dict[str, list[str]] = {}
    for (st, name), rd in sorted(rates["destinations"].items()):
        did = name_to_id.get((st, name))
        if did is None:
            fail(f"FY{fy}: rate-workbook destination {st} {name!r} has no ZIP-workbook rows")
        zd = by_id[did]
        months = [rd["months"][m] for m in MONTHS]
        if months != zd["months"] or rd["meals"] != zd["meals"]:
            fail(f"FY{fy}: {st} {name!r} monthly lodging/M&IE differs between rate and ZIP workbooks")
        definition, unparsed = parse_location_defined(st, rd["location_defined"])
        if unparsed:
            fail(f"FY{fy}: {st} {name!r} location text needs a pinned definition: "
                 f"{rd['location_defined']!r} (unparsed {unparsed})")
        for ck in definition["counties"]:
            if ck not in census_counties:
                fail(f"FY{fy}: {st} {name!r} county {ck!r} is not a Census 2020 county")
            if county_map.get(ck, did) != did:
                fail(f"FY{fy}: county {ck} assigned to two destinations")
            county_map[ck] = did
        for pk in definition["places"]:
            place_map[pk] = did
        if definition["excluded"]:
            excluded[str(did)] = definition["excluded"]
        destinations.append({
            "id": did, "state": st, "name": name, "location_defined": rd["location_defined"],
            "months": months, "meals": rd["meals"],
        })
    extra = set(by_id) - {d["id"] for d in destinations}
    if extra:
        fail(f"FY{fy}: ZIP-workbook destinations missing from the rate workbook: {sorted(extra)}")

    # Validate ZIP-workbook county labels against the county map built from the rate workbook.
    carve_ids = set(place_map.values()) | {int(k) for k in excluded}
    unexplained = collections.Counter()
    for z in zrows:
        if z["id"] == 0 or not z["county"] or ", " not in z["county"]:
            continue
        cname, cstate = z["county"].rsplit(", ", 1)
        ck = county_key(cstate, cname)
        ck = ZIP_COUNTY_ALIASES.get(ck, COUNTY_ALIASES.get(ck, ck))
        if county_map.get(ck) != z["id"] and z["id"] not in carve_ids and county_map.get(ck) not in carve_ids:
            unexplained[(z["county"], z["name"])] += 1
    if unexplained:
        fail(f"FY{fy}: ZIP-workbook county labels disagree with rate-workbook definitions: "
             f"{unexplained.most_common(10)}")

    totals = {t["total"] for t in tiers}
    used = {d["meals"] for d in destinations} | {std["meals"]}
    if not used <= totals:
        fail(f"FY{fy}: M&IE amounts {sorted(used - totals)} missing from the M&IE breakdown {sorted(totals)}")

    zips: dict[str, list] = collections.defaultdict(list)
    state_members: dict[str, set[int]] = collections.defaultdict(set)
    for z in zrows:
        entry = z["state"] if z["id"] == 0 else z["id"]
        if entry not in zips[z["zip"]]:
            zips[z["zip"]].append(entry)
        if z["id"]:
            state_members[z["state"]].add(z["id"])
    for d in destinations:
        state_members[d["state"]].add(d["id"])

    if prior:
        for label, now, before in (("ZIP rows", len(zrows), prior["zip_rows"]),
                                   ("destinations", len(destinations), prior["destinations"])):
            if abs(now - before) > 0.1 * before:
                fail(f"FY{fy}: {label} changed by more than 10% from FY{fy - 1} ({before} -> {now})")

    snap = {
        "schema": SCHEMA_VERSION,
        "fiscal_year": fy,
        "months": list(MONTHS),
        "standard": {"months": [std["lodging"]] * 12, "meals": std["meals"]},
        "destinations": destinations,
        "state_members": {st: sorted(ids) for st, ids in sorted(state_members.items())},
        "zips": {z: v for z, v in sorted(zips.items())},
        "county_map": dict(sorted(county_map.items())),
        "place_map": dict(sorted(place_map.items())),
        "excluded": dict(sorted(excluded.items())),
        "mie_tiers": sorted(tiers, key=lambda t: t["total"]),
    }
    meta = {
        "fiscal_year": fy,
        "rates": rate_meta,
        "zip": {**zip_meta, "published": src["zip_published"]},
        "mie": mie_meta,
        "counts": {"zip_rows": len(zrows), "zips": len(zips), "destinations": len(destinations),
                   "ambiguous_zips": sum(1 for v in zips.values() if len(v) > 1)},
    }
    return snap, meta


def write_gz(path: Path, obj: object) -> None:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    path.write_bytes(buf.getvalue())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache", type=Path, required=True, help="directory for downloaded source files")
    p.add_argument("--out", type=Path, default=PKG / "data")
    p.add_argument("--years", default=f"{min(SOURCES)}-{max(SOURCES)}")
    args = p.parse_args(argv)
    lo, _, hi = args.years.partition("-")
    years = list(range(int(lo), int(hi or lo) + 1))
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    census_raw, census_meta = {}, {}
    for key, url in CENSUS_FILES.items():
        census_raw[key], census_meta[key] = fetch(url, args.cache)
    counties, places = build_census(census_raw)

    manifest = {"schema": SCHEMA_VERSION, "builder": BUILDER_VERSION, "census": census_meta, "fiscal_years": {}}
    prior = None
    try:
        for fy in years:
            snap, meta = build_year(fy, args.cache, counties, prior)
            prior = {"zip_rows": meta["counts"]["zip_rows"], "destinations": meta["counts"]["destinations"]}
            staged = args.out / f".fy{fy}.json.gz.tmp"
            write_gz(staged, snap)
            meta["file"] = f"fy{fy}.json.gz"
            meta["file_sha256"] = hashlib.sha256(staged.read_bytes()).hexdigest()
            manifest["fiscal_years"][str(fy)] = meta
            print(f"FY{fy}: {meta['counts']}", file=sys.stderr)
    except BuildError as e:
        for tmp in args.out.glob(".fy*.tmp"):
            tmp.unlink()
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 1
    # Publish atomically only after every year validated.
    for fy in years:
        (args.out / f".fy{fy}.json.gz.tmp").replace(args.out / f"fy{fy}.json.gz")
    write_gz(args.out / "places.json.gz", places)
    manifest["places_sha256"] = hashlib.sha256((args.out / "places.json.gz").read_bytes()).hexdigest()
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
