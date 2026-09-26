#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Report when BLS's published OEWS flat files differ from the bundled database.

Re-downloads the small mapping files recorded in data/manifest.json and
compares SHA-256, checks the large data file's size and Last-Modified date,
and reads oe.release for a release newer than the bundled one. Exits 1 with
a Markdown report on any difference. Never modifies the bundled data;
refreshing is a reviewed release (scripts/build_oews_db.py).
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "src" / "bls_oews_mcp" / "data" / "manifest.json"
# download.bls.gov answers 403 to clients without a descriptive User-Agent.
UA = {"User-Agent": "1102tools research (james@1102tools.com)"}
LARGE = "oe.data.0.Current"


def _open(url: str, method: str = "GET"):
    return urllib.request.urlopen(urllib.request.Request(url, method=method, headers=UA), timeout=120)


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    problems: list[str] = []
    for name, src in sorted(manifest["sources"].items()):
        try:
            if name == LARGE:
                # Not re-downloaded (331 MB): compare the validators BLS sends.
                # Some BLS edge servers omit Content-Length on HEAD, so size
                # is compared only when present.
                with _open(src["url"], "HEAD") as r:
                    length = r.headers.get("Content-Length")
                    modified = r.headers.get("Last-Modified")
                    etag = r.headers.get("ETag")
                modified = parsedate_to_datetime(modified).date().isoformat() if modified else None
                changed = modified != src["last_modified"] or (etag and etag != src.get("etag"))
                if length is not None and int(length) != src["bytes"]:
                    changed = True
                if changed:
                    problems.append(
                        f"- {name}: now modified {modified}, ETag {etag}, {length or '?'} bytes "
                        f"(bundled {src['last_modified']}, {src.get('etag')}, {src['bytes']} bytes) {src['url']}"
                    )
                continue
            with _open(src["url"]) as r:
                body = r.read()
        except Exception as e:  # noqa: BLE001 - report every failure
            problems.append(f"- {name}: download failed ({type(e).__name__}) {src['url']}")
            continue
        if hashlib.sha256(body).hexdigest() != src["sha256"]:
            problems.append(f"- {name}: content changed {src['url']}")
        if name == "oe.release":
            lines = body.decode("utf-8", "replace").splitlines()[1:]
            codes = [line.split("\t")[0].strip() for line in lines if line.strip()]
            bundled = manifest["release"]["code"]
            if codes and codes[0] != bundled:
                problems.append(f"- BLS lists OEWS release {codes[0]} (bundled {bundled}): {src['url']}")
    if problems:
        print("BLS OEWS source files differ from the bundled database:\n")
        print("\n".join(problems))
        print("\nRefresh with `uv run python scripts/build_oews_db.py --cache <dir>` from "
              "servers/bls-oews-mcp, update OEWS_CURRENT_YEAR/OEWS_RELEASE_NAME and the "
              "golden values in tests/test_snapshot.py, run the live parity test "
              "(BLS_LIVE_TESTS=1), bump the version, and release.")
        return 1
    print(f"All {len(manifest['sources'])} BLS OEWS source files match the bundled "
          f"{manifest['release']['description']} release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
