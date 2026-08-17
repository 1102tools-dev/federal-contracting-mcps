# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants for the BLS OEWS MCP server."""

BASE_URL_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BASE_URL_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "bls-oews-mcp/1.0.1"

# OEWS publishes about a year in arrears. Do NOT use the calendar year.
# May 2025 estimates released April 2026. Next: May 2026 estimates in ~April 2027.
# BLS withdraws the prior year once superseded: 2024 stopped returning rows
# when 2025 published, so this constant must be bumped each release cycle or
# every defaulted query comes back empty. Verify with detect_latest_year().
OEWS_CURRENT_YEAR = "2025"

# Series ID format: PREFIX(4) + AREA(7) + INDUSTRY(6) + OCC(6) + DATATYPE(2) = 25 chars
SERIES_ID_LENGTH = 25

# Max series per request
MAX_SERIES_V1 = 25
MAX_SERIES_V2 = 50

SPECIAL_VALUES = {"-", "#", "*", "N/A"}

# Official OEWS datatype map, live-verified 2026-08 against national
# all-occupations data by cross-footing hourly x 2080 against the annual
# percentiles (06=$15.00 x 2080 = $31,200 = dt11 annual 10th, 08=$24.51
# x 2080 = $50,980 = dt13 annual median, and so on). Datatypes 16/17 only
# exist at state/metro scope and are ratios, not dollars.
DATATYPE_LABELS: dict[str, str] = {
    "01": "Employment",
    "03": "Hourly Mean Wage",
    "04": "Annual Mean Wage",
    "06": "Hourly 10th Percentile",
    "07": "Hourly 25th Percentile",
    "08": "Hourly Median",
    "09": "Hourly 75th Percentile",
    "10": "Hourly 90th Percentile",
    "11": "Annual 10th Percentile",
    "12": "Annual 25th Percentile",
    "13": "Annual Median",
    "14": "Annual 75th Percentile",
    "15": "Annual 90th Percentile",
    "16": "Employment per 1,000 Jobs",
    "17": "Location Quotient",
}

# The set of datatypes we route as HOURLY values in _parse_value
HOURLY_DATATYPES: set[str] = {"03", "06", "07", "08", "09", "10"}
# Datatypes returning COUNTS (not dollars)
COUNT_DATATYPES: set[str] = {"01"}
# Datatypes returning RATIOS (not dollars): state/metro only
RATIO_DATATYPES: set[str] = {"16", "17"}

# Datatypes used for IGCE wage profiles. "03" rides along so annual-only
# occupations (pilots, teachers) can be detected: BLS suppresses their
# hourly mean while publishing annual figures.
IGCE_DATATYPES = ["04", "11", "13", "15"]

# Common SOC codes for federal IT/professional services
COMMON_SOC_CODES: dict[str, str] = {
    "111021": "General and Operations Managers",
    "113021": "Computer and Information Systems Managers",
    "131082": "Project Management Specialists",
    "131111": "Management Analysts",
    "132011": "Accountants and Auditors",
    "151211": "Computer Systems Analysts",
    "151212": "Information Security Analysts",
    "151232": "Computer User Support Specialists (Help Desk)",
    "151241": "Computer Network Architects",
    "151242": "Database Administrators",
    "151244": "Network and Computer Systems Administrators",
    "151251": "Computer Programmers",
    "151252": "Software Developers",
    "151253": "Software Quality Assurance Analysts",
    "151254": "Web Developers",
    "152051": "Data Scientists",
    "273042": "Technical Writers",
    "436014": "Secretaries and Administrative Assistants",
}

# Common metro MSA codes
COMMON_METROS: dict[str, str] = {
    "0047900": "Washington DC",
    "0042660": "Seattle",
    "0012580": "Baltimore",
    "0037980": "Philadelphia",
    "0035620": "New York City",
    "0031080": "Los Angeles",
    "0041860": "San Francisco",
    "0038060": "Phoenix",
    "0016980": "Chicago",
    "0012420": "Austin",
    "0014460": "Boston",
    "0019100": "Dallas",
    "0026420": "Houston",
    "0041740": "San Diego",
    "0019820": "Detroit",
}

# Every state/territory FIPS code OEWS publishes (50 states, DC, GU, PR, VI).
# Used to validate scope='state' area codes so a bogus FIPS fails fast
# instead of burning a query on a series that cannot exist.
STATE_FIPS: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "66": "GU", "72": "PR", "78": "VI",
}
