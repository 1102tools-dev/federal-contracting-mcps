#!/usr/bin/env python3
"""Copy or verify the canonical response cache in the five live-API packages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared" / "response_cache.py"
TARGETS = (
    ROOT / "servers" / "ecfr-mcp" / "src" / "ecfr_mcp" / "_response_cache.py",
    ROOT / "servers" / "federal-register-mcp" / "src" / "federal_register_mcp" / "_response_cache.py",
    ROOT / "servers" / "gsa-calc-mcp" / "src" / "gsa_calc_mcp" / "_response_cache.py",
    ROOT / "servers" / "regulations-gov-mcp" / "src" / "regulationsgov_mcp" / "_response_cache.py",
    ROOT / "servers" / "usaspending-gov-mcp" / "src" / "usaspending_gov_mcp" / "_response_cache.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = SOURCE.read_bytes()
    drifted: list[Path] = []
    for target in TARGETS:
        if args.check:
            if not target.exists() or target.read_bytes() != expected:
                drifted.append(target)
        else:
            target.write_bytes(expected)
    if drifted:
        for target in drifted:
            print(f"response cache drift: {target.relative_to(ROOT)}", file=sys.stderr)
        return 1
    if not args.check:
        print(f"synchronized {len(TARGETS)} response caches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
