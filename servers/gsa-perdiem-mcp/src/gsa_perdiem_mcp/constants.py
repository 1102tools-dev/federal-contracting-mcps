# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants for the GSA Per Diem MCP server."""

from . import __version__

BASE_URL = "https://api.gsa.gov/travel/perdiem/v2/rates"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = f"gsa-perdiem-mcp/{__version__}"
