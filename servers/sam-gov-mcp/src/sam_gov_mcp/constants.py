# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants and reference tables for the SAM.gov MCP server."""

BASE_URL = "https://api.sam.gov"
ENTITY_PATH = "/entity-information/v3/entities"
EXCLUSIONS_PATH = "/entity-information/v4/exclusions"
OPPORTUNITIES_PATH = "/opportunities/v2/search"
OPPORTUNITY_DESC_PATH = "/prod/opportunities/v1/noticedesc"
PSC_PATH = "/prod/locationservices/v1/api/publicpscdetails"
CONTRACT_AWARDS_PATH = "/contract-awards/v1/search"
FH_ORGS_PATH = "/prod/federalorganizations/v1/orgs"
FH_HIERARCHY_PATH = "/prod/federalorganizations/v1/org/hierarchy"
SUBCONTRACTS_PATH = "/prod/contract/v1/subcontracts/search"
ASSISTANCE_SUBAWARDS_PATH = "/prod/assistance/v1/subawards/search"

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "sam-gov-mcp/1.0.1"

# Hard caps from the SAM.gov API (enforce client-side to give good errors)
ENTITY_MAX_SIZE = 10          # Entity Management has a hard cap of 10
OPPORTUNITY_MAX_LIMIT = 1000  # Opportunities accepts large limits
EXCLUSION_MAX_SIZE = 100      # Exclusions typical cap
CONTRACT_AWARDS_MAX_LIMIT = 100  # Contract Awards hard cap
FH_MAX_LIMIT = 100            # Federal Hierarchy /orgs cap
SUBAWARD_MAX_PAGE_SIZE = 1000 # Subaward APIs allow up to 1000/page

# Notice type codes (ptype parameter on Opportunities)
NOTICE_TYPES: dict[str, str] = {
    "p": "Presolicitation",
    "o": "Solicitation",
    "k": "Combined Synopsis/Solicitation",
    "r": "Sources Sought",
    "g": "Sale of Surplus Property",
    "s": "Special Notice",
    "i": "Intent to Bundle",
    "a": "Award Notice",
    "u": "Justification (J&A)",
}

# Set-aside type codes for Opportunities
SET_ASIDE_CODES: dict[str, str] = {
    "SBA": "Total Small Business Set-Aside",
    "SBP": "Partial Small Business Set-Aside",
    "8A": "8(a) Competed",
    "8AN": "8(a) Sole Source",
    "HZC": "HUBZone Set-Aside",
    "HZS": "HUBZone Sole Source",
    "SDVOSBC": "SDVOSB Set-Aside",
    "SDVOSBS": "SDVOSB Sole Source",
    "WOSB": "WOSB Set-Aside",
    "WOSBSS": "WOSB Sole Source",
    "EDWOSB": "EDWOSB Set-Aside",
    "EDWOSBSS": "EDWOSB Sole Source",
    "VSA": "Veteran Set-Aside",
    "VSS": "Veteran Sole Source",
}

# Business type codes (validated against live SAM.gov API)
BUSINESS_TYPE_CODES: dict[str, str] = {
    "23": "Minority-Owned Business",
    "27": "Self Certified Small Disadvantaged Business",
    "2X": "For Profit Organization",
    "8W": "Women-Owned Small Business",
    "A2": "Women-Owned Business",
    "A5": "Veteran-Owned Business",
    "A8": "Non-Profit Organization",
    "LJ": "Limited Liability Company",
    "MF": "Manufacturer of Goods",
    "OY": "Black American Owned",
    "PI": "Hispanic American Owned",
    "QF": "Service-Disabled Veteran-Owned Business",
    "XS": "Subchapter S Corporation",
}

# SBA-determined certification types. Assigned by SBA, never self-selected,
# and filtered through the dedicated sbaBusinessTypeCode query parameter, not
# businessTypeCode. The codes are counterintuitive: XX is HUBZone and A6 is
# 8(a). Releases before 1.0.1 had XX mislabeled as "8(a) Certified".
# A6/JT/XX/A4 are from the SAM Functional Data Dictionary ("Business Types"
# field); A9/A0 postdate it and were pinned from live entity data, where both
# filter correctly and appear in sbaBusinessTypeList with these descriptions
# (verified 2026-08-16).
SBA_BUSINESS_TYPE_CODES: dict[str, str] = {
    "A6": "SBA Certified 8(a) Program Participant",
    "JT": "SBA Certified 8(a) Joint Venture",
    "XX": "SBA Certified HUBZone Firm",
    "A4": "SBA Certified Small Disadvantaged Business",
    "A9": "SBA-Certified Women-Owned Small Business",
    "A0": "SBA-Certified Economically Disadvantaged Women-Owned Small Business",
}

# Valid includeSections values for Entity Management
ENTITY_SECTIONS = {
    "entityRegistration",
    "coreData",
    "assertions",
    "pointsOfContact",
    "repsAndCerts",
    "integrityInformation",
    "All",
}

# Exclusion classification types
EXCLUSION_CLASSIFICATIONS = [
    "Firm",
    "Individual",
    "Vessel",
    "Special Entity Designation",
]

# Registration status codes
REGISTRATION_STATUS = {
    "A": "Active",
    "E": "Expired",
    "D": "Deleted",
    "I": "Inactive",
}
