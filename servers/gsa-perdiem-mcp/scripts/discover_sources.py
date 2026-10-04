#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Derive scripts/sources.json from GSA's per diem files page.

GSA labels every file the same way ("FY 27 Per Diem Rates", "FY 27 Per Diem
ZIP Code ... - published 9/03/2026", "FY 25-Present M&IE Breakdown"), so the
page alone says which rate, ZIP, and M&IE files belong to each fiscal year.
A fiscal year is added only once GSA posts both its rate and ZIP files.

    uv run python scripts/discover_sources.py          # report differences
    uv run python scripts/discover_sources.py --write  # update sources.json

Exits 0 when sources.json already matches the page, 1 when it differs (after
writing, with --write), and 2 when the page cannot be read or parsed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

FILES_PAGE = "https://www.gsa.gov/travel/plan-a-trip/per-diem-rates/per-diem-files"
SOURCES_FILE = Path(__file__).resolve().parent / "sources.json"
UA = {"User-Agent": "gsa-perdiem-mcp source check (+https://github.com/1102tools-dev/federal-contracting-mcps)"}

_LINK = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_RATES = re.compile(r"^FY (\d\d) Per Diem Rates \[")
_ZIP = re.compile(r"^FY (\d\d) Per Diem ZIP Code \[")
_MIE = re.compile(r"^FY (\d\d)-(\d\d|Present) M&IE Breakdown \[", re.I)
_PUBLISHED = re.compile(r"^\s*-\s*published\s+(\d{1,2})/(\d{1,2})/(\d{4})")


class DiscoveryError(RuntimeError):
    pass


def _year(two_digits: str) -> int:
    return 2000 + int(two_digits)


def parse_page(page: str) -> tuple[dict[int, str], dict[int, tuple[str, str]], list[tuple[int, int | None, str]]]:
    """Return rate files, ZIP files (with published date), and M&IE spans."""
    rates: dict[int, str] = {}
    zips: dict[int, tuple[str, str]] = {}
    mies: list[tuple[int, int | None, str]] = []
    links = list(_LINK.finditer(page))
    for i, m in enumerate(links):
        url = html.unescape(m.group(1)).strip()
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        if not url.startswith("https://www.gsa.gov/system/files/"):
            continue
        if r := _RATES.match(text):
            rates.setdefault(_year(r.group(1)), url)
        elif z := _ZIP.match(text):
            tail = page[m.end(): links[i + 1].start() if i + 1 < len(links) else len(page)]
            p = _PUBLISHED.match(html.unescape(re.sub(r"<[^>]+>", " ", tail)))
            if not p:
                raise DiscoveryError(f"{text}: no 'published' date after the link")
            month, day, year = (int(x) for x in p.groups())
            zips.setdefault(_year(z.group(1)), (url, dt.date(year, month, day).isoformat()))
        elif e := _MIE.match(text):
            last = None if e.group(2).lower() == "present" else _year(e.group(2))
            mies.append((_year(e.group(1)), last, url))
    if not rates or not zips or not mies:
        raise DiscoveryError(f"{FILES_PAGE}: found {len(rates)} rate, {len(zips)} ZIP, {len(mies)} M&IE links")
    return rates, zips, mies


def _covers(first: int, last: int | None) -> str:
    return f"FY{first}-present" if last is None else f"FY{first}-FY{last}"


def derive(page: str, first_year: int) -> dict:
    """Build the sources.json structure for first_year onward from the page."""
    rates, zips, mies = parse_page(page)
    fiscal_years: dict[str, dict[str, str]] = {}
    mie_covers: dict[str, str] = {}
    for fy in sorted(set(rates) & set(zips)):
        if fy < first_year:
            continue
        spans = [(f, l, u) for f, l, u in mies if f <= fy and (l is None or fy <= l)]
        if len(spans) != 1:
            raise DiscoveryError(f"FY{fy}: expected one M&IE breakdown covering it, found {len(spans)}")
        first, last, mie = spans[0]
        mie_covers[mie] = _covers(first, last)
        zip_url, published = zips[fy]
        fiscal_years[str(fy)] = {"rates": rates[fy], "zip": zip_url, "zip_published": published, "mie": mie}
    return {"fiscal_years": fiscal_years, "mie_covers": mie_covers}


def fetch_page() -> str:
    with urllib.request.urlopen(urllib.request.Request(FILES_PAGE, headers=UA), timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def diff(current: dict, derived: dict) -> list[str]:
    changes = []
    for fy in sorted(set(current["fiscal_years"]) | set(derived["fiscal_years"])):
        before, after = current["fiscal_years"].get(fy), derived["fiscal_years"].get(fy)
        if before is None:
            changes.append(f"- FY{fy}: new fiscal year on GSA's files page")
        elif after is None:
            changes.append(f"- FY{fy}: no longer listed on GSA's files page")
        elif before != after:
            fields = ", ".join(k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k))
            changes.append(f"- FY{fy}: {fields} changed on GSA's files page")
    if current["mie_covers"] != derived["mie_covers"]:
        changes.append("- M&IE breakdown spans changed on GSA's files page")
    return changes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write", action="store_true", help="update scripts/sources.json")
    p.add_argument("--page", type=Path, help="read a saved copy of the files page instead (testing)")
    args = p.parse_args(argv)
    current = json.loads(SOURCES_FILE.read_text())
    try:
        page = args.page.read_text() if args.page else fetch_page()
        derived = derive(page, min(int(fy) for fy in current["fiscal_years"]))
    except Exception as e:  # noqa: BLE001 - any failure means no automatic change
        print(f"Could not derive per diem sources from {FILES_PAGE}: {e}", file=sys.stderr)
        return 2
    removed = set(current["fiscal_years"]) - set(derived["fiscal_years"])
    if removed:
        print(f"GSA's files page no longer lists FY{', FY'.join(sorted(removed))}; not changing sources.json",
              file=sys.stderr)
        return 2
    changes = diff(current, derived)
    if not changes:
        print("scripts/sources.json matches GSA's files page.")
        return 0
    print("\n".join(changes))
    if args.write:
        SOURCES_FILE.write_text(json.dumps(derived, indent=2) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
