# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""GSA Per Diem Rates MCP server.

Federal travel lodging and M&IE rates for CONUS locations. Rates are set
annually per fiscal year (Oct 1 - Sep 30).

Authentication via PERDIEM_API_KEY environment variable. Falls back to
DEMO_KEY (~10 req/hr) if not set. Register free at api.data.gov/signup
for 1,000 req/hr.

These are maximum reimbursement ceilings, not actual hotel prices.
CONUS only. Non-foreign OCONUS (Alaska, Hawaii, territories) rates are
set by DoD (DTMO); foreign rates by the State Department.
"""

from __future__ import annotations

import json as _json
import os
import re
import urllib.parse
from datetime import date as _date
from typing import Any

import httpx
from mcp.server import MCPServer

from . import __version__
from ._pacing import FederalApiPacer
from .constants import BASE_URL, DEFAULT_TIMEOUT, USER_AGENT

mcp = MCPServer("gsa-perdiem", version=__version__)


# ---------------------------------------------------------------------------
# Defensive helpers
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict[str, Any]:
    """Return value if it's a dict, else {}."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Coerce value to list. Empty if None; single-item wrap if dict."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce to int, handling None/''/'null'/float-strings/non-parseable."""
    if value in (None, "", "null", "None"):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _safe_number(value: Any, default: float = 0.0) -> float:
    """Coerce to float; 0.0 for None/NaN/unparseable."""
    if value in (None, "", "null", "None"):
        return default
    try:
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):  # NaN/Inf
            return default
        return f
    except (TypeError, ValueError):
        return default


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(f"{field} exceeds maximum of {hi}. Got {value}.")
    return value


def _current_fiscal_year() -> int:
    """US federal FY runs Oct 1 - Sep 30. FY2026 = 2025-10-01 through 2026-09-30."""
    today = _date.today()
    return today.year + 1 if today.month >= 10 else today.year


def _validate_fiscal_year(value: Any, *, field: str = "fiscal_year") -> int:
    """Allow FY2020 through next-FY (for planning).

    Live-verified floor: the rates endpoints return empty for FY2015-2019
    (FY2020 is the earliest that serves data), so years below 2020 are
    rejected instead of producing an unhelpful "No rates found".
    """
    if value is None:
        return _current_fiscal_year()
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an int year like 2026, not bool.")
    try:
        fy = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an int year like 2026. Got {value!r}.") from exc
    current = _current_fiscal_year()
    lo = 2020
    hi = current + 1
    if fy < lo or fy > hi:
        raise ValueError(
            f"{field}={fy} is out of range. GSA Per Diem data covers "
            f"FY{lo} through FY{hi} (current FY is {current})."
        )
    return fy


# USPS 2-letter state codes plus DC and territories. GSA Per Diem covers
# CONUS (50 states + DC) plus some insular areas.
_USPS_STATES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY",
    # Territories (OCONUS; accepted so tools can explain, not error)
    "AS", "GU", "MP", "PR", "VI",
})

# GSA CONUS per diem does not cover these. Non-foreign OCONUS rates
# (AK, HI, territories) are set by DoD (DTMO); foreign by State Dept.
# The API accepts these codes but returns empty rate sets, which without
# this guard reads as "standard CONUS rate applies", a real IGCE trap.
_OCONUS_STATES = frozenset({"AK", "HI", "AS", "GU", "MP", "PR", "VI"})

_OCONUS_NOTE = (
    "GSA per diem covers CONUS only. Rates for Alaska, Hawaii, and the "
    "territories (non-foreign OCONUS) are set by DoD's Defense Travel "
    "Management Office at travel.dod.mil; foreign rates by the State "
    "Department at aoprals.state.gov. Do NOT apply the CONUS standard "
    "rate to these locations."
)


def _validate_state(value: Any, *, field: str = "state") -> str:
    if value is None:
        raise ValueError(f"{field} is required.")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a 2-letter USPS code. Got {type(value).__name__}.")
    s = value.strip().upper()
    if len(s) != 2 or not s.isalpha():
        raise ValueError(
            f"{field} must be a 2-letter USPS code (e.g., 'DC', 'VA'). Got {value!r}."
        )
    if s not in _USPS_STATES:
        raise ValueError(
            f"{field}={value!r} is not a valid USPS state/territory code. "
            f"Common codes: AL, AK, AZ, AR, CA, CO, CT, DC, ..."
        )
    return s


_ZIP5_RE = re.compile(r"^\d{5}$")


def _validate_zip(value: Any, *, field: str = "zip_code") -> str:
    if value is None:
        raise ValueError(f"{field} is required.")
    if not isinstance(value, str):
        value = str(value)
    s = value.strip()
    # Accept ZIP+4 and strip to 5-digit prefix
    if "-" in s:
        s = s.split("-", 1)[0].strip()
    if not _ZIP5_RE.match(s):
        raise ValueError(
            f"{field} must be a 5-digit US ZIP (ZIP+4 also accepted, e.g., '02101' "
            f"or '02101-1234'). Got {value!r}."
        )
    return s


_CITY_INVALID_CHARS_RE = re.compile(r"[\x00-\x1f\\]")


def _validate_city(value: Any, *, field: str = "city") -> str:
    if value is None:
        raise ValueError(f"{field} is required.")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string. Got {type(value).__name__}.")
    # Check raw value for control chars before stripping (strip() eats \n, \r, \t)
    if _CITY_INVALID_CHARS_RE.search(value):
        raise ValueError(
            f"{field}={value!r} contains control characters or backslashes. "
            f"Use plain city names like 'Boston' or 'Saint Louis'."
        )
    # GSA publishes composite NSA names like "Boston / Cambridge"; users
    # paste them verbatim. Treat forward slashes as separators, not errors.
    value = value.replace("/", " ")
    s = re.sub(r"\s+", " ", value).strip()
    if not s:
        raise ValueError(f"{field} cannot be empty or whitespace.")
    if len(s) > 100:
        raise ValueError(f"{field} exceeds 100 chars. Got {len(s)}.")
    # Reject path-traversal sequences. Slashes were replaced with spaces
    # above and the URL encoder never emits raw slashes, but '..' alone is
    # still worth blocking.
    if ".." in s:
        raise ValueError(
            f"{field}={value!r} contains '..' which is not a valid city name."
        )
    return s


_MONTH_SHORTS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH_FULL = ("January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December")
_MONTH_LOOKUP = {m.lower(): m for m in _MONTH_SHORTS}
_MONTH_LOOKUP.update({full.lower(): _MONTH_SHORTS[i] for i, full in enumerate(_MONTH_FULL)})


def _validate_travel_month(value: Any, *, field: str = "travel_month") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a month name like 'Jan' or 'January'.")
    s = value.strip()
    if not s:
        return None
    # Exact 3-letter abbreviation or exact full name, case-insensitive.
    # Prefix matching is deliberately NOT done: it silently accepted any
    # word whose first three letters spelled a month ("Mayhem" -> May).
    month = _MONTH_LOOKUP.get(s.lower())
    if month is None:
        raise ValueError(
            f"{field}={value!r} must be an exact month: 'Jan'-'Dec' or "
            f"'January'-'December' (case-insensitive)."
        )
    return month


_HTML_MARK_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
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


def _clean_error_body(text: Any, api_key: str | None = None) -> str:
    if text is None:
        return "(empty body)"
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            text = repr(text)
    if not isinstance(text, str):
        text = str(text)
    text = _redact_sensitive_text(text, api_key)
    if not _HTML_MARK_RE.search(text):
        return text[:400]
    pieces: list[str] = []
    title = _TITLE_RE.search(text)
    if title:
        pieces.append(re.sub(r"\s+", " ", title.group(1)).strip())
    h1 = _H1_RE.search(text)
    if h1:
        h1_text = re.sub(r"\s+", " ", h1.group(1)).strip()
        if h1_text and (not pieces or h1_text != pieces[0]):
            pieces.append(h1_text)
    return " - ".join(pieces) if pieces else "upstream returned HTML page"


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get("PERDIEM_API_KEY", "").strip() or "DEMO_KEY"


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or getattr(_client, "is_closed", False):
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _pacer(api_key: str) -> FederalApiPacer:
    return FederalApiPacer(
        bucket="api.data.gov",
        default_interval=4.0,
        credential=api_key,
    )


def _format_error(status: int, body: Any, api_key: str | None = None) -> str:
    cleaned = _clean_error_body(body, api_key)
    if status == 403:
        return (
            "HTTP 403: API key rejected or missing. "
            "Set PERDIEM_API_KEY env var, or the server will use DEMO_KEY "
            "(~10 req/hr). Register free at https://api.data.gov/signup/ "
            "for 1,000 req/hr."
        )
    if status == 429:
        return (
            "HTTP 429: Rate limited. DEMO_KEY allows ~10 req/hr; set "
            "PERDIEM_API_KEY with a real key (1,000 req/hr). "
            "Register free at https://api.data.gov/signup/."
        )
    if status == 500:
        return (
            f"HTTP 500: GSA Per Diem API server error. This often happens with "
            f"non-ASCII characters, special characters, or unusual whitespace in "
            f"city names. Use standard English city names. Response: {cleaned}"
        )
    if status == 404:
        return (
            f"HTTP 404: Endpoint not found. If you passed a city with '..' or a "
            f"slash, it may have been rejected by the API router. Response: {cleaned}"
        )
    return f"HTTP {status}: {cleaned}"


async def _get(path: str) -> Any:
    """GET helper with API key injection. Returns parsed JSON."""
    key = _get_api_key()
    encoded_key = urllib.parse.quote(key, safe="-")
    sep = "&" if "?" in path else "?"
    url = f"{BASE_URL}/{path}{sep}api_key={encoded_key}"
    try:
        async with _pacer(key).request_slot() as pacing:
            r = await _get_client().get(url)
            pacing.observe_response(r)
            pacing.raise_if_rate_limited(
                r,
                service="GSA Per Diem",
                guidance=_format_error(r.status_code, r.text, key),
            )
    except httpx.RequestError as e:
        safe_error = _redact_sensitive_text(str(e), key)
        raise RuntimeError(
            f"Network error calling GSA Per Diem API: {safe_error}"
        ) from e
    if r.status_code >= 400:
        raise RuntimeError(_format_error(r.status_code, r.text, key))
    try:
        return _redact_sensitive_payload(r.json(), key)
    except (ValueError, _json.JSONDecodeError) as e:
        preview = _clean_error_body(r.text or "(empty body)", key)[:200]
        ct = r.headers.get("content-type", "?")
        raise RuntimeError(
            f"GSA Per Diem returned a non-JSON response (status {r.status_code}, "
            f"content-type={ct!r}): {preview}"
        ) from e


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _parse_rate_entry(entry: Any) -> dict[str, Any]:
    """Parse one rate entry from the API response.

    Defensive against None entry, None months, single-dict month collapse,
    None/string values, missing keys.
    """
    entry = _safe_dict(entry)
    months_raw = _as_list(_safe_dict(entry.get("months")).get("month"))
    months: dict[str, int] = {}
    months_without_data: list[str] = []
    for m in months_raw:
        m = _safe_dict(m)
        short = m.get("short")
        if not isinstance(short, str) or not short:
            continue
        # A null or unparseable value must NOT become $0: it would poison
        # lodging_min, flip has_seasonal_variation, and price lodging at $0
        # downstream. Track it as missing instead.
        value = _safe_int(m.get("value"), default=0)
        if value > 0:
            months[short] = value
        else:
            months_without_data.append(short)

    city = entry.get("city") or ""
    if not isinstance(city, str):
        city = str(city) if city is not None else ""

    # The API uses the literal string "Standard Rate" for the standard-rate row.
    # `standardRate` field is unreliable (always "false"), so we match by name.
    is_standard = city.strip().lower() == "standard rate"

    lodging_values = list(months.values()) if months else []
    lodging_min = min(lodging_values) if lodging_values else 0
    lodging_max = max(lodging_values) if lodging_values else 0

    county = entry.get("county")
    if not isinstance(county, str) or not county:
        county = "N/A"

    meals = _safe_int(entry.get("meals"), default=0)

    out = {
        "city": city or None,
        "county": county,
        "meals": meals,
        "is_standard_rate": is_standard,
        "lodging_by_month": months,
        "lodging_min": lodging_min,
        "lodging_max": lodging_max,
        "has_seasonal_variation": bool(lodging_values) and lodging_min != lodging_max,
        "has_monthly_data": bool(months),
    }
    if months_without_data:
        out["months_without_data"] = months_without_data
    return out


def _normalize_for_match(s: str) -> str:
    """Normalize a city string for matching: lowercase, strip common punctuation
    (including the slashes GSA uses in composite NSA names), collapse
    whitespace. Handles ASCII and typographic apostrophes."""
    s = s.lower()
    for ch in ("'", "\u2019", "\u2018", ".", ",", "-", "/"):
        s = s.replace(ch, " ")
    return re.sub(r"\s+", " ", s).strip()


def _select_best_rate(
    response: Any,
    query_city: str | None = None,
) -> dict[str, Any] | None:
    """Select the best matching rate from an API response.

    Priority (when query_city given):
      1. Exact city match (after normalization)
      2. Composite name match ("Boston" -> "Boston / Cambridge")
      3. API-resolved NSA, match_type='api_resolved': the city endpoint does
         city-to-county-to-NSA resolution server-side, so a response with
         NSA rows and NO Standard Rate row means GSA resolved the query to
         those rate areas even though no name matches (live-verified:
         Washington/DC -> "District of Columbia", McLean/VA -> DC NSA,
         Penasco/NM -> Taos). Among several rows, prefer the one whose
         county mentions the query; other rows are listed in
         `other_candidates` so nothing is silently discarded.
      4. Standard Rate with match_type='standard_fallback': the response
         carries a Standard Rate row, meaning the query fell through to the
         state-wide default (unlisted city).

    Without query_city: returns first NSA, else first entry.

    Defensive against None response, list response, malformed rates.
    Adds `match_type` to the returned dict so callers can detect when the
    query didn't match exactly.
    """
    response = _safe_dict(response)
    rates = _as_list(response.get("rates"))
    if not rates:
        return None
    first = _safe_dict(rates[0])
    raw_entries = _as_list(first.get("rate"))
    if not raw_entries:
        return None

    parsed = [_parse_rate_entry(e) for e in raw_entries]
    parsed = [p for p in parsed if p.get("city")]  # drop entries with no city
    if not parsed:
        return None

    def tag(rate: dict[str, Any], match_type: str) -> dict[str, Any]:
        out = dict(rate)
        out["match_type"] = match_type
        return out

    if query_city:
        q = _normalize_for_match(query_city)
        # Exact match
        exact = [p for p in parsed if p["city"] and _normalize_for_match(p["city"]) == q]
        if exact:
            return tag(exact[0], "exact")
        # Composite name match (e.g., "Boston" matches "Boston / Cambridge")
        composite = [
            p for p in parsed
            if p["city"]
            and q in _normalize_for_match(p["city"])
            and not p["is_standard_rate"]
        ]
        if composite:
            return tag(composite[0], "composite")

        standard = [p for p in parsed if p["is_standard_rate"]]
        nsa = [p for p in parsed if not p["is_standard_rate"]]

        # No Standard Rate row present: GSA resolved the query city to the
        # returned NSA(s). Trust the resolution instead of warning on it.
        if nsa and not standard:
            county_hits = [
                p for p in nsa
                if q and q in _normalize_for_match(str(p.get("county") or ""))
            ]
            chosen = county_hits[0] if county_hits else nsa[0]
            out = tag(chosen, "api_resolved")
            others = [p["city"] for p in nsa if p is not chosen]
            if others:
                out["other_candidates"] = others
            return out

        # Standard Rate row present and nothing matched: the query fell
        # through to the state-wide default rate.
        if standard:
            return tag(standard[0], "standard_fallback")
        return tag(parsed[0], "api_resolved")

    # No query_city: caller wants any representative rate.
    nsa = [p for p in parsed if not p["is_standard_rate"]]
    if nsa:
        return tag(nsa[0], "first_nsa")
    return tag(parsed[0], "standard_only")


def _normalize_city_for_url(city: str) -> str:
    """Normalize a city name for the GSA URL path.

    GSA's URL routing rejects apostrophes and some hyphens. We replace them
    with spaces; URL encoding then turns those into %20. We do NOT preserve
    slashes -- they're encoded so path traversal is impossible.
    """
    # Apostrophe / hyphen become spaces (GSA quirk)
    s = city.replace("'", " ").replace("\u2019", " ").replace("-", " ")
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    # safe='' encodes /, ., :, everything except unreserved chars.
    return urllib.parse.quote(s, safe="")


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Lookup City Per Diem", "readOnlyHint": True, "destructiveHint": False})
async def lookup_city_perdiem(
    city: str,
    state: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Look up federal per diem rates for a city and state.

    Returns lodging rates (monthly breakdown for seasonal locations) and
    M&IE (meals and incidental expenses) for the specified fiscal year.

    state: 2-letter USPS code (e.g., 'DC', 'VA', 'MD', 'CA').
    fiscal_year: defaults to current FY. FY runs Oct 1 - Sep 30, so
    FY2026 = 2025-10-01 through 2026-09-30.

    The city endpoint resolves cities to their county's rate area
    server-side, so the matched NSA name can legitimately differ from the
    query (Washington -> 'District of Columbia', Penasco -> 'Taos').
    Selection order:
    1. Exact city name match
    2. Composite NSA name containing the city (e.g., 'Boston' matches 'Boston / Cambridge')
    3. API-resolved rate area (no Standard Rate row in the response)
    4. Standard Rate fallback (query fell through to the state default)

    Apostrophes, hyphens, and slashes in city names are auto-replaced with
    spaces (GSA API quirk). Keep periods for 'St.' prefix cities (St. Louis).

    For DC: query city='Washington', state='DC'.
    CONUS only: AK, HI, and territories return a pointer to DoD/State rates.
    """
    city_clean = _validate_city(city, field="city")
    state_upper = _validate_state(state, field="state")
    year = _validate_fiscal_year(fiscal_year, field="fiscal_year")

    if state_upper in _OCONUS_STATES:
        return {
            "query": {"city": city_clean, "state": state_upper, "fiscal_year": year},
            "oconus": True,
            "error": _OCONUS_NOTE,
        }

    city_encoded = _normalize_city_for_url(city_clean)
    response = await _get(f"city/{city_encoded}/state/{state_upper}/year/{year}")
    best = _select_best_rate(response, query_city=city_clean)

    if not best:
        return {
            "query": {"city": city_clean, "state": state_upper, "fiscal_year": year},
            "error": (
                f"No rates found for {city_clean}, {state_upper} in FY{year}."
                + _no_rates_hint(year)
            ),
        }

    out = {
        "query": {"city": city_clean, "state": state_upper, "fiscal_year": year},
        "matched_city": best["city"],
        "match_type": best.get("match_type", "exact"),
        "match_note": _match_note(best.get("match_type"), city_clean, best),
        "county": best["county"],
        "is_standard_rate": best["is_standard_rate"],
        "lodging_by_month": best["lodging_by_month"],
        "lodging_range": _format_lodging_range(best),
        "mie_daily": best["meals"],
        "mie_first_last_day": round(best["meals"] * 0.75, 2),
        "max_daily_total": best["lodging_max"] + best["meals"],
        "has_monthly_data": best["has_monthly_data"],
    }
    if best.get("other_candidates"):
        out["other_candidates"] = best["other_candidates"]
    if best.get("months_without_data"):
        out["months_without_data"] = best["months_without_data"]
    return out


def _match_note(
    match_type: str | None,
    query_city: str,
    best: dict[str, Any] | None = None,
) -> str | None:
    """Human-readable note explaining non-exact matches."""
    if match_type in (None, "exact"):
        return None
    if match_type == "composite":
        return f"{query_city!r} is part of a composite NSA name."
    if match_type == "standard_fallback":
        return (
            f"{query_city!r} is not a listed NSA for this state. "
            f"Returning the Standard Rate, which applies to all non-NSA "
            f"locations in this state."
        )
    if match_type == "api_resolved":
        best = best or {}
        note = (
            f"GSA resolved {query_city!r} to the {best.get('city')!r} rate "
            f"area (county: {best.get('county')}). This is the API's own "
            f"city-to-county resolution, not a name-match failure."
        )
        others = best.get("other_candidates")
        if others:
            note += (
                f" Other rate areas in the response: {others}. If the "
                f"destination county is ambiguous, verify with "
                f"lookup_zip_perdiem."
            )
        return note
    return None


def _no_rates_hint(year: int) -> str:
    """Extra context for empty results when querying the upcoming FY."""
    if year > _current_fiscal_year():
        return (
            f" FY{year} rates may simply not be published yet; GSA posts "
            f"new-FY rates in late August."
        )
    return ""


def _format_lodging_range(rate: dict[str, Any]) -> str:
    lo = rate.get("lodging_min", 0)
    hi = rate.get("lodging_max", 0)
    if not rate.get("has_monthly_data"):
        return "no monthly lodging data available"
    if rate.get("has_seasonal_variation"):
        return f"${lo}-${hi}/night"
    return f"${lo}/night"


@mcp.tool(annotations={"title": "Lookup ZIP Per Diem", "readOnlyHint": True, "destructiveHint": False})
async def lookup_zip_perdiem(
    zip_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Look up federal per diem rates by ZIP code.

    May return multiple entries (NSA + standard rate). This tool auto-selects
    the NSA rate over the standard rate.

    Useful when the exact city name is uncertain but the ZIP is known.
    Accepts 5-digit ZIPs or ZIP+4 (e.g., '02101' or '02101-1234').
    """
    zip5 = _validate_zip(zip_code, field="zip_code")
    year = _validate_fiscal_year(fiscal_year, field="fiscal_year")

    response = await _get(f"zip/{zip5}/year/{year}")
    best = _select_best_rate(response)

    if not best:
        return {
            "zip_code": zip5,
            "fiscal_year": year,
            "error": (
                "No rates found for this ZIP."
                + _no_rates_hint(year)
                + " If this ZIP is in Alaska, Hawaii, or a territory: "
                + _OCONUS_NOTE
            ),
        }

    return {
        "zip_code": zip5,
        "fiscal_year": year,
        "matched_city": best["city"],
        "match_type": best.get("match_type"),
        "county": best["county"],
        "is_standard_rate": best["is_standard_rate"],
        "lodging_range": _format_lodging_range(best),
        "mie_daily": best["meals"],
        "has_monthly_data": best["has_monthly_data"],
    }


@mcp.tool(annotations={"title": "Lookup State Rates", "readOnlyHint": True, "destructiveHint": False})
async def lookup_state_rates(
    state: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get all Non-Standard Area (NSA) per diem rates for a state.

    Returns every city/county with rates above the standard rate in that
    state. Useful for comparing rates across cities within a state or for
    building a travel IGCE with multiple destinations.

    CONUS only: AK, HI, and territories return a pointer to DoD/State rates
    instead of an empty list that would falsely imply the standard CONUS
    rate applies there.
    """
    state_upper = _validate_state(state, field="state")
    year = _validate_fiscal_year(fiscal_year, field="fiscal_year")

    if state_upper in _OCONUS_STATES:
        return {
            "state": state_upper,
            "fiscal_year": year,
            "oconus": True,
            "error": _OCONUS_NOTE,
        }

    response = await _get(f"state/{state_upper}/year/{year}")
    response = _safe_dict(response)
    rates = _as_list(response.get("rates"))
    if not rates:
        return {
            "state": state_upper,
            "fiscal_year": year,
            "nsa_count": 0,
            "rates": [],
            "note": (
                f"The API returned no rate data for {state_upper} in FY{year}."
                + _no_rates_hint(year)
            ),
        }
    first = _safe_dict(rates[0])
    raw_entries = _as_list(first.get("rate"))
    parsed = [_parse_rate_entry(e) for e in raw_entries]
    parsed = [p for p in parsed if p.get("city")]
    nsa_only = [p for p in parsed if not p["is_standard_rate"]]

    return {
        "state": state_upper,
        "fiscal_year": year,
        "nsa_count": len(nsa_only),
        "rates": [
            {
                "city": r["city"],
                "county": r["county"],
                "lodging_max": r["lodging_max"],
                "lodging_min": r["lodging_min"],
                "mie": r["meals"],
                "max_daily": r["lodging_max"] + r["meals"],
                "seasonal": r["has_seasonal_variation"],
            }
            for r in nsa_only
        ],
    }


@mcp.tool(annotations={"title": "Get M&IE Breakdown", "readOnlyHint": True, "destructiveHint": False})
async def get_mie_breakdown(fiscal_year: int | None = None) -> dict[str, Any]:
    """Get the M&IE (meals and incidental expenses) tier breakdown table.

    Returns all M&IE tiers with breakfast, lunch, dinner, incidental, and
    first/last day (75%) amounts. Use this to show the meal component
    breakdown when presenting per diem estimates.

    M&IE does NOT vary seasonally (unlike lodging). The tier is set per
    location and applies year-round.
    """
    year = _validate_fiscal_year(fiscal_year, field="fiscal_year")
    data = await _get(f"conus/mie/{year}")

    if isinstance(data, list):
        tiers_raw = data
    else:
        data_d = _safe_dict(data)
        tiers_raw = data_d.get("mieData")
        if tiers_raw is None:
            tiers_raw = data_d.get("rates")
    tiers_raw = _as_list(tiers_raw)

    out: list[dict[str, Any]] = []
    for t in tiers_raw:
        t = _safe_dict(t)
        total = _safe_number(t.get("total"))
        first_last = t.get("FirstLastDay")
        if first_last is None:
            first_last = round(total * 0.75, 2) if total else 0.0
        else:
            first_last = _safe_number(first_last)
        out.append({
            "total": total,
            "breakfast": _safe_number(t.get("breakfast")),
            "lunch": _safe_number(t.get("lunch")),
            "dinner": _safe_number(t.get("dinner")),
            "incidental": _safe_number(t.get("incidental")),
            "first_last_day_75pct": first_last,
        })

    return {"fiscal_year": year, "tiers": out}


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Estimate Travel Cost", "readOnlyHint": True, "destructiveHint": False})
async def estimate_travel_cost(
    city: str,
    state: str,
    num_nights: int,
    travel_month: str | None = None,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Estimate total per diem cost for a trip.

    Calculates lodging + M&IE for the specified number of nights.
    First and last travel days use 75% M&IE per 41 CFR 301-11.101.

    travel_month: 3-letter abbreviation (Jan, Feb, ..., Dec). If omitted,
    uses the max monthly lodging rate (conservative estimate for IGCE).

    Does NOT include airfare or ground transportation. Add those separately.

    Formula:
    - Lodging = nightly_rate * num_nights
    - M&IE = full_day_rate * (travel_days - 2) + first/last_day_rate * 2
    - Travel days = num_nights + 1

    num_nights bounded 1-365. A single trip longer than a year is
    unlikely to be covered by per diem.
    """
    city_clean = _validate_city(city, field="city")
    state_upper = _validate_state(state, field="state")
    num_nights = _clamp(int(num_nights), field="num_nights", lo=1, hi=365)
    year = _validate_fiscal_year(fiscal_year, field="fiscal_year")
    travel_month = _validate_travel_month(travel_month, field="travel_month")

    if state_upper in _OCONUS_STATES:
        return {
            "query": {"city": city_clean, "state": state_upper, "fiscal_year": year},
            "oconus": True,
            "error": _OCONUS_NOTE,
        }

    city_encoded = _normalize_city_for_url(city_clean)
    response = await _get(f"city/{city_encoded}/state/{state_upper}/year/{year}")
    best = _select_best_rate(response, query_city=city_clean)

    if not best:
        return {
            "query": {"city": city_clean, "state": state_upper, "fiscal_year": year},
            "error": (
                f"No rates found for {city_clean}, {state_upper} in FY{year}."
                + _no_rates_hint(year)
            ),
        }

    month_fallback_note: str | None = None
    if travel_month and travel_month in best["lodging_by_month"]:
        nightly = best["lodging_by_month"][travel_month]
        rate_month = travel_month
    else:
        nightly = best["lodging_max"]
        rate_month = "MAX"
        if travel_month:
            month_fallback_note = (
                f"No published lodging rate for {travel_month}; used the "
                f"max monthly rate instead."
            )

    daily_mie = best["meals"]
    # A $0 lodging or M&IE rate is missing data, not a real rate. Refuse to
    # produce a dollar estimate that silently prices a component at zero.
    if nightly <= 0 or daily_mie <= 0:
        return {
            "query": {"city": city_clean, "state": state_upper, "fiscal_year": year},
            "matched_city": best["city"],
            "match_type": best.get("match_type"),
            "error": (
                f"Rate data for {best['city']!r} is incomplete "
                f"(nightly lodging={nightly}, M&IE={daily_mie}); refusing to "
                f"build an estimate that prices a component at $0. Try "
                f"lookup_state_rates or a different fiscal year."
                + _no_rates_hint(year)
            ),
        }

    lodging_total = nightly * num_nights
    travel_days = num_nights + 1
    first_last_mie = round(daily_mie * 0.75, 2)

    if travel_days <= 1:
        mie_total = first_last_mie
    elif travel_days == 2:
        mie_total = first_last_mie * 2
    else:
        mie_total = (daily_mie * (travel_days - 2)) + (first_last_mie * 2)

    out = {
        "destination": best["city"],
        "state": state_upper,
        "fiscal_year": year,
        "match_type": best.get("match_type"),
        "match_note": _match_note(best.get("match_type"), city_clean, best),
        "num_nights": num_nights,
        "travel_days": travel_days,
        "nightly_lodging": nightly,
        "lodging_total": lodging_total,
        "daily_mie": daily_mie,
        "first_last_day_mie": first_last_mie,
        "mie_total": round(mie_total, 2),
        "grand_total": round(lodging_total + mie_total, 2),
        "rate_month": rate_month,
        "_note": "Per diem only (lodging + M&IE). Airfare and ground transport not included.",
    }
    if month_fallback_note:
        out["month_fallback_note"] = month_fallback_note
    return out


_MAX_COMPARE_LOCATIONS = 25


@mcp.tool(annotations={"title": "Compare Locations", "readOnlyHint": True, "destructiveHint": False})
async def compare_locations(
    locations: list[dict[str, str]],
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Compare per diem rates across multiple locations.

    locations: list of {"city": "...", "state": "XX"} dicts, max 25 entries
    (DEMO_KEY limits you to ~10 req/hr so this is generous). Returns rates
    sorted by max daily total (highest first).

    Useful for travel IGCE development when comparing destination costs.
    """
    if not isinstance(locations, list) or not locations:
        raise ValueError("locations must be a non-empty list of {city, state} dicts.")
    if len(locations) > _MAX_COMPARE_LOCATIONS:
        raise ValueError(
            f"compare_locations accepts up to {_MAX_COMPARE_LOCATIONS} locations. "
            f"Got {len(locations)}. Batch your comparisons."
        )

    year = _validate_fiscal_year(fiscal_year, field="fiscal_year")
    results: list[dict[str, Any]] = []

    # Pre-validate everything first so we fail fast on bad input rather
    # than halfway through a set of network calls.
    prepared: list[tuple[str, str, str]] = []
    for i, loc in enumerate(locations):
        if not isinstance(loc, dict):
            raise ValueError(
                f"locations[{i}] must be a dict with 'city' and 'state'. Got {type(loc).__name__}."
            )
        try:
            city_clean = _validate_city(loc.get("city"), field=f"locations[{i}].city")
            state_upper = _validate_state(loc.get("state"), field=f"locations[{i}].state")
        except ValueError as e:
            results.append({
                "location": f"{loc.get('city','?')}, {loc.get('state','?')}",
                "error": str(e),
            })
            continue
        prepared.append((city_clean, state_upper, _normalize_city_for_url(city_clean)))

    import asyncio
    for city_clean, state_upper, city_encoded in prepared:
        # Label rows by the QUERY, not the matched entry: labeling Arlington
        # by its matched NSA produced nonsense like "District of Columbia, VA".
        label = f"{city_clean}, {state_upper}"
        if state_upper in _OCONUS_STATES:
            results.append({"location": label, "oconus": True, "error": _OCONUS_NOTE})
            continue
        try:
            response = await _get(f"city/{city_encoded}/state/{state_upper}/year/{year}")
            best = _select_best_rate(response, query_city=city_clean)
            if best:
                results.append({
                    "location": label,
                    "matched_city": best["city"],
                    "match_type": best.get("match_type"),
                    "is_standard_rate": best["is_standard_rate"],
                    "lodging_max": best["lodging_max"],
                    "lodging_min": best["lodging_min"],
                    "mie": best["meals"],
                    "max_daily_total": best["lodging_max"] + best["meals"],
                    "seasonal": best["has_seasonal_variation"],
                })
            else:
                results.append({
                    "location": label,
                    "error": "no rates found" + _no_rates_hint(year),
                })
        except RuntimeError as e:
            results.append({
                "location": label,
                "error": str(e)[:200],
            })

    results.sort(key=lambda x: x.get("max_daily_total", 0), reverse=True)
    return {"fiscal_year": year, "locations": results}


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like lookup_city_perdiem(state_code='VA')
    (real param is `state`) would succeed with the typo discarded and
    run without the intended filter. extra='forbid' raises "Extra inputs
    are not permitted" on typos before any HTTP call.
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
    mcp.run()


if __name__ == "__main__":
    main()
