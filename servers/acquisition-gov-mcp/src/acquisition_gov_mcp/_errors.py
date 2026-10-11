"""Input errors whose messages should reach the user."""

from mcp.server.mcpserver.exceptions import ToolError


class UserInputError(ValueError, ToolError):
    """Bad tool input. MCP SDK 2.3 shows ToolError text and hides other errors;
    subclassing ValueError keeps direct callers working."""
