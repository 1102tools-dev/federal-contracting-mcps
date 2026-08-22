"""Regression coverage for the packaged-agent USASpending tool profile."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from usaspending_gov_mcp.server import ACQUISITION_AGENT_TOOLS


def _load_tools(profile: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if profile is None:
        env.pop("USASPENDING_TOOL_PROFILE", None)
    else:
        env["USASPENDING_TOOL_PROFILE"] = profile
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from usaspending_gov_mcp.server import mcp; "
                "print(json.dumps(sorted(t.name for t in mcp._tool_manager.list_tools())))"
            ),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_default_full_profile_preserves_all_55_tools() -> None:
    result = _load_tools(None)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)) == 55


def test_acquisition_agent_profile_exposes_exact_allowlist() -> None:
    result = _load_tools("acquisition-agent")
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout)) == ACQUISITION_AGENT_TOOLS


def test_unknown_profile_fails_startup_clearly() -> None:
    result = _load_tools("not-a-profile")
    assert result.returncode != 0
    assert "Unknown USASPENDING_TOOL_PROFILE='not-a-profile'" in result.stderr
    assert "'full' and 'acquisition-agent'" in result.stderr
