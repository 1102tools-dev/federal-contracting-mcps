# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants for the GSA CALC+ MCP server."""

BASE_URL = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "gsa-calc-mcp/1.0.1"

MAX_PAGE_SIZE = 500
RATE_LIMIT_PER_HOUR = 1000

EDUCATION_LEVELS = {
    "AA": "Associate's",
    "BA": "Bachelor's",
    "HS": "High School",
    "MA": "Master's",
    "PHD": "Doctorate",
    "TEC": "Technical/Vocational",
}

BUSINESS_SIZES = {
    "S": "Small Business",
    "O": "Other (Large Business)",
}

ORDERING_FIELDS = [
    "current_price",
    "labor_category",
    "vendor_name",
    "education_level",
    "min_years_experience",
    "next_year_price",
    "idv_piid",
    "business_size",
]

# Worksite filtering was removed in 1.0.1: the CALC+ v3 API silently ignores
# the worksite filter (live-verified, every value returns unfiltered totals),
# and the v3 data vocabulary is Customer_Facility / Contractor_Facility /
# Virtual, not the old Customer / Contractor / Both enum this server used to
# validate against. _validate_worksite now raises on any value.

# Live-verified in the 1.0.1 audit: every SIN below returns records on the
# CALC+ v3 API. 541512, 541513, 541610, and 541519 were removed; they return
# 0 records (retired or absorbed under MAS consolidation, for example the old
# 541512/541513 work now falls under 54151S).
COMMON_SINS: dict[str, str] = {
    "54151S": "IT Professional Services",
    "541611": "Management and Financial Consulting",
    "541715": "Engineering Research and Development",
    "541330ENG": "Engineering Services",
    "541690": "Other Scientific and Technical Consulting",
    "561210FAC": "Facilities Maintenance and Management",
    "541511": "Custom Computer Programming",
    "611430": "Training",
}
