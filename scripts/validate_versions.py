#!/usr/bin/env python3
"""Verify package, module, User-Agent, and MCP version sources agree."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "acquisition-gov-mcp": ("acquisition_gov_mcp", "acquisition-gov-mcp"),
    "bls-oews-mcp": ("bls_oews_mcp", "bls-oews-mcp"),
    "ecfr-mcp": ("ecfr_mcp", "ecfr-mcp"),
    "federal-register-mcp": ("federal_register_mcp", "federal-register-mcp"),
    "gsa-calc-mcp": ("gsa_calc_mcp", "gsa-calc-mcp"),
    "gsa-perdiem-mcp": ("gsa_perdiem_mcp", "gsa-perdiem-mcp"),
    "regulations-gov-mcp": ("regulationsgov_mcp", "regulationsgov-mcp"),
    "sam-gov-mcp": ("sam_gov_mcp", "sam-gov-mcp"),
    "usaspending-gov-mcp": ("usaspending_gov_mcp", "usaspending-gov-mcp"),
}


def main() -> int:
    failures: list[str] = []
    for directory, (module, distribution) in PACKAGES.items():
        project = ROOT / "servers" / directory
        pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        if match is None:
            failures.append(f"{directory}: project version not found")
            continue
        expected = match.group(1)
        code = (
            "import json, importlib.metadata as m; "
            f"import {module} as p; from {module}.constants import USER_AGENT; "
            f"print(json.dumps([m.version('{distribution}'), p.__version__, USER_AGENT]))"
        )
        completed = subprocess.run(
            ["uv", "run", "--project", str(project), "python", "-c", code],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        installed, module_version, user_agent = json.loads(completed.stdout.strip())
        expected_agent = f"{distribution}/{expected}"
        if [installed, module_version, user_agent] != [expected, expected, expected_agent]:
            failures.append(
                f"{directory}: pyproject={expected}, installed={installed}, "
                f"module={module_version}, user-agent={user_agent}"
            )
        server_source = next((project / "src" / module).glob("server.py")).read_text()
        if "version=__version__" not in server_source:
            failures.append(f"{directory}: MCPServer does not use __version__")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"validated version consistency for {len(PACKAGES)} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
