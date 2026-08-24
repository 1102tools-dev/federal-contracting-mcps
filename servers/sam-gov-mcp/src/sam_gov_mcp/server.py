# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""SAM.gov MCP server.

Provides access to SAM.gov entity registration, exclusion/debarment records,
contract opportunity data, and contract award data (FPDS replacement).
Authentication via environment variable SAM_API_KEY.

The server wraps four SAM.gov REST APIs:
- Entity Management v3 (/entity-information/v3/entities)
- Exclusions v4 (/entity-information/v4/exclusions)
- Get Opportunities v2 (/opportunities/v2/search)
- Contract Awards v1 (/contract-awards/v1/search)
- Product/Service Code lookup (/prod/locationservices/v1/api/publicpscdetails)

All tools are read-only. API keys expire every 90 days; on 401/403 errors
the server returns an actionable regeneration message.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from datetime import date
from typing import Any, Literal, Union

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from ._pacing import FederalApiPacer
from .constants import (
    ASSISTANCE_SUBAWARDS_PATH,
    BASE_URL,
    CONTRACT_AWARDS_MAX_LIMIT,
    CONTRACT_AWARDS_PATH,
    DEFAULT_TIMEOUT,
    ENTITY_MAX_SIZE,
    ENTITY_PATH,
    EXCLUSION_MAX_SIZE,
    EXCLUSIONS_PATH,
    FH_HIERARCHY_PATH,
    FH_MAX_LIMIT,
    FH_ORGS_PATH,
    OPPORTUNITIES_PATH,
    OPPORTUNITY_DESC_PATH,
    OPPORTUNITY_MAX_LIMIT,
    PSC_PATH,
    SUBAWARD_MAX_PAGE_SIZE,
    SUBCONTRACTS_PATH,
    USER_AGENT,
)

mcp = MCPServer(
    "sam-gov",
    version=__version__,
    instructions=(
        "Before the first SAM.gov data call in a session, call get_access_status. "
        "If it reports missing_required, tell the user SAM_API_KEY is not configured "
        "and do not call or retry SAM.gov data tools until setup is corrected."
    ),
)


# ---------------------------------------------------------------------------
# Validators and normalizers
# ---------------------------------------------------------------------------

_MMDDYYYY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_MMDDYYYY_RANGE_RE = re.compile(r"^\[\d{2}/\d{2}/\d{4},\d{2}/\d{2}/\d{4}\]$")
_YYYY_MM_DD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UEI_RE = re.compile(r"^[A-Z0-9]{12}$")
_CAGE_RE = re.compile(r"^[A-Z0-9]{5}$")


def _coerce_str(value: Any, *, field: str) -> str | None:
    """Accept int/str/None for fields that are conceptually numeric codes.

    SAM.gov APIs want string codes but users often pass ints (naics_code=541512).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a string or integer, not bool.")
    if isinstance(value, (int, str)):
        s = str(value).strip()
        return s if s else None
    raise ValueError(
        f"{field} must be a string or integer. Got {type(value).__name__}: {value!r}."
    )


def _validate_date_mmddyyyy(
    value: str | None, *, field: str, allow_range: bool = True
) -> str | None:
    """SAM.gov uses MM/DD/YYYY. Bracketed ranges [MM/DD/YYYY,MM/DD/YYYY] are
    allowed only where the endpoint supports them (allow_range=True). The
    Opportunities date params take single dates; before 1.0.2 a bracketed
    range passed validation there and then crashed the range-math with
    'too many values to unpack'."""
    if value is None:
        return None
    if _MMDDYYYY_RANGE_RE.match(value):
        if not allow_range:
            raise ValueError(
                f"{field} takes a single MM/DD/YYYY date, not a bracketed "
                f"range. Got {value!r}. Use the matching _from/_to parameter "
                f"pair to express a range."
            )
        parts = value.strip("[]").split(",")
        for p in parts:
            _validate_date_mmddyyyy(p, field=f"{field} (range part)")
        return value
    if not _MMDDYYYY_RE.match(value):
        range_hint = " or bracketed range [MM/DD/YYYY,MM/DD/YYYY]" if allow_range else ""
        raise ValueError(
            f"{field} must be MM/DD/YYYY (e.g. '01/15/2026'){range_hint}. "
            f"Got {value!r}. ISO 8601 and YYYY-MM-DD are rejected."
        )
    try:
        mm, dd, yyyy = value.split("/")
        date(int(yyyy), int(mm), int(dd))
    except ValueError as exc:
        raise ValueError(f"{field}={value!r} is not a valid calendar date: {exc}") from exc
    return value


def _validate_date_yyyy_mm_dd(value: str | None, *, field: str) -> str | None:
    """Subaward APIs use ISO yyyy-MM-dd, unlike the rest of SAM.gov (MM/dd/yyyy)."""
    if value is None:
        return None
    if not _YYYY_MM_DD_RE.match(value):
        raise ValueError(
            f"{field} must be yyyy-MM-dd (e.g. '2026-01-15'). Got {value!r}. "
            f"Note: Subaward APIs use ISO format, unlike Contract Awards/Opportunities "
            f"which use MM/DD/YYYY."
        )
    try:
        yyyy, mm, dd = value.split("-")
        date(int(yyyy), int(mm), int(dd))
    except ValueError as exc:
        raise ValueError(f"{field}={value!r} is not a valid calendar date: {exc}") from exc
    return value


def _validate_uei(uei: str, *, field: str = "uei") -> str:
    if not uei or not uei.strip():
        raise ValueError(f"{field} cannot be empty.")
    stripped = uei.strip().upper()
    if not _UEI_RE.match(stripped):
        raise ValueError(
            f"{field} must be 12 uppercase alphanumeric characters. Got {uei!r}."
        )
    return stripped


def _validate_cage(cage: str, *, field: str = "cage_code") -> str:
    if not cage or not cage.strip():
        raise ValueError(f"{field} cannot be empty.")
    stripped = cage.strip().upper()
    if not _CAGE_RE.match(stripped):
        raise ValueError(
            f"{field} must be 5 uppercase alphanumeric characters. Got {cage!r}."
        )
    return stripped


def _current_fiscal_year() -> int:
    """Federal FY (Oct-Sep). FY2026 runs 2025-10-01 through 2026-09-30."""
    today = date.today()
    return today.year + 1 if today.month >= 10 else today.year


def _validate_fiscal_year(value: Any, *, field: str = "fiscal_year") -> str | None:
    if value is None:
        return None
    # Accept int or str that parses as int
    try:
        fy = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field} must be a year like 2026 (int or str). Got {value!r}."
        ) from exc
    current = _current_fiscal_year()
    # Live-verified 2026-08: data exists back to FY1970 (FY1980 alone has 634k
    # records); the old 2008 floor silently walled off four decades. Two-digit
    # years (e.g. 24) are accepted by the API but return an empty shape, so
    # require a real 4-digit year.
    if fy < 1970 or fy > current:
        raise ValueError(
            f"{field}={fy} is out of range. Use a 4-digit year; SAM.gov Contract "
            f"Awards data has been observed from FY1970 through FY{current} "
            f"(current fiscal year). Earlier years return empty results."
        )
    return str(fy)


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(
            f"{field} exceeds maximum of {hi}. Got {value}. Paginate instead."
        )
    return value


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _redact_sensitive_text(text: str, api_key: str | None = None) -> str:
    """Remove raw and URL-encoded credential values from untrusted text."""
    result = text
    if api_key:
        variants = {
            api_key,
            urllib.parse.quote(api_key, safe=""),
            urllib.parse.quote_plus(api_key),
        }
        for value in sorted(variants, key=len, reverse=True):
            result = result.replace(value, "[REDACTED]")
    return result


def _redact_sensitive_payload(value: Any, api_key: str | None = None) -> Any:
    if isinstance(value, str):
        return _redact_sensitive_text(value, api_key)
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_payload(item, api_key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_payload(item, api_key) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_payload(item, api_key) for item in value)
    return value


def _clean_error_body(text: str, api_key: str | None = None) -> str:
    """Redact credentials and compact upstream error bodies for safe display."""
    text = _redact_sensitive_text(text, api_key)
    if not _HTML_ERROR_RE.search(text):
        return text[:500]
    pieces: list[str] = []
    title = _TITLE_RE.search(text)
    if title:
        pieces.append(title.group(1).strip())
    h1 = _H1_RE.search(text)
    if h1 and (not title or h1.group(1).strip() != title.group(1).strip()):
        pieces.append(h1.group(1).strip())
    return " - ".join(pieces) if pieces else "upstream returned HTML error page"


_SAFE_INT_ERROR_VALUES = (None, "", "null", "None")


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce value to int, handling None/empty/'null' that SAM.gov sometimes returns.

    Round 7 fix: also catches OverflowError from inf/nan
    floats. Without it, _safe_int(float('inf')) crashed instead of returning
    the default.
    """
    if value in _SAFE_INT_ERROR_VALUES:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_list(value: Any) -> list[Any]:
    """Normalize XML-to-JSON single-item collapse. SAM.gov sometimes returns a lone
    dict where a list of length 1 was expected (Entity entityData, Exclusion
    excludedEntity, etc.). Returns a list regardless of input shape."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]  # best-effort


# Input sanity patterns. The original 0.3.0 release had a WAF filter that
# rejected single quotes, angle brackets, SQL keywords, and backticks, on the
# assumption that SAM.gov's WAF dropped connections on these. Round-1 live
# audit (v0.3.1) confirmed this was wrong: SAM.gov accepts all of those as
# literal search text. The filter blocked legitimate company names like
# McDonald's, L'Oreal, O'Reilly, etc. Now we only reject things that actually
# break URL construction or the API:
_REJECT_PATTERNS = [
    (re.compile(r"\x00"), "null byte"),
    (re.compile(r"[\r\n\t]"), "control character (tab / CR / LF)"),
]


def _validate_waf_safe(value: str | None, *, field: str) -> str | None:
    """Reject strings that contain control characters that break URL encoding.

    Historical name kept for backward compatibility; SAM.gov does not in
    practice have a WAF that blocks the patterns the original filter tried
    to guard against. See the _REJECT_PATTERNS comment above.
    """
    if value is None:
        return None
    for pattern, description in _REJECT_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"{field}={value!r} contains {description}. "
                f"Remove the offending character and retry."
            )
    return value


def _clamp_str_len(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if len(value) > maximum:
        raise ValueError(
            f"{field} exceeds maximum length of {maximum} chars. "
            f"Got {len(value)}. Long strings trigger HTTP 414 on SAM.gov."
        )
    return value


def _validate_code_in_dict(
    value: str | None,
    *,
    field: str,
    valid_codes: dict[str, str],
    upcase: bool = True,
) -> str | None:
    """Validate a code against a known-codes dict. Normalizes case if upcase=True."""
    if value is None:
        return None
    normalized = value.strip().upper() if upcase else value.strip()
    if not normalized:
        return None
    if normalized not in valid_codes:
        sample = ", ".join(list(valid_codes.keys())[:8])
        raise ValueError(
            f"{field}={value!r} is not a valid code. "
            f"Valid codes include: {sample} (total {len(valid_codes)}). "
            f"See SAM.gov documentation for the full list."
        )
    return normalized


_NAICS_RE = re.compile(r"^\d{2,6}$")


def _validate_naics(value: Any, *, field: str = "naics_code", allow_operators: bool = False) -> str | None:
    """Validate NAICS. 2-6 digit numeric string.

    Contract Awards allows ~ (OR) and ! (NOT) operators; set allow_operators=True there.
    """
    if value is None:
        return None
    s = _coerce_str(value, field=field)
    if s is None:
        return None
    # Allow SAM.gov boolean operators on Contract Awards
    if allow_operators:
        parts = re.split(r"[~!]", s)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if not _NAICS_RE.match(p):
                raise ValueError(
                    f"{field}={value!r}: NAICS code {p!r} must be 2-6 digits. "
                    f"Use ~ for OR, ! for NOT (e.g. '541511~541512', '!541511')."
                )
        return s
    if not _NAICS_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be a 2-6 digit NAICS code (no operators)."
        )
    return s


def _validate_bracket_range(
    value: str | None,
    *,
    field: str,
    inner_validator: Any = None,
) -> str | None:
    """Validate [min,max] bracket range format used for dollars_obligated etc."""
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if not (s.startswith("[") and s.endswith("]") and "," in s):
        raise ValueError(
            f"{field}={value!r} must use bracket format '[min,max]' (e.g. '[1000,50000]')."
        )
    return s


# ---------------------------------------------------------------------------
# Auth and HTTP client
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Fetch the SAM.gov API key from the environment on every call.

    Reading per-call (rather than at import time) lets users update the env
    without restarting the server and keeps the key out of module state.
    """
    key = os.environ.get("SAM_API_KEY", "").strip()
    if not key:
        raise ToolError(
            "Missing required credential: SAM_API_KEY is not configured. "
            "SAM.gov entity, exclusion, opportunity, award, hierarchy, and "
            "subaward tools will not work until it is configured. Get a free "
            "personal API key by signing in and following the Public API Key "
            "instructions at https://sam.gov/help. Configure it in the launching "
            "environment or your client's MCP credential configuration, restart the client, and run "
            "get_access_status again. Do not paste the key into chat."
        )
    if not key.startswith("SAM-"):
        raise ToolError(
            "Configured credential rejected before use: SAM_API_KEY has an unexpected format "
            "(expected SAM-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx). "
            "Verify or regenerate the personal Public API Key using "
            "https://sam.gov/help, update the launching environment, restart the "
            "client, and run get_access_status again. Do not paste the key into chat."
        )
    return key


@mcp.tool(
    annotations={
        "title": "Check SAM.gov Data Access",
        "readOnlyHint": True,
        "destructiveHint": False,
    }
)
def get_access_status() -> dict[str, Any]:
    """Check SAM.gov credential presence without returning or validating its value."""
    if not os.environ.get("SAM_API_KEY", "").strip():
        status = "missing_required"
    else:
        status = "configured_unverified"
    return {
        "service": "sam.gov",
        "status": status,
        "credential_env": "SAM_API_KEY",
        "required_for": [
            "SAM.gov entity, exclusion, opportunity, award, hierarchy, and subaward operations"
        ],
        "fallback": None,
        "setup_url": "https://sam.gov/help",
        "validation": "presence_only",
        "restart_required": True,
    }


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=DEFAULT_TIMEOUT,
            # CRITICAL: do not set Accept: application/json; the Exclusions
            # endpoint returns 406 Not Acceptable when that header is present.
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _pacer(api_key: str) -> FederalApiPacer:
    return FederalApiPacer(
        bucket="api.sam.gov",
        default_interval=3.0,
        credential=api_key,
    )


def _format_error(
    status: int, body: str, api_key: str | None = None
) -> str:
    """Translate common SAM.gov errors into actionable messages."""
    cleaned = _clean_error_body(body, api_key)
    # 401/403: key expired or invalid. Response is often HTML, not JSON.
    if status in (401, 403):
        return (
            f"Configured credential rejected: SAM.gov returned HTTP {status}. "
            "SAM.gov keys expire every 90 days. "
            "Use https://sam.gov/help to verify or regenerate the personal Public "
            "API Key. Then update SAM_API_KEY in the launching environment, restart "
            "the client, and run get_access_status again. Do not paste the key into chat."
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. "
            "The SAM.gov Exclusions endpoint rejects requests that include "
            "an Accept: application/json header. This server does not set "
            "that header by default; if you see this error, check that no "
            "proxy is injecting one."
        )
    if status == 429:
        return (
            "HTTP 429: SAM.gov rate limited the request. Published daily "
            "allowances vary by account, while burst and abuse controls are "
            "not numerically documented. Do not retry automatically. Check "
            "the key's rate plan and any provider-supplied retry guidance."
        )
    if status == 400:
        # Surface specific 400 patterns
        lower = cleaned.lower()
        if "size cannot exceed 10" in lower:
            return (
                "HTTP 400: Entity Management has a hard cap of size=10 per request. "
                "To retrieve more records, paginate with the 'page' parameter. "
                "This cap does NOT apply to Opportunities (which accepts limit=1000+)."
            )
        if "invalid_search_parameter" in lower or "invalid search" in lower:
            return (
                f"HTTP 400: Invalid search parameter. "
                f"Exclusions uses 'size' not 'limit'. "
                f"Opportunities requires postedFrom and postedTo (MM/DD/YYYY). "
                f"Dates must be MM/DD/YYYY, not ISO 8601. "
                f"API response: {cleaned}"
            )
        if "date" in lower and ("range" in lower or "format" in lower):
            return (
                f"HTTP 400: Date parameter error. "
                f"SAM.gov uses MM/DD/YYYY format (not ISO 8601). "
                f"Opportunity postedFrom/postedTo range max is 364 days. "
                f"API response: {cleaned}"
            )
        return f"HTTP 400: {cleaned}"
    if status == 414:
        return (
            "HTTP 414: URI Too Long. The query string exceeds SAM.gov's URL "
            "length limit. Shorten your search parameters (entity names, "
            "free text) and try again."
        )
    if status == 404:
        # PSC endpoint returns the unhelpful "Entered search criteria is not
        # found" on a valid-format code that just doesn't exist in SAM's
        # database. Translate.
        if "entered search criteria is not found" in cleaned.lower():
            return (
                "HTTP 404: SAM.gov did not find any record matching your search. "
                "For PSC codes: this endpoint defaults to active_only='Y', so a "
                "retired code returns 404 even though it is a real PSC. If the "
                "code is well-formed (4 characters, like 'R425'), retry with "
                "active_only='ALL' to see retired entries and their end dates "
                "(D302, for example, is real but was retired 2020-10-29). "
                "Otherwise verify the code at "
                "https://www.acquisition.gov/psc-manual. "
                "For free-text PSC searches: SAM's PSC endpoint requires a "
                "substring that appears in an active PSC name or description."
            )
        return f"HTTP 404: {cleaned}"
    return f"HTTP {status}: {cleaned}"


async def _get(
    path: str,
    params: dict[str, Any],
    *,
    base_url: str = BASE_URL,
) -> dict[str, Any]:
    """GET helper. Handles SAM.gov auth, error translation, and HTML 401 bodies."""
    api_key = _get_api_key()
    query = dict(params)
    query["api_key"] = api_key

    # Build URL manually so we can preserve brackets/tildes used for OR/NOT
    # in SAM.gov multi-value params.
    query_str = urllib.parse.urlencode(query, safe="[],~/!*")
    full_url = f"{base_url}{path}?{query_str}"

    try:
        async with _pacer(api_key).request_slot() as pacing:
            r = await _get_client().get(full_url)
            pacing.observe_response(r)
            pacing.raise_if_rate_limited(
                r,
                service="SAM.gov",
                guidance=_format_error(r.status_code, r.text, api_key),
            )
        r.raise_for_status()
        # Most endpoints return JSON; opportunity description endpoint returns
        # a JSON object with a "description" HTML field.
        content_type = r.headers.get("content-type", "")
        if "json" in content_type:
            data = _redact_sensitive_payload(r.json(), api_key)
            # Contract Awards can 200 with a BARE JSON STRING error message
            # (e.g. '"Max value allowed for parameter \"limit\" is 100"').
            # Surfacing it as an error beats normalizing it into a silent
            # zero-result response.
            if not isinstance(data, dict):
                raise ToolError(
                    f"SAM.gov returned a non-object JSON response: {str(data)[:500]}"
                )
            return data
        # Contract Awards returns plain text for certain errors even on 200
        # (e.g. "Max value allowed for parameter \"limit\" is 100").
        # Also returns HTML for auth errors (e.g. <h1>API_KEY_INVALID</h1>).
        body = _redact_sensitive_text(r.text.strip(), api_key)
        if body and not body.startswith("{"):
            raise ToolError(f"SAM.gov returned non-JSON response: {body[:500]}")
        # Sometimes SAM.gov returns text/html for errors even on 200
        return {"raw_response": _redact_sensitive_text(r.text, api_key)}
    except httpx.HTTPStatusError as e:
        raise ToolError(
            _format_error(e.response.status_code, e.response.text, api_key)
        ) from e
    except httpx.RequestError as e:
        safe_error = _redact_sensitive_text(str(e), api_key)
        err_str = safe_error.lower()
        # SAM's WAF drops the connection silently for bad chars; sometimes httpx
        # surfaces this as an empty error string, other times as reset/closed/eof.
        waf_signals = ["reset", "closed", "connection", "timeout", "eof"]
        if not err_str or any(x in err_str for x in waf_signals):
            raise ToolError(
                f"SAM.gov dropped the connection. This often happens when the "
                f"request URL contains characters that trigger their web application "
                f"firewall (single quotes, angle brackets, SQL keywords, path "
                f"traversal sequences like '../'). Remove special characters "
                f"from your search parameters and try again. "
                f"Original error: {safe_error or type(e).__name__}"
            ) from e
        raise ToolError(f"Network error calling SAM.gov: {safe_error}") from e
    except RuntimeError as e:
        # FederalApiPacer uses RuntimeError for anticipated local pacing failures.
        raise ToolError(_redact_sensitive_text(str(e), api_key)) from e


# ---------------------------------------------------------------------------
# Entity Management tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Lookup Entity by UEI", "readOnlyHint": True, "destructiveHint": False})
async def lookup_entity_by_uei(
    uei: str,
    include_sections: list[
        Literal[
            "entityRegistration",
            "coreData",
            "assertions",
            "pointsOfContact",
            "repsAndCerts",
            "integrityInformation",
            "All",
        ]
    ] | None = None,
    sam_registered: Literal["Yes", "No"] = "Yes",
) -> dict[str, Any]:
    """Look up a federal entity by its Unique Entity ID (UEI).

    Returns the full entity record from SAM.gov Entity Management v3.
    The UEI is a 12-character alphanumeric identifier assigned by SAM.gov.
    Matching is case-insensitive and whitespace-tolerant (live-verified).

    A UEI is NOT guaranteed unique: live data contains UEIs with multiple
    (sometimes duplicate) registration records, so totalRecords can exceed 1;
    inspect every entityData entry rather than assuming [0] is the only one.
    sam_registered='No' searches a separate ~614k-record population of
    "ID Assigned" entities (UEI issued, registration never completed).

    include_sections controls response size:
    - entityRegistration: UEI, CAGE, name, status, activation/expiration dates (ALWAYS include)
    - coreData: addresses, POCs at high level, business types, hierarchy
    - assertions: NAICS and PSC codes (in goodsAndServices subsection)
    - pointsOfContact: detailed POC records (name, title, address; email/phone FOUO only)
    - repsAndCerts: FAR/DFARS certification responses (must be explicitly requested)
    - integrityInformation: FAPIIS proceedings data (must be explicitly requested)
    - All: entityRegistration + coreData + assertions + pointsOfContact (but NOT repsAndCerts/integrityInformation)

    Default: entityRegistration + coreData. Always include entityRegistration
    alongside any other section or the response loses entity identification.

    sam_registered='Yes' (default) returns only fully registered entities.
    Use 'No' to find entities with a UEI assigned but incomplete registration.
    """
    if not uei or not uei.strip():
        return {"totalRecords": 0, "entityData": [], "_note": "Empty UEI provided."}

    uei = _validate_uei(uei)

    if include_sections is None:
        include_sections = ["entityRegistration", "coreData"]
    elif "entityRegistration" not in include_sections and "All" not in include_sections:
        include_sections = ["entityRegistration"] + list(include_sections)

    params = {
        "ueiSAM": uei,
        "samRegistered": sam_registered,
        "includeSections": ",".join(include_sections),
    }
    return await _get(ENTITY_PATH, params)


@mcp.tool(annotations={"title": "Lookup Entity by CAGE", "readOnlyHint": True, "destructiveHint": False})
async def lookup_entity_by_cage(
    cage_code: str,
    include_sections: list[str] | None = None,
) -> dict[str, Any]:
    """Look up a federal entity by its CAGE code.

    CAGE (Commercial and Government Entity) codes are 5-character alphanumeric
    identifiers assigned by DLA. Useful when you have a CAGE but no UEI.
    """
    if not cage_code or not cage_code.strip():
        return {"totalRecords": 0, "entityData": [], "_note": "Empty CAGE code provided."}

    cage_code = _validate_cage(cage_code)

    if include_sections is None:
        include_sections = ["entityRegistration", "coreData"]
    params = {
        "cageCode": cage_code,
        "samRegistered": "Yes",
        "includeSections": ",".join(include_sections),
    }
    return await _get(ENTITY_PATH, params)


@mcp.tool(annotations={"title": "Search Entities", "readOnlyHint": True, "destructiveHint": False})
async def search_entities(
    legal_business_name: str | None = None,
    primary_naics: Union[str, int, None] = None,
    any_naics: Union[str, int, None] = None,
    psc_code: str | None = None,
    business_type_code: str | None = None,
    sba_business_type_code: str | None = None,
    state_code: str | None = None,
    registration_status: Literal["A", "E"] = "A",
    purpose_of_registration: Literal["Z1", "Z2", "Z3", "Z4", "Z5"] | None = None,
    free_text: str | None = None,
    include_sections: list[str] | None = None,
    page: int = 0,
    size: int = 10,
) -> dict[str, Any]:
    """Search SAM.gov entities with flexible filters.

    All filters are AND-ed together. Returns paginated results; note that
    Entity Management has a HARD CAP of 10 records per page (size <= 10).
    For more results, increment 'page' and make multiple calls.

    Key filter notes:
    - legal_business_name does partial matching with no relevance ranking.
      Cannot contain & or parentheses (API strips them, returns 0 results).
      For exact lookup use UEI or CAGE.
    - primary_naics matches the entity's designated primary NAICS only.
    - any_naics matches any NAICS the entity has on file.
    - business_type_code covers self-selected types: QF (SDVOSB), A2
      (Women-Owned), 8W (WOSB), 23 (Minority-Owned), NB (Native American
      Owned), A3 (Labor Surplus Area Firm), and any other 2-character code
      from the SAM Functional Data Dictionary "Business Types" field: the
      full FDD set passes through. SDVOSB is NOT XS (that's S-Corp).
    - sba_business_type_code covers SBA-certified programs, which SAM.gov
      filters through a dedicated sbaBusinessTypeCode parameter: A6 (8(a)
      Program Participant), XX (HUBZone), JT (8(a) Joint Venture), A4 (Small
      Disadvantaged Business), A9 (SBA-Certified WOSB), A0 (SBA-Certified
      EDWOSB). Per the SAM data dictionary, XX is HUBZone and A6 is 8(a); do
      not swap them. Note A9 is the SBA-CERTIFIED WOSB population; 8W on
      business_type_code is the broader self-designated WOSB flag. SBA codes
      passed to business_type_code raise a redirect error.
    - state_code is 2-letter USPS.
    - purpose_of_registration: Z1=Federal Assistance Awards only, Z2=All
      Awards, Z3=IGT-Only (Intra-Governmental Transactions), Z4=Federal
      Assistance Awards and IGT, Z5=All Awards and IGT. (Pre-1.0.2
      releases blocked Z3/Z4 and mislabeled Z5 as "Supplemental grants".)
    - free_text (q parameter) ANDs multiple words together. "cybersecurity cloud"
      returns entities matching BOTH words, not either.

    Default registration_status is 'A' (Active); use 'E' for expired registrations.
    Only A and E are real filter values: D and I were live-verified 2026-08 to
    return 0 records for every query (dead values), and comma lists like "A,E"
    are accepted by the API but match nothing. One value per call.
    Note: expired records display registrationStatus "Inactive" in payloads
    even though the filter vocabulary is A/E.
    """
    from .constants import BUSINESS_TYPE_CODES, SBA_BUSINESS_TYPE_CODES

    size = _clamp(size, field="size", lo=1, hi=ENTITY_MAX_SIZE)
    if page < 0:
        raise ValueError(f"page must be >= 0. Got {page}.")
    primary_naics = _validate_naics(primary_naics, field="primary_naics")
    any_naics = _validate_naics(any_naics, field="any_naics")
    psc_code = _coerce_str(psc_code, field="psc_code")
    if state_code is not None:
        state_code = state_code.strip().upper()
        if not re.match(r"^[A-Z]{2}$", state_code):
            raise ValueError(
                f"state_code must be 2-letter USPS (e.g. 'VA', 'CA'). Got {state_code!r}."
            )
    # business_type_code: self-selected types only. SBA certification codes
    # filter through the separate sbaBusinessTypeCode API parameter, so a code
    # from that family redirects with an error instead of silently searching
    # the wrong field and returning 0 results.
    if business_type_code:
        probe = business_type_code.strip().upper()
        if probe in SBA_BUSINESS_TYPE_CODES:
            raise ValueError(
                f"business_type_code={business_type_code!r} is an SBA certification "
                f"code ({SBA_BUSINESS_TYPE_CODES[probe]}). SAM.gov filters SBA "
                f"certifications through a separate parameter; pass it as "
                f"sba_business_type_code instead."
            )
        # Format check only: the FDD defines dozens of valid codes beyond
        # our labeled table (NB, JV, A3, 1E, A7, M8, ...), and the old
        # whitelist blocked all of them (e.g. Native-American-owned
        # searches were impossible). Well-formed codes pass through.
        if not re.match(r"^[A-Z0-9]{2}$", probe):
            sample = ", ".join(list(BUSINESS_TYPE_CODES.keys())[:8])
            raise ValueError(
                f"business_type_code={business_type_code!r} must be a "
                f"2-character code from the SAM Functional Data Dictionary "
                f"(e.g. {sample}, NB, A3)."
            )
        business_type_code = probe
    if sba_business_type_code:
        sba_business_type_code = _validate_code_in_dict(
            sba_business_type_code, field="sba_business_type_code",
            valid_codes=SBA_BUSINESS_TYPE_CODES,
        )
    # WAF-safe + length clamp on user-controlled strings
    legal_business_name = _clamp_str_len(
        _validate_waf_safe(legal_business_name, field="legal_business_name"),
        field="legal_business_name", maximum=200,
    )
    free_text = _clamp_str_len(
        _validate_waf_safe(free_text, field="free_text"),
        field="free_text", maximum=500,
    )
    if include_sections is None:
        include_sections = ["entityRegistration", "coreData"]

    params: dict[str, Any] = {
        "samRegistered": "Yes",
        "registrationStatus": registration_status,
        "includeSections": ",".join(include_sections),
        "page": str(page),
        "size": str(size),
    }
    if legal_business_name:
        params["legalBusinessName"] = legal_business_name
    if primary_naics:
        params["primaryNaics"] = primary_naics
    if any_naics:
        params["naicsCode"] = any_naics
    if psc_code:
        params["pscCode"] = psc_code
    if business_type_code:
        params["businessTypeCode"] = business_type_code
    if sba_business_type_code:
        params["sbaBusinessTypeCode"] = sba_business_type_code
    if state_code:
        params["physicalAddressProvinceOrStateCode"] = state_code
    if purpose_of_registration:
        params["purposeOfRegistrationCode"] = purpose_of_registration
    if free_text:
        params["q"] = free_text

    return await _get(ENTITY_PATH, params)


@mcp.tool(annotations={"title": "Get Entity Reps and Certs", "readOnlyHint": True, "destructiveHint": False})
async def get_entity_reps_and_certs(
    uei: str,
    summary_only: bool = True,
    clause_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch FAR/DFARS representations and certifications for an entity by UEI.

    repsAndCerts is NOT included in the default response or even in
    includeSections=All. It must be explicitly requested. Returns the
    entity's responses to standard FAR 52.212-3, FAR 52.204-17, FAR 52.209-2,
    FAR 52.219-1, FAR 52.222-18, FAR 52.225-2, DFARS 252.204-7016, and other
    certification clauses.

    Combined with entityRegistration for identification context.

    Parameters:
    - summary_only (default True): returns a condensed view (clause ID, title,
      and answer summary per clause) instead of the full certification text.
      The full repsAndCerts payload for a large entity can exceed 70KB, which
      blows the MCP response budget. Set False to get the raw response.
    - clause_filter: list of FAR/DFARS clause identifiers to include
      (e.g. ['FAR 52.204-17', 'FAR 52.219-1']). Case-insensitive substring match.
      Combines with summary_only.
    """
    uei = _validate_uei(uei)
    params = {
        "ueiSAM": uei,
        "samRegistered": "Yes",
        "includeSections": "entityRegistration,repsAndCerts",
    }
    data = await _get(ENTITY_PATH, params)

    if not summary_only and not clause_filter:
        return data

    # Normalize XML-to-JSON single-item collapse: SAM sometimes returns entityData
    # as a dict instead of a list when there's one match.
    entity_data = _as_list(data.get("entityData"))
    if entity_data:
        data["entityData"] = entity_data
    if not entity_data:
        return data

    def _ci_get_list(container: Any, *names: str) -> list[Any]:
        """Case-insensitive key lookup tolerating SAM's mixed-case JSON keys.

        The Entity API documents 'fARResponses' and 'dFARResponses' (mixed
        case). Pre-1.0.2 code read 'farResponses'/'dfarsResponses', which do
        not exist, so the default summary mode returned empty clause lists
        for every entity: a CO asking for FAR 52.212-3 answers was told the
        entity certified nothing. Scan case-insensitively so either casing
        (and any future drift) resolves.
        """
        if not isinstance(container, dict):
            return []
        lowered = {k.lower(): v for k, v in container.items() if isinstance(k, str)}
        for name in names:
            v = lowered.get(name.lower())
            if v is not None:
                return _as_list(v)
        return []

    for entity in entity_data:
        if not isinstance(entity, dict):
            continue
        rc = entity.get("repsAndCerts")
        if not isinstance(rc, dict):
            continue
        certifications = rc.get("certifications") or {}
        if not isinstance(certifications, dict):
            certifications = {}
        # architectEngineerResponses lives under qualifications per the
        # docs, not certifications; check both homes.
        qualifications = rc.get("qualifications") or {}
        far_responses = _ci_get_list(certifications, "fARResponses")
        dfars_responses = _ci_get_list(certifications, "dFARResponses", "dFARSResponses")
        architect_responses = (
            _ci_get_list(qualifications, "architectEngineerResponses")
            or _ci_get_list(certifications, "architectEngineerResponses")
        )

        def _clause_matches(item: dict[str, Any]) -> bool:
            if not clause_filter:
                return True
            name = (item.get("provisionId") or "").lower()
            title = (item.get("title") or "").lower()
            return any(f.lower() in name or f.lower() in title for f in clause_filter)

        def _summarize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for item in items:
                if not _clause_matches(item):
                    continue
                if summary_only:
                    out.append({
                        "provisionId": item.get("provisionId"),
                        "title": item.get("title"),
                        "answerCount": len(item.get("listOfAnswers") or []),
                    })
                else:
                    out.append(item)
            return out

        entity["repsAndCerts"] = {
            "certifications": {
                "farResponses": _summarize(far_responses),
                "dfarsResponses": _summarize(dfars_responses),
                "architectEngineerResponses": _summarize(architect_responses),
            },
            "_summary_only": summary_only,
            "_clause_filter": clause_filter,
        }

    return data


@mcp.tool(annotations={"title": "Get Entity Integrity Info", "readOnlyHint": True, "destructiveHint": False})
async def get_entity_integrity_info(uei: str) -> dict[str, Any]:
    """Fetch FAPIIS proceedings integrity information for an entity by UEI.

    integrityInformation is NOT included in the default response or even
    includeSections=All. Requires explicit request plus proceedingsData=Yes
    query parameter. Returns proceedings disclosures per FAR 52.209-7/9.
    """
    uei = _validate_uei(uei)
    params = {
        "ueiSAM": uei,
        "samRegistered": "Yes",
        "includeSections": "entityRegistration,integrityInformation",
        "proceedingsData": "Yes",
    }
    return await _get(ENTITY_PATH, params)


# ---------------------------------------------------------------------------
# Exclusion tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Check Exclusion by UEI", "readOnlyHint": True, "destructiveHint": False})
async def check_exclusion_by_uei(uei: str) -> dict[str, Any]:
    """Check if an entity has any exclusion/debarment records by UEI.

    Returns exclusion records from the consolidated Excluded Parties List.
    totalRecords=0 means the entity is not currently excluded. totalRecords>0
    means one or more exclusion records exist; check recordStatus='Active' on
    each entry to determine if the exclusion is currently in effect.

    This is the single most important check for FAR 9.104-1 responsibility
    determinations and FAR 9.405 debarment prohibitions.
    """
    if not uei or not uei.strip():
        return {"totalRecords": 0, "excludedEntity": [], "_note": "Empty UEI provided."}
    uei = _validate_uei(uei)
    params = {"ueiSAM": uei}
    return await _get(EXCLUSIONS_PATH, params)


@mcp.tool(annotations={"title": "Search Exclusions", "readOnlyHint": True, "destructiveHint": False})
async def search_exclusions(
    entity_name: str | None = None,
    cage_code: str | None = None,
    classification: Literal["Firm", "Individual", "Vessel", "Special Entity Designation"] | None = None,
    exclusion_program: Literal["Reciprocal", "NonProcurement", "Procurement"] | None = None,
    excluding_agency_code: str | None = None,
    state_province: str | None = None,
    country: str | None = None,
    activation_date_range: str | None = None,
    free_text: str | None = None,
    page: int = 0,
    size: int = 10,
) -> dict[str, Any]:
    """Search SAM.gov exclusion records with flexible filters.

    All filters are AND-ed. Unlike Entity Management, Exclusions uses 'size'
    (not 'limit') for pagination. Size can go up to 100 per page.

    Key filter notes:
    - entity_name: firm name for classification=Firm; for individuals use
      the full name. Cannot contain &, |, {, }, ^, backslash.
    - cage_code: 5-character CAGE of the excluded entity.
    - classification: Firm, Individual, Vessel, or Special Entity Designation.
    - exclusion_program: Reciprocal (cross-agency), NonProcurement, or Procurement.
    - excluding_agency_code: agency code that imposed the exclusion (e.g., DOD, HHS).
    - country: MUST be 3-character ISO alpha-3 (USA, CAN, GBR). 2-char codes
      (US, CA, GB) return 0 results.
    - activation_date_range: use bracket format [MM/DD/YYYY,MM/DD/YYYY].
    - free_text (q parameter): supports wildcards (*), AND, OR operators.
      Example: "acme*" matches any company starting with acme.
    """
    size = _clamp(size, field="size", lo=1, hi=EXCLUSION_MAX_SIZE)
    if page < 0:
        raise ValueError(f"page must be >= 0. Got {page}.")
    activation_date_range = _validate_date_mmddyyyy(
        activation_date_range, field="activation_date_range"
    )
    entity_name = _clamp_str_len(
        _validate_waf_safe(entity_name, field="entity_name"),
        field="entity_name", maximum=200,
    )
    free_text = _clamp_str_len(
        _validate_waf_safe(free_text, field="free_text"),
        field="free_text", maximum=500,
    )
    if cage_code:
        cage_code = _validate_cage(cage_code)

    params: dict[str, Any] = {
        "page": str(page),
        "size": str(size),
    }
    if entity_name:
        # P1 bug fix in 0.3.6: SAM API rejects entityName as INVALID_SEARCH_PARAMETER.
        # Correct param name is exclusionName. Caught by round 6 live audit.
        params["exclusionName"] = entity_name
    if cage_code:
        params["cageCode"] = cage_code
    if classification:
        params["classification"] = classification
    if exclusion_program:
        params["exclusionProgram"] = exclusion_program
    if excluding_agency_code:
        params["excludingAgencyCode"] = excluding_agency_code
    if state_province:
        params["stateProvince"] = state_province
    if country:
        country_up = country.strip().upper()
        if not re.match(r"^[A-Z]{3}$", country_up):
            raise ValueError(
                f"country must be 3-character ISO alpha-3 (USA, CAN, GBR). "
                f"Got {country!r}."
            )
        params["country"] = country_up
    if activation_date_range:
        params["activationDate"] = activation_date_range
    if free_text:
        params["q"] = free_text

    return await _get(EXCLUSIONS_PATH, params)


# ---------------------------------------------------------------------------
# Opportunity tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Opportunities", "readOnlyHint": True, "destructiveHint": False})
async def search_opportunities(
    posted_from: str,
    posted_to: str,
    notice_type: Literal["p", "o", "k", "r", "g", "s", "i", "a", "u"] | None = None,
    title: str | None = None,
    solicitation_number: str | None = None,
    notice_id: str | None = None,
    naics_code: Union[str, int, None] = None,
    psc_code: str | None = None,
    set_aside: str | None = None,
    state: str | None = None,
    zip_code: Union[str, int, None] = None,
    response_deadline_from: str | None = None,
    response_deadline_to: str | None = None,
    agency_keyword: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Search contract opportunities on SAM.gov.

    posted_from and posted_to are MANDATORY. Format is MM/DD/YYYY (not ISO 8601).
    The date range cannot exceed 364 days. For older notices or longer ranges,
    chain multiple calls with sequential date windows.

    Notice type codes:
    - p = Presolicitation
    - o = Solicitation
    - k = Combined Synopsis/Solicitation
    - r = Sources Sought
    - s = Special Notice
    - i = Intent to Bundle
    - a = Award Notice
    - u = Justification (J&A)
    - g = Sale of Surplus Property

    WORKING filters: title, solicitation_number, notice_id, notice_type,
    naics_code, psc_code, set_aside, state, zip_code, response_deadline_from,
    response_deadline_to.

    BROKEN filters (do not use): deptname, subtier. The SAM.gov API silently
    ignores these. To filter by agency, use agency_keyword: this tool will
    post-filter the results by checking fullParentPathName for a substring match.

    PSC code filter (psc_code) requires exact 4-character match. Prefix
    matching (e.g. 'R4') returns 0 results; use 'R425'.

    Set-aside codes: SBA, SBP, 8A, 8AN, HZC, HZS, SDVOSBC, SDVOSBS, WOSB,
    WOSBSS, EDWOSB, EDWOSBSS, LAS (Local Area), IEE (Buy Indian Act),
    ISBEE (Buy Indian Act small business), BICiv (IHS Buy Indian),
    VSA, VSS. Case-insensitive; documented casing goes on the wire.

    The 'description' field in each result is a URL, not inline text. Use
    get_opportunity_description() to fetch the actual description HTML.

    Pagination (live-verified 2026-08): offset is a ZERO-BASED PAGE INDEX
    (page size = limit), not a record skip count; offset=1 with limit=100
    returns records 101-200. Compute the last page from totalRecords and stop
    there: pages past the end do NOT come back empty, they return one
    arbitrary record, so an empty-page loop terminator never fires.
    """
    from .constants import SET_ASIDE_CODES, SET_ASIDE_WIRE_CASING

    limit = _clamp(limit, field="limit", lo=1, hi=OPPORTUNITY_MAX_LIMIT)
    if offset < 0:
        raise ValueError(f"offset must be >= 0. Got {offset}.")
    posted_from = _validate_date_mmddyyyy(
        posted_from, field="posted_from", allow_range=False
    )
    posted_to = _validate_date_mmddyyyy(
        posted_to, field="posted_to", allow_range=False
    )
    response_deadline_from = _validate_date_mmddyyyy(
        response_deadline_from, field="response_deadline_from", allow_range=False
    )
    response_deadline_to = _validate_date_mmddyyyy(
        response_deadline_to, field="response_deadline_to", allow_range=False
    )

    # 364-day cap + reversed-range check (SAM API enforces both; pre-check here)
    def _parse_mmddyyyy(s: str) -> date:
        mm, dd, yyyy = s.split("/")
        return date(int(yyyy), int(mm), int(dd))
    pf = _parse_mmddyyyy(posted_from)
    pt = _parse_mmddyyyy(posted_to)
    if pf > pt:
        raise ValueError(
            f"posted_from ({posted_from}) is after posted_to ({posted_to}). "
            f"SAM.gov requires posted_from <= posted_to."
        )
    if (pt - pf).days > 364:
        raise ValueError(
            f"posted_from to posted_to range exceeds 364 days "
            f"({(pt - pf).days} days). SAM.gov hard-caps this range; "
            f"chain multiple calls with sequential date windows to cover longer periods."
        )

    naics_code = _validate_naics(naics_code, field="naics_code")
    psc_code = _coerce_str(psc_code, field="psc_code")
    zip_code = _coerce_str(zip_code, field="zip_code")
    if zip_code and zip_code.isdigit() and len(zip_code) < 5:
        # An int zip like 6511 lost its leading zero in coercion; New Haven
        # is 06511 and the API silently returns nothing for '6511'.
        zip_code = zip_code.zfill(5)
    if state is not None:
        state = state.strip().upper()
        if not re.match(r"^[A-Z]{2}$", state):
            raise ValueError(
                f"state must be 2-letter USPS (e.g. 'VA', 'CA'). Got {state!r}."
            )
    set_aside = _validate_code_in_dict(set_aside, field="set_aside", valid_codes=SET_ASIDE_CODES)
    if set_aside:
        # BICiv is documented mixed-case; validation upcased it for lookup.
        set_aside = SET_ASIDE_WIRE_CASING.get(set_aside, set_aside)
    title = _clamp_str_len(
        _validate_waf_safe(title, field="title"),
        field="title", maximum=500,
    )
    solicitation_number = _clamp_str_len(
        _validate_waf_safe(solicitation_number, field="solicitation_number"),
        field="solicitation_number", maximum=100,
    )

    params: dict[str, Any] = {
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "limit": str(limit),
        "offset": str(offset),
    }
    if notice_type:
        params["ptype"] = notice_type
    if title:
        params["title"] = title
    if solicitation_number:
        params["solnum"] = solicitation_number
    if notice_id:
        params["noticeid"] = notice_id
    if naics_code:
        params["ncode"] = naics_code
    if psc_code:
        params["ccode"] = psc_code
    if set_aside:
        params["typeOfSetAside"] = set_aside
    if state:
        params["state"] = state
    if zip_code:
        params["zip"] = zip_code
    if response_deadline_from:
        params["rdlfrom"] = response_deadline_from
    if response_deadline_to:
        params["rdlto"] = response_deadline_to

    result = await _get(OPPORTUNITIES_PATH, params)

    # Post-filter by agency if requested (the deptname/subtier API params are broken)
    if agency_keyword and isinstance(result.get("opportunitiesData"), list):
        keyword_upper = agency_keyword.upper()
        filtered = [
            o for o in result["opportunitiesData"]
            if keyword_upper in (o.get("fullParentPathName") or "").upper()
        ]
        result["opportunitiesData"] = filtered
        result["totalRecords_postFilter"] = len(filtered)
        result["_postFilter"] = f"agency_keyword={agency_keyword!r}"

    return result


@mcp.tool(annotations={"title": "Get Opportunity Description", "readOnlyHint": True, "destructiveHint": False})
async def get_opportunity_description(notice_id: str) -> dict[str, Any]:
    """Fetch the full description text for a contract opportunity by notice ID.

    The 'description' field in search_opportunities results is a URL, not
    inline text. This tool handles the second fetch to retrieve the actual
    HTML description. Pass the noticeId from the search results.
    """
    if not notice_id or not notice_id.strip():
        raise ValueError("notice_id cannot be empty.")
    params = {"noticeid": notice_id.strip()}
    return await _get(OPPORTUNITY_DESC_PATH, params)


# ---------------------------------------------------------------------------
# PSC lookup tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Lookup PSC Code", "readOnlyHint": True, "destructiveHint": False})
async def lookup_psc_code(
    code: str,
    active_only: Literal["Y", "N", "ALL"] = "Y",
) -> dict[str, Any]:
    """Look up a Product/Service Code (PSC) by its code value.

    Returns the PSC name, full name, level 1 and level 2 category information,
    and includes/excludes guidance. Useful for validating PSC codes before
    using them as filters in other searches.
    """
    if not code or not code.strip():
        raise ValueError("code cannot be empty. PSC codes are 4 characters (e.g. 'R425').")
    code = code.strip().upper()
    if len(code) < 2:
        raise ValueError(
            f"code must be at least 2 characters. Got {code!r}. "
            f"PSC codes are typically 4 characters (e.g. 'R425')."
        )
    params = {
        "q": code,
        "searchby": "psc",
        "active": active_only,
    }
    return await _get(PSC_PATH, params)


@mcp.tool(annotations={"title": "Search PSC Free Text", "readOnlyHint": True, "destructiveHint": False})
async def search_psc_free_text(
    query: str,
    active_only: Literal["Y", "N", "ALL"] = "Y",
) -> dict[str, Any]:
    """Free-text search for Product/Service Codes (PSC).

    Searches across PSC names, descriptions, and category hierarchy. Returns
    matching PSC codes with full context. Useful for discovering PSCs from
    plain-language descriptions like 'engineering' or 'application development'.
    """
    if not query or not query.strip():
        raise ValueError(
            "query cannot be empty. Pass at least 2 characters of search text."
        )
    query = _validate_waf_safe(query.strip(), field="query")
    if len(query) < 2:
        raise ValueError(
            f"query must be at least 2 characters. Got {query!r}."
        )
    query = _clamp_str_len(query, field="query", maximum=200)
    params = {
        "q": query,
        "active": active_only,
    }
    return await _get(PSC_PATH, params)


# ---------------------------------------------------------------------------
# Contract Awards tools (FPDS replacement)
# ---------------------------------------------------------------------------


def _normalize_awards_response(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the inconsistent Contract Awards response wrapper.

    Populated results: {"awardSummary": [...], "totalRecords": 123, ...}
    Empty results:     {"awardResponse": {"totalRecords": "0", ...}, "message": "No Data..."}
    Also observed:     {"totalRecords": null, ...} (partial/malformed responses)

    This normalizes empty/null results to match the populated shape so callers
    always see {"awardSummary": [...], "totalRecords": int, ...}.
    """
    if not isinstance(data, dict):
        return {"awardSummary": [], "totalRecords": 0, "_note": "Unexpected response shape."}

    if "awardResponse" in data and "awardSummary" not in data:
        ar = data["awardResponse"] if isinstance(data["awardResponse"], dict) else {}
        return {
            "awardSummary": [],
            "totalRecords": _safe_int(ar.get("totalRecords"), default=0),
            "limit": _safe_int(ar.get("limit"), default=10),
            "offset": _safe_int(ar.get("offset"), default=0),
            "message": data.get("message", ""),
        }
    # Populated responses sometimes return totalRecords as a string or null
    if "totalRecords" in data:
        data["totalRecords"] = _safe_int(data["totalRecords"], default=0)
    if "awardSummary" in data:
        data["awardSummary"] = _as_list(data["awardSummary"])
    # Round 7 fix: ensure callers always see at least
    # totalRecords. An empty dict from a CDN proxy used to return {} unchanged,
    # which broke downstream code that checked data["totalRecords"].
    if "totalRecords" not in data and "awardSummary" not in data:
        data["totalRecords"] = 0
        data["awardSummary"] = []
        data["_note"] = "Empty or unrecognized response shape from upstream."
    return data


@mcp.tool(annotations={"title": "Search Contract Awards", "readOnlyHint": True, "destructiveHint": False})
async def search_contract_awards(
    awardee_name: str | None = None,
    awardee_uei: str | None = None,
    awardee_cage_code: str | None = None,
    piid: str | None = None,
    naics_code: Union[str, int, None] = None,
    psc_code: str | None = None,
    contracting_department_code: Union[str, int, None] = None,
    contracting_subtier_code: Union[str, int, None] = None,
    contracting_office_code: str | None = None,
    date_signed: str | None = None,
    last_modified_date: str | None = None,
    fiscal_year: Union[str, int, None] = None,
    award_or_idv: Literal["AWARD", "IDV"] | None = None,
    type_of_contract_pricing_code: str | None = None,
    type_of_set_aside_code: str | None = None,
    extent_competed_code: str | None = None,
    dollars_obligated: str | None = None,
    modification_number: Union[str, int, None] = None,
    free_text: str | None = None,
    include_sections: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search contract award records on SAM.gov (FPDS replacement).

    This is the replacement for FPDS.gov (decommissioned Feb 2026). Same data,
    new endpoint. Uses limit/offset pagination (NOT page/size), and note that
    despite the name, offset is a ZERO-BASED PAGE INDEX (live-verified 2026-08):
    offset=1 with limit=100 returns records 101-200. Never advance offset by
    limit or you will silently skip almost everything.

    CRITICAL date format: MM/dd/yyyy for single dates, [MM/dd/yyyy,MM/dd/yyyy]
    for ranges (brackets included). ISO 8601 dates are rejected.

    Boolean operators: use ~ for OR (e.g. naics_code="541512~541511"),
    use ! for NOT (e.g. extent_competed_code="!A").

    Key parameters:
    - awardee_name: awardeeLegalBusinessName (partial match). NOT "vendorName".
    - awardee_uei: awardeeUniqueEntityId (exact match)
    - awardee_cage_code: awardeeCageCode (exact match)
    - piid: Procurement Instrument Identifier. Returns all mods for that PIID.
    - naics_code: 6-digit NAICS. Supports ~ for OR, ! for NOT.
    - psc_code: Product/Service Code (4-char). Supports ~ for OR.
    - contracting_department_code: top-level department (e.g. "9700" for DoD)
    - contracting_subtier_code: subtier agency (e.g. "1700" for Navy)
    - contracting_office_code: contracting office (e.g. "N00039")
    - date_signed: date of award action. MM/dd/yyyy or [MM/dd/yyyy,MM/dd/yyyy]
    - last_modified_date: when record was last modified. Same format.
    - fiscal_year: filter by FY (e.g. "2026"). Data observed back to FY1970.
    - award_or_idv: "AWARD" for contracts/orders, "IDV" for indefinite-delivery vehicles
    - type_of_contract_pricing_code: J=FFP, U=CPFF, etc.
    - type_of_set_aside_code: SBA, 8A, HZC, SDVOSBC, etc.
    - extent_competed_code: A=Full, B=Not Available, CDO=Competed Under SAP, etc.
    - dollars_obligated: bracket range [min,max] as string
    - modification_number: "0" for base award, specific mod number, or range
    - free_text: q parameter for full-text search across all fields
    - include_sections: comma-separated: contractId, coreData, awardDetails (default: all)
    - limit: max records per page (1-100, default 10)
    - offset: 0-based PAGE index (page size = limit), NOT a record skip count.
      Hard API ceiling: offset x limit must stay BELOW 400,000 (exactly 400,000
      returns HTTP 500 upstream; beyond it, HTTP 400). Only the first 400k
      records of any result set are pageable: narrow with filters, then page.

    Returns normalized response with awardSummary list and totalRecords count.
    Each record has up to 3 sections: contractId, coreData, awardDetails.
    """
    limit = _clamp(limit, field="limit", lo=1, hi=CONTRACT_AWARDS_MAX_LIMIT)
    if offset < 0:
        raise ValueError(f"offset must be >= 0. Got {offset}.")

    # UEI / CAGE format validation (only when provided)
    if awardee_uei:
        awardee_uei = _validate_uei(awardee_uei, field="awardee_uei")
    if awardee_cage_code:
        awardee_cage_code = _validate_cage(awardee_cage_code, field="awardee_cage_code")

    # Coerce numeric codes (accept int or str) + NAICS format
    naics_code = _validate_naics(naics_code, field="naics_code", allow_operators=True)
    contracting_department_code = _coerce_str(
        contracting_department_code, field="contracting_department_code"
    )
    contracting_subtier_code = _coerce_str(
        contracting_subtier_code, field="contracting_subtier_code"
    )
    modification_number = _coerce_str(modification_number, field="modification_number")
    fiscal_year = _validate_fiscal_year(fiscal_year)
    dollars_obligated = _validate_bracket_range(dollars_obligated, field="dollars_obligated")

    # Date validation
    date_signed = _validate_date_mmddyyyy(date_signed, field="date_signed")
    last_modified_date = _validate_date_mmddyyyy(last_modified_date, field="last_modified_date")

    # WAF-safe string check on free_text and awardee_name (SAM drops connection on
    # quotes/angle brackets/SQL). Length clamps too.
    free_text = _clamp_str_len(
        _validate_waf_safe(free_text, field="free_text"),
        field="free_text", maximum=500,
    )
    awardee_name = _clamp_str_len(
        _validate_waf_safe(awardee_name, field="awardee_name"),
        field="awardee_name", maximum=200,
    )

    params: dict[str, Any] = {
        "limit": str(limit),
        "offset": str(offset),
    }
    if awardee_name:
        params["awardeeLegalBusinessName"] = awardee_name
    if awardee_uei:
        params["awardeeUniqueEntityId"] = awardee_uei
    if awardee_cage_code:
        params["awardeeCageCode"] = awardee_cage_code
    if piid:
        params["piid"] = piid
    if naics_code:
        params["naicsCode"] = naics_code
    if psc_code:
        params["productOrServiceCode"] = psc_code
    if contracting_department_code:
        params["contractingDepartmentCode"] = contracting_department_code
    if contracting_subtier_code:
        params["contractingSubtierCode"] = contracting_subtier_code
    if contracting_office_code:
        params["contractingOfficeCode"] = contracting_office_code
    if date_signed:
        params["dateSigned"] = date_signed
    if last_modified_date:
        params["lastModifiedDate"] = last_modified_date
    if fiscal_year:
        params["fiscalYear"] = fiscal_year
    if award_or_idv:
        params["awardOrIDV"] = award_or_idv
    if type_of_contract_pricing_code:
        params["typeOfContractPricingCode"] = type_of_contract_pricing_code
    if type_of_set_aside_code:
        params["typeOfSetAsideCode"] = type_of_set_aside_code
    if extent_competed_code:
        params["extentCompetedCode"] = extent_competed_code
    if dollars_obligated:
        params["dollarsObligated"] = dollars_obligated
    if modification_number:
        params["modificationNumber"] = modification_number
    if free_text:
        params["q"] = free_text
    if include_sections:
        params["includeSections"] = include_sections

    result = await _get(CONTRACT_AWARDS_PATH, params)
    return _normalize_awards_response(result)


@mcp.tool(annotations={"title": "Lookup Award by PIID", "readOnlyHint": True, "destructiveHint": False})
async def lookup_award_by_piid(
    piid: str,
    include_sections: str | None = None,
) -> dict[str, Any]:
    """Look up contract award modifications for a single PIID.

    Returns up to 100 modification records for the given Procurement
    Instrument Identifier, sorted by modification number client-side (the
    API returns them unsorted). Large IDVs can exceed 100 mods; when
    totalRecords is larger than the returned list a _note flags the
    truncation. This is the primary way to get the history of a contract
    action.

    PIIDs are alphanumeric identifiers assigned by the contracting office.
    Format varies by agency (e.g. "GS-35F-0119Y", "W912BV22P0112",
    "N0003925F7516"). The search is exact match.

    include_sections: comma-separated list of contractId, coreData, awardDetails.
    Defaults to all sections if not specified.

    Returns normalized response with awardSummary list containing all
    modifications. Check totalRecords for the number of mods found.
    """
    if not piid or not piid.strip():
        raise ValueError(
            "piid cannot be empty. Pass a contract identifier like "
            "'GS-35F-0119Y', 'W912BV22P0112', or 'N0003925F7516'."
        )
    piid_clean = piid.strip()
    if any(c in piid_clean for c in ("\x00", "\n", "\r", "\t")):
        raise ValueError(f"piid={piid!r} contains control characters.")

    params: dict[str, Any] = {
        "piid": piid_clean,
        "limit": "100",
        "offset": "0",
    }
    if include_sections:
        params["includeSections"] = include_sections

    result = await _get(CONTRACT_AWARDS_PATH, params)
    result = _normalize_awards_response(result)

    def _mod_sort_key(item: Any) -> tuple[int, str]:
        """Tolerant modification-number extractor: the field lives under
        contractId in populated records but shapes vary. Numeric mods sort
        numerically ('2' before '10'), alpha mods (P00001, A) sort after
        base awards lexically."""
        if not isinstance(item, dict):
            return (1, "")
        contract_id = item.get("contractId")
        mod = None
        if isinstance(contract_id, dict):
            mod = contract_id.get("modificationNumber")
        if mod is None:
            mod = item.get("modificationNumber")
        s = str(mod).strip() if mod is not None else ""
        if s.isdigit():
            return (0, s.zfill(10))
        return (1, s)

    summary = result.get("awardSummary")
    if isinstance(summary, list) and summary:
        result["awardSummary"] = sorted(summary, key=_mod_sort_key)

    total = result.get("totalRecords")
    if isinstance(total, int) and isinstance(summary, list) and total > len(summary):
        result["_note"] = (
            f"PIID has {total} modification records; only the first "
            f"{len(summary)} were returned (API page limit 100). "
        )
    return result


@mcp.tool(annotations={"title": "Search Deleted Awards", "readOnlyHint": True, "destructiveHint": False})
async def search_deleted_awards(
    piid: str | None = None,
    awardee_name: str | None = None,
    contracting_department_code: Union[str, int, None] = None,
    last_modified_date: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search contract award records that have been deleted from FPDS/SAM.gov.

    Uses the same Contract Awards endpoint with deletedStatus=Y. Deleted
    records are removed from normal search results but remain accessible
    through this parameter. Useful for audit trails and historical research.

    Supports the same date format as search_contract_awards:
    MM/dd/yyyy or [MM/dd/yyyy,MM/dd/yyyy] for ranges.

    limit: 1-100 (default 10). offset: 0-based pagination.
    """
    limit = _clamp(limit, field="limit", lo=1, hi=CONTRACT_AWARDS_MAX_LIMIT)
    if offset < 0:
        raise ValueError(f"offset must be >= 0. Got {offset}.")
    contracting_department_code = _coerce_str(
        contracting_department_code, field="contracting_department_code"
    )
    last_modified_date = _validate_date_mmddyyyy(
        last_modified_date, field="last_modified_date"
    )

    params: dict[str, Any] = {
        "deletedStatus": "Y",
        "limit": str(limit),
        "offset": str(offset),
    }
    if piid:
        params["piid"] = piid
    if awardee_name:
        params["awardeeLegalBusinessName"] = awardee_name
    if contracting_department_code:
        params["contractingDepartmentCode"] = contracting_department_code
    if last_modified_date:
        params["lastModifiedDate"] = last_modified_date

    result = await _get(CONTRACT_AWARDS_PATH, params)
    return _normalize_awards_response(result)


# ---------------------------------------------------------------------------
# Composite workflow tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Vendor Responsibility Check", "readOnlyHint": True, "destructiveHint": False})
async def vendor_responsibility_check(uei: str) -> dict[str, Any]:
    """Composite pre-award vendor responsibility check per FAR 9.104-1.

    Performs TWO API calls in sequence:
    1. Entity Management lookup (registration status, business types,
       CAGE, activation/expiration dates, exclusion flag on the entity record)
    2. Exclusions lookup (active debarment/suspension records)

    Returns a structured summary with:
    - registration: full registration details or None if not registered
    - exclusion: exclusion record count and active exclusion details
    - flags: list of responsibility concern flags

    Flag meanings:
    - NOT_REGISTERED: entity has no SAM registration (cannot receive award per FAR 4.1102)
    - REGISTRATION_NOT_ACTIVE: registration expired or inactive
    - EXCLUSION_FLAG_ON_ENTITY: entity record indicates exclusion exists
    - ACTIVE_EXCLUSION_FOUND: confirmed active exclusion (FAR 9.405 prohibits award)

    No flags = clear for responsibility determination.
    """
    result: dict[str, Any] = {
        "uei": uei,
        "registration": None,
        "exclusion": None,
        "flags": [],
    }

    if not uei or not uei.strip():
        result["flags"].append("EMPTY_UEI")
        result["_note"] = "Cannot perform responsibility check without a UEI."
        return result

    try:
        uei = _validate_uei(uei)
    except ValueError as e:
        result["flags"].append("INVALID_UEI_FORMAT")
        result["_note"] = str(e)
        return result

    result["uei"] = uei

    # Step 1: Entity registration + coreData
    try:
        entity_resp = await _get(
            ENTITY_PATH,
            {
                "ueiSAM": uei,
                "samRegistered": "Yes",
                "includeSections": "entityRegistration,coreData",
            },
        )
    except Exception as e:
        result["registration"] = {"error": str(e)}
        result["flags"].append("ENTITY_LOOKUP_FAILED")
        entity_resp = None

    if entity_resp is not None:
        total = _safe_int(entity_resp.get("totalRecords"), default=0)
        entity_data = _as_list(entity_resp.get("entityData"))
        if total == 0 or not entity_data:
            result["flags"].append("NOT_REGISTERED")
        else:
            entity = entity_data[0]
            if not isinstance(entity, dict):
                result["flags"].append("ENTITY_SHAPE_UNEXPECTED")
                entity = {}
            reg = entity.get("entityRegistration") or {}
            if not isinstance(reg, dict):
                reg = {}
            core = entity.get("coreData") or {}
            if not isinstance(core, dict):
                core = {}
            business_types_obj = core.get("businessTypes") or {}
            if not isinstance(business_types_obj, dict):
                business_types_obj = {}
            biz_types = _as_list(business_types_obj.get("businessTypeList"))
            sba_types = _as_list(business_types_obj.get("sbaBusinessTypeList"))

            result["registration"] = {
                "legalBusinessName": reg.get("legalBusinessName"),
                "status": reg.get("registrationStatus"),
                "activationDate": reg.get("activationDate"),
                "expirationDate": reg.get("registrationExpirationDate"),
                "cageCode": reg.get("cageCode"),
                "ueiStatus": reg.get("ueiStatus"),
                "exclusionStatusFlag": reg.get("exclusionStatusFlag"),
                "publicDisplayFlag": reg.get("publicDisplayFlag"),
                "businessTypes": [
                    bt.get("businessTypeDesc") for bt in biz_types
                ],
                "sbaBusinessTypes": [
                    st.get("sbaBusinessTypeDesc") for st in sba_types
                ],
            }
            if reg.get("registrationStatus") != "Active":
                result["flags"].append("REGISTRATION_NOT_ACTIVE")
            if reg.get("exclusionStatusFlag") == "Y":
                result["flags"].append("EXCLUSION_FLAG_ON_ENTITY")

    # Step 2: Exclusions check
    try:
        excl_resp = await _get(EXCLUSIONS_PATH, {"ueiSAM": uei})
    except Exception as e:
        result["exclusion"] = {"error": str(e)}
        result["flags"].append("EXCLUSION_LOOKUP_FAILED")
        excl_resp = None

    if excl_resp is not None:
        total = _safe_int(excl_resp.get("totalRecords"), default=0)
        records = _as_list(excl_resp.get("excludedEntity"))
        if total == 0 or not records:
            result["exclusion"] = {"totalRecords": 0, "status": "NO_EXCLUSIONS_ON_RECORD"}
        else:
            active: list[dict[str, Any]] = []
            for r in records:
                if not isinstance(r, dict):
                    continue
                actions_obj = r.get("exclusionActions") or {}
                if not isinstance(actions_obj, dict):
                    actions_obj = {}
                actions = _as_list(actions_obj.get("listOfActions"))
                if any(isinstance(a, dict) and a.get("recordStatus") == "Active" for a in actions):
                    details = r.get("exclusionDetails") or {}
                    if not isinstance(details, dict):
                        details = {}
                    active.append({
                        "exclusionType": details.get("exclusionType"),
                        "exclusionProgram": details.get("exclusionProgram"),
                        "excludingAgency": details.get("excludingAgencyName"),
                        "classification": details.get("classificationType"),
                    })
            result["exclusion"] = {
                "totalRecords": total,
                "activeCount": len(active),
                "activeDetails": active,
            }
            if active:
                result["flags"].append("ACTIVE_EXCLUSION_FOUND")

    return result


# ---------------------------------------------------------------------------
# Federal Hierarchy tools
# ---------------------------------------------------------------------------

def _normalize_fh_response(data: dict[str, Any]) -> dict[str, Any]:
    """Federal Hierarchy uses lowercase 'totalrecords' and 'orglist' (different from
    the rest of SAM.gov which uses camelCase). Normalize so callers can rely on
    consistent keys, but preserve the originals too.
    """
    if not isinstance(data, dict):
        return {"totalrecords": 0, "orglist": [], "_note": "Unexpected response shape."}
    if "totalrecords" in data:
        data["totalrecords"] = _safe_int(data["totalrecords"], default=0)
    if "orglist" in data:
        data["orglist"] = _as_list(data["orglist"])
    return data


@mcp.tool(annotations={"title": "Search Federal Organizations", "readOnlyHint": True, "destructiveHint": False})
async def search_federal_organizations(
    fh_org_id: Union[str, int, None] = None,
    fh_org_name: str | None = None,
    fh_org_type: str | None = None,
    status: Literal["ACTIVE", "INACTIVE", "MERGED"] | None = None,
    agency_code: Union[str, int, None] = None,
    cgac: Union[str, int, None] = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search the SAM.gov Federal Hierarchy.

    Returns federal organizations (departments, agencies, sub-agencies, offices)
    with their FH IDs, codes, hierarchical relationships, and status. Useful
    for normalizing agency names to canonical FH IDs before passing them to
    Contract Awards, Opportunities, or Subaward searches.

    Filter notes:
    - fh_org_id: exact lookup by Federal Hierarchy organization ID (numeric).
    - fh_org_name: partial substring match on the organization name.
    - fh_org_type: case-insensitive substring filter. Live values from the API
      look like 'Department/Ind. Agency', but the API also accepts shorthand
      like 'DEPARTMENT' or 'AGENCY' and matches loosely. Pass whatever the
      response showed, or one of: department, agency, sub-agency, office,
      major command, field activity.
    - status: ACTIVE (default if filter omitted), INACTIVE (retired), or
      MERGED. Live audit (April 2026): the API defaults to ACTIVE-only when
      no filter is sent, so passing status='ACTIVE' is a no-op vs. the
      unfiltered call. Pass 'INACTIVE' to expand the search to retired orgs.
    - agency_code: legacy agency code if known.
    - cgac: Common Government-wide Accounting Classification (Treasury) code.

    Pagination uses limit (1-100) / offset (0-based). The Federal Hierarchy
    API uses lowercase 'totalrecords' and 'orglist' in responses (unlike the
    camelCase used elsewhere in SAM.gov); the normalizer preserves both keys.
    """
    limit = _clamp(limit, field="limit", lo=1, hi=FH_MAX_LIMIT)
    if offset < 0:
        raise ValueError(f"offset must be >= 0. Got {offset}.")
    fh_org_id = _coerce_str(fh_org_id, field="fh_org_id")
    agency_code = _coerce_str(agency_code, field="agency_code")
    cgac = _coerce_str(cgac, field="cgac")
    if cgac and cgac.isdigit() and len(cgac) < 3:
        # CGAC codes are 3 digits with meaningful leading zeros (HHS is
        # '075'); an int input like 75 lost its zero in coercion.
        cgac = cgac.zfill(3)
    fh_org_name = _clamp_str_len(
        _validate_waf_safe(fh_org_name, field="fh_org_name"),
        field="fh_org_name", maximum=200,
    )
    fh_org_type = _clamp_str_len(
        _validate_waf_safe(fh_org_type, field="fh_org_type"),
        field="fh_org_type", maximum=100,
    )

    params: dict[str, Any] = {
        "limit": str(limit),
        "offset": str(offset),
    }
    if fh_org_id:
        params["fhorgid"] = fh_org_id
    if fh_org_name:
        params["fhorgname"] = fh_org_name
    if fh_org_type:
        params["fhorgtype"] = fh_org_type
    if status:
        params["status"] = status
    if agency_code:
        params["agencycode"] = agency_code
    if cgac:
        params["cgac"] = cgac

    result = await _get(FH_ORGS_PATH, params)
    return _normalize_fh_response(result)


@mcp.tool(annotations={"title": "Get Organization Hierarchy", "readOnlyHint": True, "destructiveHint": False})
async def get_organization_hierarchy(
    fh_org_id: Union[str, int],
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Get the immediate child organizations of a federal organization.

    Pass an FH org ID (use search_federal_organizations to find one) and
    receive the list of its direct subordinates. To traverse the full tree,
    call recursively on each child.

    Pagination uses limit (1-100) / offset.
    """
    limit = _clamp(limit, field="limit", lo=1, hi=FH_MAX_LIMIT)
    if offset < 0:
        raise ValueError(f"offset must be >= 0. Got {offset}.")
    org_id = _coerce_str(fh_org_id, field="fh_org_id")
    if not org_id:
        raise ValueError(
            "fh_org_id cannot be empty. Use search_federal_organizations to "
            "find an org ID first."
        )

    params: dict[str, Any] = {
        "fhorgid": org_id,
        "limit": str(limit),
        "offset": str(offset),
    }
    result = await _get(FH_HIERARCHY_PATH, params)
    return _normalize_fh_response(result)


# ---------------------------------------------------------------------------
# Subaward Reporting tools (FFATA)
# ---------------------------------------------------------------------------


def _normalize_subaward_response(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize subaward responses. Both Acquisition and Assistance APIs use:
      {totalPages, totalRecords, pageNumber, nextPageLink, previousPageLink, data}
    But the wrapper can be missing fields when there are zero records, and 'data'
    can occasionally come back as a single dict instead of a list.
    """
    if not isinstance(data, dict):
        return {"totalRecords": 0, "data": [], "_note": "Unexpected response shape."}
    if "totalRecords" in data:
        data["totalRecords"] = _safe_int(data["totalRecords"], default=0)
    if "totalPages" in data:
        data["totalPages"] = _safe_int(data["totalPages"], default=0)
    if "pageNumber" in data:
        data["pageNumber"] = _safe_int(data["pageNumber"], default=0)
    if "data" in data:
        data["data"] = _as_list(data["data"])
    elif "totalRecords" in data:
        # API returned counts but no data array
        data["data"] = []
    else:
        data["totalRecords"] = 0
        data["data"] = []
        data["_note"] = "Empty or unrecognized response shape from upstream."
    return data


@mcp.tool(annotations={"title": "Search Acquisition Subawards", "readOnlyHint": True, "destructiveHint": False})
async def search_acquisition_subawards(
    prime_contract_key: str | None = None,
    piid: str | None = None,
    referenced_idv_piid: str | None = None,
    referenced_idv_agency_id: Union[str, int, None] = None,
    agency_id: Union[str, int, None] = None,
    prime_award_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    status: Literal["Published", "Deleted"] = "Published",
    page_number: int = 0,
    page_size: int = 100,
) -> dict[str, Any]:
    """Search FFATA subcontract reports (acquisition subawards).

    These are subcontracts reported by prime contractors under the Federal
    Funding Accountability and Transparency Act. Use this to map prime
    contractors to their subs, see subcontract values, and identify the
    full distribution of a federal procurement dollar.

    CRITICAL: dates use ISO yyyy-MM-dd format (NOT MM/dd/yyyy like the rest
    of SAM.gov). Pagination uses pageNumber/pageSize (NOT limit/offset).

    Key filters:
    - prime_contract_key: business key for subawards under a prime
    - piid: Procurement Instrument ID of the prime contract (returns all subs)
    - referenced_idv_piid: prime contract family identifier (parent IDV)
    - referenced_idv_agency_id: agency on the parent IDV
    - agency_id: four-digit agency code on the prime (e.g. 9700 for DoD)
    - prime_award_type: type of the parent prime award
    - from_date / to_date: yyyy-MM-dd window (filters on subaward report date)
    - status: 'Published' (default) or 'Deleted' for audit trails
    - page_number: 0-based page index. Stay within ceil(totalRecords/page_size):
      pages past the end HANG upstream until timeout (live-verified 2026-08)
    - page_size: 1-1000, default 100

    Response: {totalPages, totalRecords, pageNumber, nextPageLink,
    previousPageLink, data: [...]}.
    """
    page_size = _clamp(page_size, field="page_size", lo=1, hi=SUBAWARD_MAX_PAGE_SIZE)
    if page_number < 0:
        raise ValueError(f"page_number must be >= 0. Got {page_number}.")
    referenced_idv_agency_id = _coerce_str(
        referenced_idv_agency_id, field="referenced_idv_agency_id"
    )
    agency_id = _coerce_str(agency_id, field="agency_id")
    from_date = _validate_date_yyyy_mm_dd(from_date, field="from_date")
    to_date = _validate_date_yyyy_mm_dd(to_date, field="to_date")
    prime_contract_key = _clamp_str_len(
        _validate_waf_safe(prime_contract_key, field="prime_contract_key"),
        field="prime_contract_key", maximum=100,
    )
    piid = _clamp_str_len(
        _validate_waf_safe(piid, field="piid"),
        field="piid", maximum=100,
    )
    referenced_idv_piid = _clamp_str_len(
        _validate_waf_safe(referenced_idv_piid, field="referenced_idv_piid"),
        field="referenced_idv_piid", maximum=100,
    )
    prime_award_type = _clamp_str_len(
        _validate_waf_safe(prime_award_type, field="prime_award_type"),
        field="prime_award_type", maximum=100,
    )

    params: dict[str, Any] = {
        "pageNumber": str(page_number),
        "pageSize": str(page_size),
        "status": status,
    }
    if prime_contract_key:
        params["primeContractKey"] = prime_contract_key
    if piid:
        # Live audit (April 2026): the documented uppercase 'PIID' is silently
        # ignored by the API and returns the unfiltered total. The lowercase
        # 'piid' is what actually filters. Same surprise as deptname/subtier
        # on Opportunities.
        params["piid"] = piid
    if referenced_idv_piid:
        # Documented as 'referencedIdvPIID'; the working casing is
        # 'referencedIDVPIID' (caps on IDV). The documented form is silently
        # ignored.
        params["referencedIDVPIID"] = referenced_idv_piid
    if referenced_idv_agency_id:
        # Documented as 'referencedIDVAgencyID'; the working casing is
        # 'referencedIDVAgencyId' (lowercase d at the end). Documented form
        # is silently ignored.
        params["referencedIDVAgencyId"] = referenced_idv_agency_id
    if agency_id:
        params["agencyId"] = agency_id
    if prime_award_type:
        params["primeAwardType"] = prime_award_type
    if from_date:
        params["fromDate"] = from_date
    if to_date:
        params["toDate"] = to_date

    result = await _get(SUBCONTRACTS_PATH, params)
    return _normalize_subaward_response(result)


@mcp.tool(annotations={"title": "Search Assistance Subawards", "readOnlyHint": True, "destructiveHint": False})
async def search_assistance_subawards(
    prime_award_key: str | None = None,
    fain: str | None = None,
    agency_code: Union[str, int, None] = None,
    from_date: str | None = None,
    to_date: str | None = None,
    status: Literal["Published", "Deleted"] = "Published",
    page_number: int = 0,
    page_size: int = 100,
) -> dict[str, Any]:
    """Search FFATA grant subaward reports (financial assistance subawards).

    These are subawards reported by prime grant recipients on cooperative
    agreements and grants. Use this to trace federal grant funds from prime
    recipient down to subrecipients.

    CRITICAL: dates use ISO yyyy-MM-dd format (NOT MM/dd/yyyy). Pagination
    uses pageNumber/pageSize.

    Key filters:
    - prime_award_key: business key identifying subawards under a prime grant
    - fain: Federal Award Identification Number for grants
    - agency_code: FOUR-DIGIT agency code on the prime (e.g. 9700 for DoD,
      7529 for HHS/IHS). The API rejects anything else with "AgencyCode must
      be a four digit number"; 3-digit CGAC codes like 075 do NOT work here
      (unlike the Federal Hierarchy tools, which accept CGAC)
    - from_date / to_date: yyyy-MM-dd window
    - status: 'Published' (default) or 'Deleted'
    - page_number: 0-based page index. Stay within ceil(totalRecords/page_size):
      pages past the end HANG upstream until timeout (live-verified 2026-08)
    - page_size: 1-1000, default 100
    """
    page_size = _clamp(page_size, field="page_size", lo=1, hi=SUBAWARD_MAX_PAGE_SIZE)
    if page_number < 0:
        raise ValueError(f"page_number must be >= 0. Got {page_number}.")
    agency_code = _coerce_str(agency_code, field="agency_code")
    from_date = _validate_date_yyyy_mm_dd(from_date, field="from_date")
    to_date = _validate_date_yyyy_mm_dd(to_date, field="to_date")
    prime_award_key = _clamp_str_len(
        _validate_waf_safe(prime_award_key, field="prime_award_key"),
        field="prime_award_key", maximum=100,
    )
    fain = _clamp_str_len(
        _validate_waf_safe(fain, field="fain"),
        field="fain", maximum=100,
    )

    params: dict[str, Any] = {
        "pageNumber": str(page_number),
        "pageSize": str(page_size),
        "status": status,
    }
    if prime_award_key:
        params["primeAwardKey"] = prime_award_key
    if fain:
        params["fain"] = fain
    if agency_code:
        ac = str(agency_code).strip()
        if not (ac.isdigit() and len(ac) == 4):
            raise ValueError(
                f"agency_code must be a four-digit agency code (e.g. 9700 for "
                f"DoD). Got {agency_code!r}. The Assistance Subawards API "
                f"rejects 3-digit CGAC codes like 075."
            )
        params["agencyCode"] = ac
    if from_date:
        params["fromDate"] = from_date
    if to_date:
        params["toDate"] = to_date

    result = await _get(ASSISTANCE_SUBAWARDS_PATH, params)
    return _normalize_subaward_response(result)


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    Default MCPServer behavior is extra='ignore' which silently drops unknown
    parameter names. That turns a typo like search_entities(keyword='x')
    (the real param is free_text) into an unfiltered default-query response
    instead of an error. Applying extra='forbid' across the board surfaces
    typos immediately.
    """
    for tool in mcp._tool_manager.list_tools():
        am = tool.fn_metadata.arg_model
        am.model_config = {**am.model_config, "extra": "forbid"}
        am.model_rebuild(force=True)


_forbid_extra_params_on_all_tools()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
