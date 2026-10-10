# SPDX-License-Identifier: MIT
"""Expected user-facing errors across supported MCP SDK versions."""
from mcp.server.mcpserver.exceptions import ToolError


class UserInputError(ValueError, ToolError):
    """A safe validation/domain error that preserves actionable MCP guidance.

    ValueError compatibility preserves direct callers; ToolError tells newer
    SDKs this message is intended for the user rather than an internal failure.
    """


class SourceNotFoundError(RuntimeError, ToolError):
    """An expected missing-source response with safe recovery guidance.

    RuntimeError compatibility preserves direct callers and comparison logic;
    ToolError keeps the not-found explanation visible in newer MCP clients.
    Unexpected provider and internal failures retain their ordinary exceptions.
    """
