#!/usr/bin/env python3
"""Copy or verify the canonical pacing helper in all eight Python packages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared" / "federal_api_pacing.py"
TARGETS = (
    ROOT / "servers" / "bls-oews-mcp" / "src" / "bls_oews_mcp" / "_pacing.py",
    ROOT / "servers" / "ecfr-mcp" / "src" / "ecfr_mcp" / "_pacing.py",
    ROOT / "servers" / "federal-register-mcp" / "src" / "federal_register_mcp" / "_pacing.py",
    ROOT / "servers" / "gsa-calc-mcp" / "src" / "gsa_calc_mcp" / "_pacing.py",
    ROOT / "servers" / "gsa-perdiem-mcp" / "src" / "gsa_perdiem_mcp" / "_pacing.py",
    ROOT / "servers" / "regulations-gov-mcp" / "src" / "regulationsgov_mcp" / "_pacing.py",
    ROOT / "servers" / "sam-gov-mcp" / "src" / "sam_gov_mcp" / "_pacing.py",
    ROOT / "servers" / "usaspending-gov-mcp" / "src" / "usaspending_gov_mcp" / "_pacing.py",
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
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected)
    if drifted:
        for target in drifted:
            print(f"pacing helper drift: {target.relative_to(ROOT)}", file=sys.stderr)
        return 1
    if not args.check:
        print(f"synchronized {len(TARGETS)} pacing helpers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
