# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants and reference data for the USASpending API."""

from . import __version__

BASE_URL = "https://api.usaspending.gov"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = f"usaspending-gov-mcp/{__version__}"

# Award type code groups. These MUST NOT be mixed in a single request
# (the API returns HTTP 422 otherwise).
# The F-codes are the newer FABS award types returned by
# /api/v2/references/award_types/ (verified live 2026-08-16). Real awards
# carry them (e.g. multi-billion Amtrak F001 grants), so omitting them
# silently excludes those records from group searches.
AWARD_TYPE_GROUPS: dict[str, list[str]] = {
    "contracts": ["A", "B", "C", "D"],
    "idvs": [
        "IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B",
        "IDV_B_C", "IDV_C", "IDV_D", "IDV_E",
    ],
    "grants": ["02", "03", "04", "05", "F001", "F002"],
    "loans": ["07", "08", "F003", "F004"],
    "direct_payments": ["06", "10", "F006", "F007"],
    "other": ["09", "11", "-1", "F005", "F008", "F009", "F010"],
}

# Default field sets for different award types
DEFAULT_CONTRACT_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Award Amount",
    "Total Outlays",
    "Contract Award Type",
    "Start Date",
    "End Date",
    "NAICS",
    "PSC",
    "generated_internal_id",
    "Last Modified Date",
]

DEFAULT_IDV_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Award Amount",
    "Start Date",
    "Last Date to Order",
    "NAICS",
    "PSC",
    "generated_internal_id",
    "Last Modified Date",
]

DEFAULT_LOAN_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Loan Value",
    "Subsidy Cost",
    "Awarding Agency",
    "Awarding Sub Agency",
    "generated_internal_id",
    "Last Modified Date",
]

# Assistance awards use "Award Type" (not "Contract Award Type") and carry
# CFDA assistance listings. Verified against live grants results 2026-08-16.
DEFAULT_GRANT_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Award Amount",
    "Total Outlays",
    "Award Type",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Start Date",
    "End Date",
    "CFDA Number",
    "generated_internal_id",
    "Last Modified Date",
]

# direct_payments / other: same assistance field set without the
# grant-centric CFDA Number column.
DEFAULT_ASSISTANCE_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Award Amount",
    "Total Outlays",
    "Award Type",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Start Date",
    "End Date",
    "generated_internal_id",
    "Last Modified Date",
]
