# SPDX-License-Identifier: MIT
"""Regression tests for 1.0.7 host-neutral credential guidance.

Through 1.0.6 the missing-key error told the user to edit "your Claude Desktop
mcpServers config". That named an application this suite does not support and a
configuration file that does not exist for Codex, Claude Code, or any other MCP
host. The message is the only guidance a user sees at the moment a keyed call
fails, so it must stay host-neutral.

These tests run offline. No key and no network are required.
"""

from __future__ import annotations

import os

import pytest
from mcp.server.mcpserver.exceptions import ToolError

os.environ.setdefault("SAM_API_KEY", "SAM-00000000-0000-0000-0000-000000000000")

import sam_gov_mcp.server as srv  # noqa: E402


# Any product name that would make the message wrong for some supported host.
FORBIDDEN_HOST_NAMES = (
    "claude desktop",
    "claude code",
    "codex",
    "copilot",
    "deepseek",
    "cursor",
    "windsurf",
    "librechat",
    "continue",
    "cline",
)


def _missing_key_message(monkeypatch) -> str:
    monkeypatch.delenv("SAM_API_KEY", raising=False)
    with pytest.raises(ToolError) as excinfo:
        srv._get_api_key()
    return str(excinfo.value)


def test_missing_key_message_names_no_specific_host(monkeypatch):
    message = _missing_key_message(monkeypatch).lower()
    for name in FORBIDDEN_HOST_NAMES:
        assert name not in message, (
            f"missing-key guidance names the specific host {name!r}; it must stay "
            f"host-neutral. Got: {message}"
        )


def test_missing_key_message_names_the_env_var(monkeypatch):
    assert "SAM_API_KEY" in _missing_key_message(monkeypatch)


def test_missing_key_message_points_at_generic_credential_config(monkeypatch):
    message = _missing_key_message(monkeypatch).lower()
    assert "launching environment" in message
    assert "mcp credential configuration" in message


def test_missing_key_message_links_current_help_source(monkeypatch):
    assert "https://sam.gov/help" in _missing_key_message(monkeypatch)


def test_malformed_key_message_names_no_specific_host(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "not-a-sam-key")
    with pytest.raises(ToolError) as excinfo:
        srv._get_api_key()
    message = str(excinfo.value).lower()
    for name in FORBIDDEN_HOST_NAMES:
        assert name not in message, (
            f"malformed-key guidance names the specific host {name!r}. Got: {message}"
        )


def test_valid_key_is_returned_unchanged(monkeypatch):
    key = "SAM-00000000-0000-0000-0000-000000000000"
    monkeypatch.setenv("SAM_API_KEY", f"  {key}  ")
    assert srv._get_api_key() == key
