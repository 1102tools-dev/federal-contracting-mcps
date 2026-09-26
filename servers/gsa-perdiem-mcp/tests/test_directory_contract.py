# SPDX-License-Identifier: MIT
"""Directory-listing rules: annotations, no model instructions, no key language."""

from __future__ import annotations

import asyncio
import re

from gsa_perdiem_mcp.server import mcp


def _tools():
    return asyncio.run(mcp.list_tools())


def test_every_tool_declares_all_hints():
    tools = _tools()
    assert len(tools) == 7
    for t in tools:
        a = t.annotations
        assert a.title, t.name
        assert a.read_only_hint is True, t.name
        assert a.destructive_hint is False, t.name
        assert a.open_world_hint is not None, t.name
    closed = {t.name for t in tools if t.annotations.open_world_hint is False}
    assert closed == {"get_data_status"}


def test_server_sends_no_instructions():
    assert not mcp.instructions


def test_descriptions_have_no_key_language_or_model_directives():
    for t in _tools():
        text = t.description or ""
        assert "DEMO_KEY" not in text, t.name
        assert not re.search(r"\b(you must|always call|before (the first|any)|call get_)", text, re.I), t.name
