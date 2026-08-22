# SPDX-License-Identifier: MIT
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("acquisition-gov-mcp")
except PackageNotFoundError:
    __version__ = "1.0.0"

