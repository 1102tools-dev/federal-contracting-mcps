# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""BLS OEWS MCP server.

Provides access to Bureau of Labor Statistics Occupational Employment and
Wage Statistics (OEWS) data. Authentication via BLS_API_KEY environment
variable (optional but recommended for higher rate limits).

Without a key (v1): 25 queries/day, 25 series/query.
With a key (v2): 500 queries/day, 50 series/query.

OEWS data lags ~2 years. The server defaults to the correct data year
(currently 2025 = May 2025 estimates). Do NOT query the current calendar year.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Union

import httpx
from mcp.server import MCPServer

from . import __version__
from ._pacing import FederalApiPacer
from .constants import (
    BASE_URL_V1,
    BASE_URL_V2,
    COMMON_SOC_CODES,
    COUNT_DATATYPES,
    DATATYPE_LABELS,
    DEFAULT_TIMEOUT,
    HOURLY_DATATYPES,
    IGCE_DATATYPES,
    MAX_SERIES_V1,
    MAX_SERIES_V2,
    OEWS_CURRENT_YEAR,
    RATIO_DATATYPES,
    SERIES_ID_LENGTH,
    SPECIAL_VALUES,
    STATE_FIPS,
    USER_AGENT,
)

mcp = MCPServer("bls-oews", version=__version__)


# ---------------------------------------------------------------------------
# Validators and normalizers
# ---------------------------------------------------------------------------

# ASCII-only digit regex (Python's .isdigit() accepts Unicode digits like fullwidth)
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_DATATYPE_RE = re.compile(r"^[0-9]{2}$")
_YEAR_RE = re.compile(r"^[0-9]{4}$")

# OEWS data is available from 1997 onward (earliest published year).
# IMPORTANT: The BLS OEWS public API only serves the **latest** data year.
# Requesting a historical year returns empty rows with no error, which is why
# OEWS_LATEST_FUTURE_YEAR tightly hugs the current release. To get historical
# OEWS data, users must download tables from bls.gov/oes/tables.htm.
OEWS_EARLIEST_YEAR = 1997
OEWS_LATEST_FUTURE_YEAR = int(OEWS_CURRENT_YEAR) + 1


def _as_list(value: Any) -> list[Any]:
    """Normalize XML-to-JSON single-item collapse. BLS (and any SOAP-backed API)
    sometimes returns a lone dict where a list is expected."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_str_digits(value: Any, *, field: str, length: int | None = None) -> str:
    """Coerce a numeric-looking value (int or str) to an ASCII-digit string.

    Rejects Unicode digits (fullwidth, etc), whitespace, dashes. If length is
    given, enforces exact length after stripping."""
    if value is None:
        raise ValueError(f"{field} cannot be None.")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer or digit-string, not bool.")
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        s = value.strip()
    else:
        raise ValueError(f"{field} must be an integer or string. Got {type(value).__name__}.")
    if not s:
        raise ValueError(f"{field} cannot be empty.")
    if not _ASCII_DIGITS_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must contain only ASCII digits 0-9 "
            f"(no dashes, letters, whitespace, or Unicode digit characters)."
        )
    if length is not None and len(s) != length:
        raise ValueError(
            f"{field}={value!r} must be exactly {length} digits. Got {len(s)}."
        )
    return s


def _validate_soc(value: Any, *, field: str = "occ_code") -> str:
    """Validate a SOC code. Accepts both '15-1252' (standard BLS format) and
    '151252' (API format); the dash is stripped before validation.

    Returns the un-dashed 6-digit form that the BLS API expects.
    """
    if value is None:
        raise ValueError(f"{field} cannot be None.")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer or digit-string, not bool.")
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        # Reject control chars before strip() eats them.
        if any(c in value for c in ("\x00", "\n", "\r", "\t")):
            raise ValueError(
                f"{field}={value!r} contains control characters. "
                f"SOC codes are 6 digits with an optional single dash: '15-1252'."
            )
        # SOC codes are officially written as XX-XXXX. Strip the dash so users
        # can paste "15-1252" directly from BLS publications.
        s = value.strip().replace("-", "")
    else:
        raise ValueError(
            f"{field} must be an integer or string. Got {type(value).__name__}."
        )
    if not s:
        raise ValueError(f"{field} cannot be empty.")
    if not _ASCII_DIGITS_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be a SOC code like '15-1252' or '151252' "
            f"(6 ASCII digits, optional single dash after the first 2). "
            f"No letters, whitespace, or Unicode digits."
        )
    if len(s) != 6:
        raise ValueError(
            f"{field}={value!r} must be exactly 6 digits (got {len(s)}). "
            f"SOC codes are 'XX-XXXX' format, e.g. '15-1252' (Software Developers)."
        )
    return s


def _validate_industry(value: Any, *, field: str = "industry") -> str:
    """Validate a 6-digit NAICS-like industry code."""
    return _coerce_str_digits(value, field=field, length=6)


def _validate_datatype(value: Any, *, field: str = "datatype") -> str:
    """Validate a 2-digit datatype code. Accepts int or str."""
    s = _coerce_str_digits(value, field=field, length=2)
    if s not in DATATYPE_LABELS:
        sample = ", ".join(sorted(DATATYPE_LABELS.keys()))
        raise ValueError(
            f"{field}={value!r} is not a known OEWS datatype. Valid: {sample}."
        )
    return s


def _validate_year(value: Any, *, field: str = "year") -> str:
    """Validate a 4-digit year. Accepts int or str (stripped).

    The BLS OEWS public API only serves the **current** data year (see
    OEWS_LATEST_FUTURE_YEAR comment above). Requesting older years
    silently returns empty rows that look like privacy-suppressed cells.
    Pre-reject out-of-range years AND years before current with a clear
    message pointing users to the bulk-download alternative.
    """
    if value is None:
        return str(OEWS_CURRENT_YEAR)
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a year, not bool.")
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        s = value.strip()
    else:
        raise ValueError(f"{field} must be an integer or year-string. Got {type(value).__name__}.")
    if not s:
        return str(OEWS_CURRENT_YEAR)
    if not _YEAR_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be a 4-digit year (e.g. '2024' or 2024). "
            f"Decimals, whitespace, and leading zeros beyond 4 digits are rejected."
        )
    y = int(s)
    if y > OEWS_LATEST_FUTURE_YEAR:
        raise ValueError(
            f"{field}={y} is beyond the latest OEWS release ({OEWS_CURRENT_YEAR}). "
            f"Future years return empty from the BLS API. "
            f"Omit the year or pass {OEWS_CURRENT_YEAR}."
        )
    if y < int(OEWS_CURRENT_YEAR):
        raise ValueError(
            f"{field}={y} is before the current OEWS release. "
            f"The BLS OEWS public API only serves the latest year "
            f"({OEWS_CURRENT_YEAR}); historical years silently return empty "
            f"rows. For historical OEWS data, download from "
            f"bls.gov/oes/tables.htm. Omit the year argument to get current data."
        )
    return s


def _normalize_whitespace_str(value: Any) -> str | None:
    """Strip and normalize an arbitrary str-like value, or return None."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return str(value).strip() or None


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _redact_sensitive_text(text: str, secrets: tuple[str | None, ...] = ()) -> str:
    """Remove active credentials from upstream-controlled text in memory."""
    result = text
    for secret in sorted(
        {item for item in secrets if item}, key=len, reverse=True
    ):
        result = result.replace(secret, "[REDACTED]")
    return result


def _redact_sensitive_payload(
    value: Any, secrets: tuple[str | None, ...] = ()
) -> Any:
    """Recursively redact credentials before an upstream payload is returned."""
    if isinstance(value, str):
        return _redact_sensitive_text(value, secrets)
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_payload(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_payload(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_payload(item, secrets) for item in value)
    return value


def _clean_error_body(
    text: str, secrets: tuple[str | None, ...] = ()
) -> str:
    """Redact credentials and compact upstream error bodies for safe display."""
    text = _redact_sensitive_text(text, secrets)
    if not _HTML_ERROR_RE.search(text):
        return text[:400]
    pieces: list[str] = []
    t = _TITLE_RE.search(text)
    if t:
        pieces.append(t.group(1).strip())
    h = _H1_RE.search(text)
    if h and (not t or h.group(1).strip() != t.group(1).strip()):
        pieces.append(h.group(1).strip())
    return " - ".join(pieces) if pieces else "upstream returned HTML error page"


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str | None:
    """Read BLS API key from environment. None = v1 (25/day).

    Whitespace-only values are treated as unset (silent downgrade to v1). Callers
    that need to know whether a key was intentionally provided should use
    _api_key_status() instead.
    """
    key = os.environ.get("BLS_API_KEY", "").strip()
    return key if key else None


def _api_key_status() -> dict[str, Any]:
    """Report whether API key was set, empty, whitespace-only, or absent."""
    raw = os.environ.get("BLS_API_KEY")
    if raw is None:
        return {"set": False, "mode": "v1", "note": "BLS_API_KEY not set (v1, 25/day)"}
    stripped = raw.strip()
    if not stripped:
        return {
            "set": True, "mode": "v1",
            "note": "BLS_API_KEY is set but empty/whitespace-only; using v1 (25/day).",
        }
    return {"set": True, "mode": "v2", "note": "v2 mode (500/day)"}


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        )
    return _client


def _pacer(api_key: str | None) -> FederalApiPacer:
    return FederalApiPacer(
        bucket="api.bls.gov",
        default_interval=3.0,
        credential=api_key,
    )


def _format_error(status: int, body: str, api_key: str | None = None) -> str:
    cleaned = _clean_error_body(body, (api_key,))
    if status == 429:
        key = _get_api_key()
        limit = "500/day (v2)" if key else "25/day (v1)"
        return (
            f"HTTP 429: BLS rate limit exceeded ({limit}, plus published "
            "short-window limits). Do not retry in a burst. Register a free "
            "v2 key at https://data.bls.gov/registrationEngine/ for the "
            "higher published allowance."
        )
    if status == 400:
        return f"HTTP 400: Bad request. Check series ID format (must be exactly 25 chars). API response: {cleaned}"
    if status == 403:
        return (
            "HTTP 403: Forbidden. Your BLS API key may be invalid. "
            "Register a free key at https://data.bls.gov/registrationEngine/"
        )
    return f"HTTP {status}: {cleaned}"


async def _query_bls(
    series_ids: list[str],
    start_year: str | None = None,
    end_year: str | None = None,
    *,
    latest: bool = False,
) -> dict[str, Any]:
    """POST to BLS timeseries API.

    latest=True sends the API's latest=true flag with no year range, which
    returns whatever the newest available year is. Used by detect_latest_year
    so a stale OEWS_CURRENT_YEAR cannot mask a newer release.
    """
    api_key = _get_api_key()
    base_url = BASE_URL_V2 if api_key else BASE_URL_V1
    max_series = MAX_SERIES_V2 if api_key else MAX_SERIES_V1

    if len(series_ids) > max_series:
        raise ValueError(
            f"Too many series ({len(series_ids)}). "
            f"Max {max_series} per request ({'v2' if api_key else 'v1'}). "
            "Split into multiple calls."
        )

    if latest:
        payload: dict[str, Any] = {"seriesid": series_ids, "latest": "true"}
    else:
        year = start_year or OEWS_CURRENT_YEAR
        payload = {
            "seriesid": series_ids,
            "startyear": year,
            "endyear": end_year or year,
        }
    if api_key:
        payload["registrationkey"] = api_key

    try:
        async with _pacer(api_key).request_slot() as pacing:
            r = await _get_client().post(base_url, content=json.dumps(payload))
            pacing.observe_response(r)
            pacing.raise_if_rate_limited(
                r,
                service="BLS",
                guidance=_format_error(r.status_code, r.text, api_key),
            )
        r.raise_for_status()

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            body_preview = _clean_error_body(
                r.text or "(empty body)", (api_key,)
            )
            raise RuntimeError(
                f"BLS returned non-JSON response on 200 OK. "
                f"This often happens during API maintenance or when an HTML "
                f"error page is served without an error status. "
                f"Body: {body_preview}"
            ) from e

        data = _redact_sensitive_payload(data, (api_key,))
        if not isinstance(data, dict):
            raise RuntimeError(
                f"BLS response was not a JSON object. Got {type(data).__name__}: {str(data)[:200]}"
            )

        status = data.get("status")
        if status == "REQUEST_NOT_PROCESSED":
            messages = data.get("message", [])
            raise RuntimeError(
                f"BLS API refused the request: {messages}. "
                "Common cause: rate limit exceeded or malformed series IDs."
            )
        if status == "REQUEST_PARTIALLY_PROCESSED":
            # Surface the warnings so caller knows some series failed.
            messages = data.get("message", [])
            data["_partial"] = True
            data["_warnings"] = messages
        else:
            # REQUEST_SUCCEEDED can still carry per-series diagnostics like
            # "Series does not exist for Series OEU..." or "No Data Available
            # for Series ... Year: 2025". They are the definitive distinction
            # between a bad series ID and a real suppression, so keep them.
            msgs = [str(m) for m in _as_list(data.get("message")) if m]
            if msgs:
                data["_messages"] = msgs
        return data

    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            _format_error(e.response.status_code, e.response.text[:500], api_key)
        ) from e
    except httpx.RequestError as e:
        safe_error = _redact_sensitive_text(str(e), (api_key,))
        raise RuntimeError(f"Network error calling BLS: {safe_error}") from e


# ---------------------------------------------------------------------------
# Series ID helpers
# ---------------------------------------------------------------------------

def _build_series_id(
    prefix: str = "OEUN",
    area: str = "0000000",
    industry: str = "000000",
    occ_code: str = "000000",
    datatype: str = "04",
) -> str:
    """Build a 25-character OEWS series ID."""
    sid = f"{prefix}{area}{industry}{occ_code}{datatype}"
    if len(sid) != SERIES_ID_LENGTH:
        raise ValueError(
            f"Series ID must be {SERIES_ID_LENGTH} chars, got {len(sid)}: {sid}. "
            f"Components: prefix={prefix}({len(prefix)}), area={area}({len(area)}), "
            f"industry={industry}({len(industry)}), occ={occ_code}({len(occ_code)}), "
            f"datatype={datatype}({len(datatype)})"
        )
    return sid


def _normalize_area(area_input: Any) -> str:
    """Convert 2-digit FIPS, 5-digit MSA, or 7-digit full code to 7-char format.

    Requires ASCII digits only; rejects letters, unicode digits, whitespace.
    """
    if area_input is None:
        raise ValueError("area_code cannot be None.")
    if isinstance(area_input, int):
        area = str(area_input)
    else:
        area = str(area_input).strip()
    if not area:
        raise ValueError("area_code cannot be empty.")
    if not _ASCII_DIGITS_RE.match(area):
        raise ValueError(
            f"area_code={area_input!r} must contain only ASCII digits 0-9. "
            f"Got characters other than digits."
        )
    if len(area) == 7:
        return area
    if len(area) == 5:
        return f"00{area}"
    if len(area) == 2:
        return f"{area}00000"
    if len(area) == 1:
        # Single-digit state FIPS (CA=6, AK=2, etc.) — auto-pad.
        return f"0{area}00000"
    raise ValueError(
        f"Unrecognized area code '{area}' (length {len(area)}). "
        "Expected: 1-2 digit state FIPS (e.g., '6' for CA, '51' for VA), "
        "5-digit MSA (e.g., '47900'), or 7-digit full code (e.g., '0047900')."
    )


def _check_area_for_scope(scope: str, area: str, *, field: str = "area_code") -> None:
    """Catch scope/area mismatches before they burn a query.

    A 2-digit state FIPS normalizes to 'NN00000', which under scope='metro'
    builds a syntactically valid OEUM series that cannot exist; a 5-digit MSA
    under scope='state' is the same trap in reverse. Bogus state FIPS codes
    are rejected against the full OEWS state/territory set.
    """
    if scope == "state":
        if not area.endswith("00000"):
            raise ValueError(
                f"{field}={area!r} does not look like a state FIPS code. "
                f"scope='state' takes a 2-digit FIPS (e.g. '51' for VA). "
                f"For MSA codes use scope='metro'."
            )
        fips = area[:2]
        if fips not in STATE_FIPS:
            raise ValueError(
                f"{field} FIPS {fips!r} is not a state/territory OEWS "
                f"publishes. Valid FIPS: {', '.join(sorted(STATE_FIPS))}."
            )
    elif scope == "metro":
        if area.endswith("00000"):
            raise ValueError(
                f"{field}={area!r} looks like a 2-digit state FIPS, not an "
                f"MSA code. scope='metro' takes a 5-digit MSA (e.g. '47900' "
                f"for the DC metro). For states use scope='state'."
            )


def _parse_value(value: Any, datatype: str, footnotes: list[str] | None = None) -> dict[str, Any]:
    """Parse a BLS data value, handling special codes and unusual types."""
    # Normalize: str-coerce non-strings, strip whitespace (BLS sometimes pads)
    if value is None:
        return {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}
    raw = value
    if isinstance(value, str):
        stripped = value.strip()
    else:
        stripped = str(value).strip()

    if stripped in SPECIAL_VALUES or stripped == "":
        # BLS attaches a footnote explaining WHY the cell is unpublished
        # (annual-only occupation, sample too small, etc). Don't editorialize:
        # wage top-coding ended, so "-" no longer implies a cap.
        msg = f"[Not published] {footnotes[0]}" if footnotes else f"[Suppressed: {stripped or '(empty)'}]"
        return {"raw": raw, "formatted": msg, "numeric": None, "suppressed": True}

    try:
        if datatype in COUNT_DATATYPES:
            n = int(float(stripped))
            return {"raw": raw, "formatted": f"{n:,}", "numeric": n, "suppressed": False}
        elif datatype in RATIO_DATATYPES:
            n = float(stripped)
            return {"raw": raw, "formatted": f"{n:,.2f}", "numeric": n, "suppressed": False}
        elif datatype in HOURLY_DATATYPES:
            n = float(stripped)
            return {"raw": raw, "formatted": f"${n:,.2f}/hr", "numeric": n, "suppressed": False}
        else:
            n = int(float(stripped))
            return {"raw": raw, "formatted": f"${n:,}", "numeric": n, "suppressed": False}
    except (ValueError, TypeError):
        return {"raw": raw, "formatted": f"[Unparseable: {stripped}]", "numeric": None, "suppressed": False}


def _extract_first_data_entry(series_item: Any) -> dict[str, Any] | None:
    """Safely pull the first data entry from a series response, tolerating
    XML-to-JSON collapse, None entries, and missing keys. Returns None if no
    valid entry exists.
    """
    if not isinstance(series_item, dict):
        return None
    data = _as_list(series_item.get("data"))
    for entry in data:
        if isinstance(entry, dict):
            return entry
    return None


def _safe_footnotes(entry: dict[str, Any]) -> list[str]:
    """Extract footnote text strings, tolerating dict/str/None footnotes fields."""
    raw = entry.get("footnotes")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    items = _as_list(raw)
    out: list[str] = []
    for f in items:
        if isinstance(f, dict):
            text = f.get("text")
            if text:
                out.append(text)
        elif isinstance(f, str) and f.strip():
            out.append(f)
    return out


def _series_id_from(series_item: Any, fallback: str = "") -> str:
    """Extract seriesID from a series response item, tolerating int/missing."""
    if not isinstance(series_item, dict):
        return fallback
    sid = series_item.get("seriesID")
    if sid is None:
        return fallback
    return str(sid)


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Get Wage Data", "readOnlyHint": True, "destructiveHint": False})
async def get_wage_data(
    occ_code: Union[str, int],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: Union[str, int, None] = None,
    industry: Union[str, int] = "000000",
    datatypes: list[str] | None = None,
    year: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Get wage data for an occupation by SOC code.

    This is the primary tool for querying BLS OEWS wage statistics.

    occ_code: 6-digit SOC code without dash (e.g., '151252' for Software
    Developers, '131082' for Project Management Specialists). See
    list_common_soc_codes() for common mappings.

    scope + area_code:
    - 'national': no area_code needed (all US)
    - 'state': area_code = 2-digit state FIPS (e.g., '51' for VA, '11' for DC)
    - 'metro': area_code = 5-digit MSA code (e.g., '47900' for DC metro,
      '42660' for Seattle). See list_common_metros() for codes.

    industry: 6-digit industry code for national-only breakdowns.
    '000000' = all industries (default). Common: '541000' (Professional Services),
    '541500' (Computer Systems), '999100' (Federal Government). Industry
    breakdowns only work with scope='national'.

    datatypes: list of 2-digit codes. Default uses IGCE set:
    - '04' = Annual Mean Wage
    - '13' = Annual Median
    - '11' = Annual 10th Percentile
    - '15' = Annual 90th Percentile
    Hourly percentiles: '03' (Mean), '06' (10th), '07' (25th), '08'
    (Median), '09' (75th), '10' (90th). Annual percentiles: '11' (10th),
    '12' (25th), '13' (Median), '14' (75th), '15' (90th). Other: '01'
    (Employment); '16' (Employment per 1,000 Jobs) and '17' (Location
    Quotient) exist at state/metro scope only.

    CRITICAL: Data year defaults to 2025 (May 2025 estimates). Do NOT pass
    2026. OEWS estimates publish about a year in arrears (May 2025 estimates
    released April 2026), so the current calendar year returns nothing. Older
    years are withdrawn once superseded: 2024 now returns no data at all.
    Call detect_latest_year() if you need to confirm the newest published year.

    Special values ('-', '*', '#') mean BLS did not publish the cell; the
    attached footnote says why (annual-only occupation, sample too small).
    """
    occ_code = _validate_soc(occ_code)
    industry = _validate_industry(industry)
    year = _validate_year(year)

    if datatypes is None:
        datatypes = list(IGCE_DATATYPES)
    if not datatypes:
        raise ValueError(
            "datatypes cannot be empty. Pass None for defaults or specify at least one code."
        )
    validated_datatypes = [_validate_datatype(dt, field="datatypes[i]") for dt in datatypes]
    # Dedup while preserving order
    seen: set[str] = set()
    validated_datatypes = [x for x in validated_datatypes if not (x in seen or seen.add(x))]

    prefix_map = {"national": "OEUN", "state": "OEUS", "metro": "OEUM"}
    prefix = prefix_map[scope]

    if scope == "national":
        if area_code is not None:
            # area_code is ignored at national scope; keep quiet but flag in response
            pass
        area = "0000000"
    else:
        if area_code is None or (isinstance(area_code, str) and not area_code.strip()):
            raise ValueError(f"area_code is required for scope='{scope}'.")
        area = _normalize_area(area_code)
        _check_area_for_scope(scope, area)

    if industry != "000000" and scope != "national":
        raise ValueError(
            "Industry-specific estimates are only available at the national level "
            "(scope='national'). Cannot combine state/metro scope with industry filter."
        )

    series_ids = [_build_series_id(prefix, area, industry, occ_code, dt) for dt in validated_datatypes]
    data = await _query_bls(series_ids, start_year=year)

    results: dict[str, Any] = {}
    data_year: str | None = None
    data_period: str | None = None
    series_list = _as_list(data.get("Results", {}).get("series"))
    for series in series_list:
        if not isinstance(series, dict):
            continue
        sid = _series_id_from(series)
        dt = sid[-2:] if sid else ""
        label = DATATYPE_LABELS.get(dt, dt or "unknown")
        entry = _extract_first_data_entry(series)
        if entry:
            footnotes = _safe_footnotes(entry)
            results[label] = _parse_value(entry.get("value"), dt, footnotes)
            year_val = entry.get("year")
            period_val = entry.get("periodName")
            if year_val is not None:
                data_year = str(year_val)
            if period_val is not None:
                data_period = str(period_val)
        else:
            results[label] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    # Seed any requested datatype BLS omitted from the response entirely so
    # callers see an explicit "No data" instead of a silently absent key.
    for dt in validated_datatypes:
        label = DATATYPE_LABELS.get(dt, dt)
        if label not in results:
            results[label] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    response: dict[str, Any] = {
        "occ_code": occ_code,
        "scope": scope,
        "area_code": area_code if scope != "national" else None,
        "industry": industry,
        "data_year": data_year,
        "period": data_period,
        "wages": results,
    }

    # Flag no-data / all-suppressed cases so callers don't interpret
    # "suppressed: true" as "BLS suppressed this for privacy." Most of the
    # time the real cause is an unknown SOC, nonexistent area/industry code,
    # or a SOC that isn't surveyed in that area.
    wage_values = [
        v for v in results.values()
        if isinstance(v, dict) and v.get("numeric") is not None
    ]
    if not wage_values:
        response["no_data"] = True
        response["no_data_reason"] = (
            f"BLS returned no wage values for occ_code={occ_code} "
            f"scope={scope} area_code={area_code!r} industry={industry}. "
            f"Likely causes: (1) the SOC code does not exist or was recently "
            f"retired, (2) the area/industry combo has no observations, or "
            f"(3) the SOC is not surveyed at this geographic level. Verify "
            f"the SOC at bls.gov/soc and the area/industry codes before "
            f"treating this as a real suppression."
        )

    if scope == "national" and area_code is not None:
        response["_note"] = (
            f"area_code={area_code!r} was ignored because scope='national'. "
            "Use scope='state' or scope='metro' for geographic breakdowns."
        )
    if data.get("_partial"):
        response["_partial"] = True
        response["_warnings"] = data.get("_warnings", [])
    if data.get("_messages"):
        response["_api_messages"] = data["_messages"]
    return response


@mcp.tool(annotations={"title": "Compare Metros", "readOnlyHint": True, "destructiveHint": False})
async def compare_metros(
    occ_code: Union[str, int],
    metro_codes: list[Union[str, int]],
    datatype: Union[str, int] = "04",
    year: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Compare wages for one occupation across multiple metro areas.

    Pass a list of 5-digit MSA codes (e.g., ['47900', '42660', '12580']
    for DC, Seattle, Baltimore). Returns the specified wage measure for
    each metro. Use list_common_metros() to find codes.

    datatype: '04' (Annual Mean, default), '13' (Median), '03' (Hourly Mean).

    Max ~12 metros per call (each metro = 1 series, 50 series limit on v2).
    """
    occ_code = _validate_soc(occ_code)
    datatype = _validate_datatype(datatype)
    year = _validate_year(year)
    if not metro_codes:
        raise ValueError("metro_codes list cannot be empty.")

    # Dedup on the NORMALIZED form: '47900' and '0047900' are the same metro
    # and must collapse to one series (first spelling wins the label).
    series_ids: list[str] = []
    metro_labels: dict[str, str] = {}
    collapsed: list[str] = []
    for code in metro_codes:
        raw_label = str(code).strip()
        area = _normalize_area(code)
        # Reject state-FIPS-sized inputs in a metros-only context: after
        # normalization a 2-digit state FIPS becomes 'NN00000' which is a
        # valid-looking 7-digit series component, but it means the national
        # state record, not a metro. That silently produces zero-result
        # series. Enforce that metro_codes look like metros.
        if area.endswith("00000"):
            raise ValueError(
                f"metro_codes[{code!r}] looks like a 2-digit state FIPS. "
                f"compare_metros requires MSA codes (5 or 7 digits). "
                f"For states, use compare_occupations with scope='state' instead."
            )
        sid = _build_series_id("OEUM", area, "000000", occ_code, datatype)
        if sid in metro_labels:
            collapsed.append(raw_label)
            continue
        series_ids.append(sid)
        metro_labels[sid] = raw_label

    data = await _query_bls(series_ids, start_year=year)

    metros: dict[str, Any] = {}
    series_list = _as_list(data.get("Results", {}).get("series"))
    for series in series_list:
        if not isinstance(series, dict):
            continue
        sid = _series_id_from(series)
        code = metro_labels.get(sid, sid or "unknown")
        entry = _extract_first_data_entry(series)
        if entry:
            metros[code] = _parse_value(entry.get("value"), datatype, _safe_footnotes(entry))
        else:
            metros[code] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    # Seed requested metros missing from the response entirely.
    for sid, code in metro_labels.items():
        if code not in metros:
            metros[code] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    response: dict[str, Any] = {
        "occ_code": occ_code,
        "datatype": DATATYPE_LABELS.get(datatype, datatype),
        "metros": metros,
    }
    # Flag the all-no-data case: every metro returned empty.
    metros_with_values = [
        v for v in metros.values()
        if isinstance(v, dict) and v.get("numeric") is not None
    ]
    if metros and not metros_with_values:
        response["no_data"] = True
        response["no_data_reason"] = (
            f"No BLS data for occ_code={occ_code} across any of the requested "
            f"metros. Likely cause: the SOC code does not exist, is retired, "
            f"or is not surveyed at MSA level. Verify the SOC at bls.gov/soc."
        )
    if collapsed:
        response["_note"] = (
            f"Inputs {collapsed} normalized to the same series as another "
            f"input and were collapsed (first spelling wins)."
        )
    if data.get("_partial"):
        response["_partial"] = True
        response["_warnings"] = data.get("_warnings", [])
    if data.get("_messages"):
        response["_api_messages"] = data["_messages"]
    return response


@mcp.tool(annotations={"title": "Compare Occupations", "readOnlyHint": True, "destructiveHint": False})
async def compare_occupations(
    occ_codes: list[Union[str, int]],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: Union[str, int, None] = None,
    datatype: Union[str, int] = "04",
    year: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Compare wages across multiple occupations in one location.

    Pass a list of 6-digit SOC codes. Returns the specified wage measure
    for each occupation. Use list_common_soc_codes() to find codes.

    Max ~12 occupations per call.
    """
    if not occ_codes:
        raise ValueError("occ_codes list cannot be empty.")

    datatype = _validate_datatype(datatype)
    year = _validate_year(year)

    prefix_map = {"national": "OEUN", "state": "OEUS", "metro": "OEUM"}
    prefix = prefix_map[scope]

    if scope == "national":
        area = "0000000"
    else:
        if area_code is None or (isinstance(area_code, str) and not area_code.strip()):
            raise ValueError(f"area_code required for scope='{scope}'.")
        area = _normalize_area(area_code)
        _check_area_for_scope(scope, area)

    # Dedup on the NORMALIZED SOC: '15-1252' and '151252' are the same
    # occupation and must collapse to one series (first spelling wins).
    series_ids: list[str] = []
    occ_labels: dict[str, str] = {}
    collapsed: list[str] = []
    for code in occ_codes:
        raw_label = str(code).strip()
        if not raw_label:
            continue
        validated = _validate_soc(code)
        sid = _build_series_id(prefix, area, "000000", validated, datatype)
        if sid in occ_labels:
            collapsed.append(raw_label)
            continue
        series_ids.append(sid)
        occ_labels[sid] = validated

    if not series_ids:
        raise ValueError("occ_codes contained no usable SOC codes.")

    data = await _query_bls(series_ids, start_year=year)

    occupations: dict[str, Any] = {}
    series_list = _as_list(data.get("Results", {}).get("series"))
    for series in series_list:
        if not isinstance(series, dict):
            continue
        sid = _series_id_from(series)
        code = occ_labels.get(sid, sid or "unknown")
        label = COMMON_SOC_CODES.get(code, code)
        entry = _extract_first_data_entry(series)
        if entry:
            occupations[f"{code} ({label})"] = _parse_value(
                entry.get("value"), datatype, _safe_footnotes(entry)
            )
        else:
            occupations[f"{code} ({label})"] = {
                "raw": None, "formatted": "No data", "numeric": None, "suppressed": True,
            }

    # Seed requested occupations missing from the response entirely.
    for sid, code in occ_labels.items():
        label = COMMON_SOC_CODES.get(code, code)
        key = f"{code} ({label})"
        if key not in occupations:
            occupations[key] = {
                "raw": None, "formatted": "No data", "numeric": None, "suppressed": True,
            }

    response: dict[str, Any] = {
        "scope": scope,
        "area_code": area_code if scope != "national" else None,
        "datatype": DATATYPE_LABELS.get(datatype, datatype),
        "occupations": occupations,
    }
    # Flag the all-no-data case, mirroring compare_metros: without this,
    # nonexistent SOCs are indistinguishable from privacy suppressions.
    occ_with_values = [
        v for v in occupations.values()
        if isinstance(v, dict) and v.get("numeric") is not None
    ]
    if not occ_with_values:
        response["no_data"] = True
        response["no_data_reason"] = (
            f"No BLS data for any requested occupation at scope={scope} "
            f"area_code={area_code!r}. Likely causes: nonexistent or retired "
            f"SOC codes, or SOCs not surveyed at this geographic level. "
            f"Verify at bls.gov/soc."
        )
    if collapsed:
        response["_note"] = (
            f"Inputs {collapsed} normalized to the same series as another "
            f"input and were collapsed (first spelling wins)."
        )
    if data.get("_partial"):
        response["_partial"] = True
        response["_warnings"] = data.get("_warnings", [])
    if data.get("_messages"):
        response["_api_messages"] = data["_messages"]
    return response


@mcp.tool(annotations={"title": "IGCE Wage Benchmark", "readOnlyHint": True, "destructiveHint": False})
async def igce_wage_benchmark(
    occ_code: Union[str, int],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: Union[str, int, None] = None,
    burden_low: float = 1.8,
    burden_high: float = 2.2,
    year: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Get wage benchmarks formatted for IGCE development.

    Returns annual and hourly wages at mean, median, 10th, and 90th
    percentiles, plus estimated burdened hourly rates using the specified
    burden multiplier range.

    BLS wages are BASE wages (no fringe, overhead, G&A, or profit).
    Multiply by a burden factor to estimate fully-loaded rates:
    - 1.5x-1.7x: lean contractor
    - 1.8x-2.2x: mid-range professional services (default)
    - 2.0x-2.5x: large contractor with clearance overhead
    - 2.5x-3.0x: high-overhead (SCIF, deployed)

    The burdened range should roughly align with GSA CALC+ ceiling rates
    for comparable labor categories. If CALC+ >> burdened BLS, the role
    may require specialized skills or clearance overhead. Document the gap.

    Burden multipliers must be positive and burden_low <= burden_high.
    Reasonable range: 1.3 (lean) to 4.0 (high-overhead/clearance).
    """
    if not isinstance(burden_low, (int, float)) or not isinstance(burden_high, (int, float)):
        raise ValueError("burden_low and burden_high must be numeric.")
    if burden_low <= 0 or burden_high <= 0:
        raise ValueError(
            f"Burden multipliers must be positive. Got low={burden_low}, high={burden_high}."
        )
    if burden_low > burden_high:
        raise ValueError(
            f"burden_low ({burden_low}) must be <= burden_high ({burden_high})."
        )
    if burden_high > 10.0:
        raise ValueError(
            f"burden_high={burden_high} is implausibly large. "
            f"Reasonable max ~4.0x for high-overhead (SCIF/deployed) work."
        )

    # "03" rides along to detect annual-only occupations: BLS suppresses the
    # hourly mean for jobs that do not work a standard year-round schedule
    # (pilots, teachers), and a 2080-hour derived rate misstates their cost.
    wage_data = await get_wage_data(
        occ_code=occ_code, scope=scope, area_code=area_code,
        datatypes=["03", "04", "11", "13", "15"], year=year,
    )

    wages = wage_data.get("wages", {})
    hourly_mean = wages.get("Hourly Mean Wage", {})
    annual_mean = wages.get("Annual Mean Wage", {})
    annual_only = (
        isinstance(hourly_mean, dict) and hourly_mean.get("numeric") is None
        and isinstance(annual_mean, dict) and annual_mean.get("numeric") is not None
    )
    benchmarks: dict[str, Any] = {}

    for label in ["Annual Mean Wage", "Annual 10th Percentile", "Annual Median", "Annual 90th Percentile"]:
        entry = wages.get(label, {})
        annual = entry.get("numeric")
        if annual and not entry.get("suppressed"):
            hourly = round(annual / 2080, 2)
            benchmarks[label] = {
                "annual": f"${annual:,}",
                "hourly_base": f"${hourly:.2f}",
                "hourly_burdened_low": f"${round(hourly * burden_low, 2):.2f}",
                "hourly_burdened_high": f"${round(hourly * burden_high, 2):.2f}",
                "numeric_annual": annual,
                "numeric_hourly": hourly,
            }
        else:
            benchmarks[label] = {"annual": entry.get("formatted", "No data"), "suppressed": True}

    # Look up occ_title. Our lookup table uses the un-dashed 6-digit form.
    normalized_soc = str(occ_code).replace("-", "").strip()
    occ_title_lookup = COMMON_SOC_CODES.get(normalized_soc)
    title_is_lookup_miss = occ_title_lookup is None

    response: dict[str, Any] = {
        "occ_code": occ_code,
        "occ_title": occ_title_lookup or occ_code,
        "scope": scope,
        "area_code": area_code,
        "data_year": wage_data.get("data_year") or OEWS_CURRENT_YEAR,
        "burden_range": f"{burden_low}x - {burden_high}x",
        "benchmarks": benchmarks,
        "_note": "BLS wages are base wages only (no fringe/overhead/G&A/profit). Burdened rates are estimates.",
    }

    # Propagate the no_data flag from the underlying wage_data call so the
    # caller knows the benchmarks are all zero-value, not real suppressions.
    if wage_data.get("no_data"):
        response["no_data"] = True
        response["no_data_reason"] = wage_data.get("no_data_reason")
    if annual_only:
        response["annual_only"] = True
        response["_hourly_warning"] = (
            "BLS publishes no hourly wage for this occupation because it "
            "does not generally work a 2080-hour year (think pilots or "
            "teachers). The hourly figures above are derived as annual/2080 "
            "and may materially misstate the true hourly rate. Benchmark "
            "against the annual figures instead."
        )
    if wage_data.get("_api_messages"):
        response["_api_messages"] = wage_data["_api_messages"]
    if title_is_lookup_miss:
        response["_title_warning"] = (
            f"occ_code={occ_code!r} was not found in the built-in SOC title "
            f"lookup. Verify the code at bls.gov/soc before relying on the "
            f"benchmark -- typos or retired SOCs produce all-zero benchmarks."
        )

    return response


@mcp.tool(annotations={"title": "Detect Latest Year", "readOnlyHint": True, "destructiveHint": False})
async def detect_latest_year() -> dict[str, Any]:
    """Ask the BLS API which OEWS data year is the newest available.

    OEWS releases annually around April/May, and BLS serves ONLY the latest
    survey year (older years are withdrawn). This probe sends the API's
    latest=true flag with no year range, so it reports the true newest year
    even if this package's default has fallen multiple years behind.

    Call this once at the start of an IGCE build to confirm the default
    year still matches reality.
    """
    probe_series = "OEUN000000000000000000004"  # National all-occupation annual mean
    current = OEWS_CURRENT_YEAR

    try:
        data = await _query_bls([probe_series], latest=True)
        series_list = _as_list(data.get("Results", {}).get("series"))
        for s in series_list:
            entry = _extract_first_data_entry(s)
            if entry and str(entry.get("value", "")).strip() not in SPECIAL_VALUES:
                api_year = str(entry.get("year", "")).strip()
                if not api_year:
                    break
                newer = int(api_year) > int(current)
                if newer:
                    msg = (
                        f"OEWS {api_year} data is available but this server "
                        f"defaults to {current}. Pass year='{api_year}' "
                        f"explicitly until the package updates its default."
                    )
                elif api_year == current:
                    msg = (
                        f"OEWS {current} is the latest available. Next "
                        f"release expected ~April {int(current) + 2}."
                    )
                else:
                    msg = (
                        f"BLS reports {api_year} as latest, OLDER than this "
                        f"server's default {current}. Default-year queries "
                        f"will return empty; pass year='{api_year}'."
                    )
                return {
                    "latest_year": api_year,
                    "default_year": current,
                    "newer_data_available": newer,
                    "api_key": _api_key_status(),
                    "message": msg,
                }
    except Exception as e:
        # Don't silently eat the error: surface it so user knows probing failed
        return {
            "latest_year": current,
            "default_year": current,
            "newer_data_available": False,
            "api_key": _api_key_status(),
            "probe_error": str(e),
            "message": (
                f"Could not probe for the latest year (reason: {type(e).__name__}). "
                f"Defaulting to OEWS {current}. Rate limit, key issue, or BLS downtime "
                f"can all cause this. Call again later to check."
            ),
        }

    return {
        "latest_year": current,
        "default_year": current,
        "newer_data_available": False,
        "api_key": _api_key_status(),
        "message": (
            f"Probe returned no usable data; assuming OEWS {current} is "
            f"current. Next release expected ~April {int(current) + 2}."
        ),
    }


@mcp.tool(annotations={"title": "List Common SOC Codes", "readOnlyHint": True, "destructiveHint": False})
async def list_common_soc_codes() -> dict[str, Any]:
    """List common SOC code mappings for federal IT and professional services.

    Use these codes with get_wage_data() and other tools. SOC codes are
    6 digits without a dash (e.g., '151252' not '15-1252').

    For the full SOC list: https://www.bls.gov/oes/current/oes_stru.htm
    """
    return {"soc_codes": COMMON_SOC_CODES}


@mcp.tool(annotations={"title": "List Common Metros", "readOnlyHint": True, "destructiveHint": False})
async def list_common_metros() -> dict[str, Any]:
    """List common metro area MSA codes for wage lookups.

    Use these codes with get_wage_data(scope='metro', area_code=...).
    Pass the 5-digit MSA code (the tool auto-pads to 7 characters).

    For the full MSA list: https://www.bls.gov/oes/current/msa_def.htm
    """
    from .constants import COMMON_METROS
    return {"metros": COMMON_METROS}


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like get_wage_data(ocupation_code='15-1252')
    (with the real parameter soc_code) would succeed with the typo
    silently discarded, returning default-filter data with no indication
    of the problem. extra='forbid' surfaces typos immediately with
    "Extra inputs are not permitted".
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
