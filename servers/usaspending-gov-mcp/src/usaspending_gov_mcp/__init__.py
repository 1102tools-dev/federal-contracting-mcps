# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""USASpending.gov MCP server."""
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("usaspending-gov-mcp")
except PackageNotFoundError:  # source tree without an installed distribution
    __version__ = "0.0.0.dev0"
