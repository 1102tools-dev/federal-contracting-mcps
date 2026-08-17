# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants and reference data for the eCFR MCP server."""

BASE_URL = "https://www.ecfr.gov"
DEFAULT_TIMEOUT_JSON = 15.0
DEFAULT_TIMEOUT_STRUCTURE = 30.0
DEFAULT_TIMEOUT_CONTENT = 60.0

# Derived from the installed package so it can never go stale again
# (1.0.1 shipped with this still pinned at 1.0.0).
try:
    from importlib.metadata import version as _pkg_version
    USER_AGENT = f"ecfr-mcp/{_pkg_version('ecfr-mcp')}"
except Exception:  # pragma: no cover - not installed (vendored copy)
    USER_AGENT = "ecfr-mcp/1.0.2"

# eCFR point-in-time coverage starts here. Every versioner request for an
# earlier date is a guaranteed 404.
ECFR_EARLIEST_DATE = "2017-01-03"

# Search caps
SEARCH_MAX_PER_PAGE = 5000
SEARCH_MAX_TOTAL = 10000

# Search result orderings accepted by /api/search/v1/results. Live-verified
# 2026-08-16: each value returns 200 and reorders results; unknown values are
# rejected by the API with {"errors": {"order": ...}}.
SEARCH_ORDERS: frozenset[str] = frozenset({
    "relevance", "newest_first", "oldest_first", "hierarchy", "citations",
})

# Title 48 chapter map (Federal Acquisition Regulations System).
# Authority: the eCFR agencies endpoint (/api/admin/v1/agencies.json) title-48
# references plus the live title-48 structure. A live-gated regression test
# diffs these keys against agencies.json so the map cannot silently drift
# again (round 6 found nine live chapters missing, including the entire HSAR).
TITLE_48_CHAPTERS: dict[str, str] = {
    "1": "FAR (Parts 1-99)",
    "2": "DFARS (Parts 200-299)",
    "3": "HHSAR (Parts 300-399)",
    "4": "AGAR (Parts 400-499)",
    "5": "GSAR (Parts 500-599)",
    "6": "DOSAR (Parts 600-699)",
    "7": "AIDAR (Parts 700-799)",
    "8": "VAAR (Parts 800-899)",
    "9": "DEAR (Parts 900-999)",
    "10": "DTAR (Parts 1000-1099)",
    "12": "TAR (Parts 1200-1299)",
    "13": "CAR (Parts 1300-1399)",
    "14": "DIAR (Parts 1400-1499)",
    "15": "EPAAR (Parts 1500-1599)",
    "16": "FEHBAR, OPM health benefits (Parts 1600-1699)",
    "17": "OPM (Parts 1700-1799)",
    "18": "NFS (Parts 1800-1899)",
    "19": "USAGM, Broadcasting Board of Governors (Parts 1900-1999)",
    "20": "NRCAR (Parts 2000-2099)",
    "21": "LIFAR, OPM group life insurance (Parts 2100-2199)",
    "23": "SSAAR (Parts 2300-2399)",
    "24": "HUDAR (Parts 2400-2499)",
    "25": "NSFAR (Parts 2500-2599)",
    "28": "JAR (Parts 2800-2899)",
    "29": "DOLAR (Parts 2900-2999)",
    "30": "HSAR (Parts 3000-3099)",
    "34": "EDAR, Dept. of Education (Parts 3400-3499)",
    "52": "Dept. of the Navy (Parts 5200-5299)",
    "54": "DLA (Parts 5400-5499)",
    "57": "USADF, African Development Foundation (Parts 5700-5799)",
    "61": "CBCA, Civilian Board of Contract Appeals (Parts 6100-6199)",
    "99": "CAS (Part 9900)",
}

# Common FAR sections for quick reference in tool descriptions
COMMON_FAR_SECTIONS: dict[str, str] = {
    "2.101": "Definitions",
    "4.1102": "SAM policy",
    "6.302-1": "Only one responsible source",
    "9.104-1": "General standards of responsibility",
    "9.406-2": "Causes for debarment",
    "12.301": "Solicitation provisions (commercial)",
    "13.003": "Simplified acquisition policy",
    "15.305": "Proposal evaluation",
    "15.306": "Exchanges with offerors",
    "19.502-2": "Total small business set-asides",
    "31.205": "Selected costs (allowability)",
    "33.103": "Protests to the agency",
    "42.302": "Contract administration functions",
    "52.212-1": "Instructions to Offerors (Commercial)",
    "52.212-4": "Contract Terms and Conditions (Commercial)",
    "52.212-5": "Required Contract Terms (Commercial)",
}
