#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Report when GSA's published per diem files differ from the bundled snapshot.

Re-downloads every GSA source recorded in data/manifest.json and compares
SHA-256, and scans GSA's per diem files page for fiscal years newer than the
latest bundled one. Exits 1 with a Markdown report on any difference. Never
modifies the bundled data; refreshing is a reviewed release
(scripts/build_snapshot.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "src" / "gsa_perdiem_mcp" / "data" / "manifest.json"
FILES_PAGE = "https://www.gsa.gov/travel/plan-a-trip/per-diem-rates/per-diem-files"
UA = {"User-Agent": "gsa-perdiem-mcp source check (+https://github.com/1102tools-dev/federal-contracting-mcps)"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    problems: list[str] = []
    seen: dict[str, str] = {}
    for fy, meta in sorted(manifest["fiscal_years"].items()):
        for kind in ("rates", "zip", "mie"):
            src = meta[kind]
            if src["url"] in seen:
                continue
            try:
                digest = hashlib.sha256(_get(src["url"])).hexdigest()
            except Exception as e:  # noqa: BLE001 - report every failure
                problems.append(f"- FY{fy} {kind}: download failed ({type(e).__name__}) {src['url']}")
                continue
            seen[src["url"]] = digest
            if digest != src["sha256"]:
                problems.append(f"- FY{fy} {kind}: content changed {src['url']}")
    latest = max(int(y) for y in manifest["fiscal_years"])
    try:
        page = _get(FILES_PAGE).decode("utf-8", "replace")
        newer = sorted({int(y) for y in re.findall(r"FY\s?(20\d\d)", page) if int(y) > latest})
        if newer:
            problems.append(f"- GSA lists fiscal year(s) {newer} newer than bundled FY{latest}: {FILES_PAGE}")
    except Exception as e:  # noqa: BLE001
        problems.append(f"- Could not read {FILES_PAGE} ({type(e).__name__})")
    if problems:
        print("GSA per diem source files differ from the bundled snapshot:\n")
        print("\n".join(problems))
        print("\nRefresh with `uv run --with openpyxl --with xlrd python scripts/build_snapshot.py --cache <dir>` "
              "(add new fiscal years to SOURCES), run the live parity tests, bump the version, and release.")
        return 1
    print(f"All {len(seen)} GSA source files match the bundled snapshot; newest bundled FY{latest}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
