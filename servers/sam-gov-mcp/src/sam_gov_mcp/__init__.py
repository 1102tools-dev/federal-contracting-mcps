# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""SAM.gov MCP server."""
# Single source of truth is pyproject.toml via installed metadata. The 1.0.4
# wheel shipped with a hardcoded 1.0.2 here because the round-9 "version sync"
# test compared serverInfo to this constant (circular); both markers now
# derive from the package, and the test pins them to installed metadata.
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("sam-gov-mcp")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0.dev0"
