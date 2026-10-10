# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""USASpending.gov MCP server.

Provides access to federal contract, grant, loan, and award data from
USASpending.gov. No API key required.

All tools are read-only. The server wraps the USASpending REST API at
https://api.usaspending.gov with actionable error handling and sensible
defaults matching common federal acquisition workflows.
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import re
import time
from datetime import date, timedelta
from typing import Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from ._throughput import USASpendingPacer
from ._response_cache import DAY, HOUR, MINUTE, ResponseCache, cache_key
from .constants import (
    AWARD_TYPE_GROUPS,
    BASE_URL,
    DEFAULT_ASSISTANCE_FIELDS,
    DEFAULT_CONTRACT_FIELDS,
    DEFAULT_GRANT_FIELDS,
    DEFAULT_IDV_FIELDS,
    DEFAULT_LOAN_FIELDS,
    DEFAULT_TIMEOUT,
    USER_AGENT,
)

mcp = MCPServer("usaspending", version=__version__)

USASPENDING_TOOL_PROFILE_ENV = "USASPENDING_TOOL_PROFILE"
ACQUISITION_AGENT_TOOLS = frozenset(
    {
        "search_awards",
        "get_award_count",
        "spending_over_time",
        "spending_by_category",
        "get_award_detail",
        "get_transactions",
        "get_award_funding",
        "get_idv_children",
        "lookup_piid",
        "autocomplete_psc",
        "autocomplete_naics",
        "list_toptier_agencies",
        "get_agency_overview",
        "get_agency_awards",
        "get_naics_details",
        "get_psc_filter_tree",
        "search_subawards",
        "search_recipients",
        "get_recipient_profile",
        "awards_last_updated",
    }
)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
_pacer = USASpendingPacer()
# Hosted only (MCP_RESPONSE_CACHE=1); see _cache_seconds for how long.
_cache = ResponseCache(max_bytes=48 * 1024 * 1024, max_entry_bytes=4 * 1024 * 1024)


_LAST_UPDATED = "/api/v2/awards/last_updated/"
# USAspending's load date and when it was read; see _data_version.
_version: tuple[str | None, float] = (None, float("-inf"))
_version_lock: asyncio.Lock | None = None


def _cache_seconds(path: str, versioned: bool = False) -> float:
    """How long a hosted answer is kept, by endpoint. USAspending reloads nightly.

    An answer filed under USAspending's current load date (``versioned``) is kept
    a full day: the next nightly load changes the date, which retires it, so it
    is never served from an older load. Without the date, the shorter times apply.
    """
    if path.startswith(("/api/v2/references/", "/api/v2/autocomplete/")) or path == "/api/v2/recipient/state/":
        return DAY  # reference lists, autocompletes, the state list
    if path == _LAST_UPDATED:
        return 15 * MINUTE
    if versioned:
        return DAY
    if path.startswith(("/api/v2/search/", "/api/v2/subawards/", "/api/v2/awards/count/")) or path in (
        "/api/v2/recipient/", "/api/v2/federal_accounts/",
    ):
        return HOUR  # searches, totals and counts
    return 6 * HOUR  # award, IDV, recipient, agency and federal-account details


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=DEFAULT_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
        )
    return _client


_HTML_ERROR_RE = re.compile(r"<!doctype html>.*?</html>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML bodies from upstream error responses for clean messages."""
    if "<!doctype html>" in text.lower() or "<html" in text.lower():
        # Try to extract a <title> or <h1> for context
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
        pieces = []
        if title_match:
            pieces.append(title_match.group(1).strip())
        if h1_match and (not title_match or h1_match.group(1).strip() != title_match.group(1).strip()):
            pieces.append(h1_match.group(1).strip())
        return " - ".join(pieces) if pieces else "upstream returned HTML error page"
    return text[:500]


def _format_http_error(e: httpx.HTTPStatusError) -> str:
    """Translate common USASpending API errors into actionable messages."""
    status = e.response.status_code
    try:
        body = e.response.json()
        detail = body.get("detail") or body.get("messages") or body
    except Exception:
        detail = _clean_error_body(e.response.text)

    detail_str = str(detail)
    # Also clean detail_str if it somehow contains HTML
    if "<!doctype html>" in detail_str.lower() or "<html" in detail_str.lower():
        detail = _clean_error_body(detail_str)
        detail_str = str(detail)

    # Known error patterns with actionable guidance
    if status == 422 and "award_type_codes" in detail_str and "one group" in detail_str:
        return (
            "HTTP 422: award_type_codes mixed across groups. "
            "Contracts [A,B,C,D], IDVs [IDV_*], Grants [02-05], "
            "Loans [07,08], Direct Payments [06,10], Other [09,11,-1] "
            "must each be used in separate requests. "
            f"API response: {detail}"
        )
    if status == 422 and "psc_codes" in detail_str:
        return (
            "HTTP 422: psc_codes filter malformed. "
            "Use a simple list like ['R499','D399']. "
            "Do not include an empty 'exclude' key. "
            f"API response: {detail}"
        )
    if status == 422 and "limit" in detail_str:
        return (
            "HTTP 422: limit exceeds maximum. "
            "Search endpoints max 100; transactions endpoint max 5000. "
            "Paginate with the 'page' parameter. "
            f"API response: {detail}"
        )
    if status == 400 and "Sort value not found in requested fields" in detail_str:
        return (
            "HTTP 400: sort field not present in fields list. "
            "The field you're sorting by must also appear in the fields array. "
            f"API response: {detail}"
        )
    if status == 400 and "keywords" in detail_str:
        return (
            "HTTP 400: empty keywords array. "
            "Omit the 'keywords' filter entirely rather than passing an empty list. "
            f"API response: {detail}"
        )
    if status == 400 and "Loan Award mappings" in detail_str:
        return (
            "HTTP 400: loan search used 'Award Amount' field. "
            "For loans (codes 07, 08) use 'Loan Value' instead. "
            f"API response: {detail}"
        )
    if status == 404:
        # Tailor the hint to the endpoint family. The award-specific hint used
        # to fire on EVERY 404 (a federal-account 404 told callers to check
        # generated_internal_id), which was misleading. Round 10 audit finding.
        try:
            req_path = str(e.request.url.path)
        except Exception:
            req_path = ""
        if "/awards/" in req_path or "/idvs/" in req_path:
            hint = (
                "Verify the generated_internal_id is correct "
                "(find it via search_awards)."
            )
        else:
            hint = (
                "Verify the identifier in the request exists (agency code, "
                "federal account number, recipient id, FIPS code, etc.)."
            )
        return f"HTTP 404: resource not found. {hint} API response: {detail}"
    if status == 429:
        return (
            "HTTP 429: rate limited. "
            "Add 0.3s delay between batch requests, or reduce concurrency. "
            f"API response: {detail}"
        )

    return f"HTTP {status}: {detail}"


def _ensure_dict_response(data: Any, *, path: str) -> dict[str, Any]:
    """Guarantee a dict return type. USASpending always responds with a
    JSON object for every endpoint this MCP uses; anything else is a
    transport/infrastructure problem that should surface clearly rather
    than leak a None / list / int into the tool output.
    """
    if isinstance(data, dict):
        return data
    if data is None:
        raise RuntimeError(
            f"USASpending returned an empty body at {path!r}. This usually "
            f"means a CDN / proxy issue rather than a real empty result; "
            f"retry in a few seconds."
        )
    raise RuntimeError(
        f"USASpending returned an unexpected {type(data).__name__} at "
        f"{path!r} (expected JSON object). First 200 chars: {str(data)[:200]!r}"
    )


async def _send(
    method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None,
) -> bytes:
    """One paced USAspending request; only cache misses get here."""
    async with _pacer.request_slot() as pacing:
        if method == "POST":
            r = await _get_client().post(path, json=body)
        elif params is None:
            r = await _get_client().get(path)
        else:
            r = await _get_client().get(path, params=params)
        pacing.observe_response(r)
        if getattr(r, "status_code", 200) == 429:
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                pacing.raise_if_rate_limited(
                    r,
                    service="USASpending",
                    guidance=_format_http_error(exc),
                )
    r.raise_for_status()
    return r.content


async def _data_version() -> str | None:
    """USAspending's last load date, read at most every 15 minutes (hosted only).

    Hosted answers are filed under it, so the nightly load retires every answer
    kept from the previous load. It is read straight from USAspending, outside
    the cache, so it never counts as a hit or miss. If it can't be read, answers
    fall back to the shorter times without it, and it is read again after a minute.
    """
    global _version, _version_lock
    if not _cache.enabled:
        return None
    value, read_at = _version
    if time.monotonic() - read_at < 15 * MINUTE:
        return value
    if _version_lock is None:
        _version_lock = asyncio.Lock()
    async with _version_lock:
        value, read_at = _version
        if time.monotonic() - read_at < 15 * MINUTE:
            return value
        try:
            found = _json.loads(await _send("GET", _LAST_UPDATED, params={})).get("last_updated")
            value = found if isinstance(found, str) and found else None
            _version = (value, time.monotonic())
        except Exception:
            value = None
            _version = (None, time.monotonic() - 14 * MINUTE)
    return value


async def _cached(method: str, path: str, parse, *, params=None, body=None):
    """Send through the hosted cache, with actionable error translation."""
    version = None if path == _LAST_UPDATED else await _data_version()
    key = cache_key(method, path, params, body)
    if version:
        key = f"{version}|{key}"
    try:
        return await _cache.get_or_fetch(
            key, _cache_seconds(path, versioned=version is not None),
            lambda: _send(method, path, params=params, body=body), parse,
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_http_error(e)) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling USASpending: {e}") from e


async def _post(path: str, json: dict[str, Any]) -> dict[str, Any]:
    """POST helper with actionable error translation."""
    return await _cached(
        "POST", path, lambda content: _ensure_dict_response(_json.loads(content), path=path), body=json,
    )


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET helper with actionable error translation."""
    return await _cached(
        "GET", path, lambda content: _ensure_dict_response(_json.loads(content), path=path),
        params=params or {},
    )


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EARLIEST_SEARCH_DATE = "2007-10-01"


def _validate_date(value: str, field_name: str) -> str:
    """Validate YYYY-MM-DD format and parseability."""
    if not _DATE_RE.match(value):
        raise ValueError(
            f"{field_name} must be in YYYY-MM-DD format (e.g. '2026-01-15'). "
            f"Got {value!r}. ISO 8601 datetimes with timezones or 'YYYY/MM/DD' are rejected."
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}={value!r} is not a valid calendar date: {exc}") from exc
    return value


def _today() -> date:
    return date.today()


def _current_fiscal_year() -> int:
    """Federal fiscal year (Oct-Sep). FY2026 runs 2025-10-01 to 2026-09-30."""
    today = _today()
    return today.year + 1 if today.month >= 10 else today.year


_DOD_NAMES = {"department of defense", "dod", "097", "096", "usace",
              "corps of engineers - civil works",
              "u.s. army corps of engineers - civil program financing only"}
_DOD_LAG_DAYS = 90


def _dod_lag_note(window_end: date | str | None, *, agencies: tuple[str | None, ...] = (),
                  award_types: Any = "contracts") -> str | None:
    """A caveat when an answer covers DoD contract actions too recent to be published.

    DoD contract and IDV actions appear in USAspending 90 days after their
    action date, so the last three months of any window look nearly empty
    for DoD (FY2026 Jul-Sep: $8.8B / $0.02B / $0.16B vs $27-72B a month
    earlier, seen 2026-10-10). Applies when the window reaches into those
    90 days, contracts or IDVs are in scope (or no award type was given),
    and DoD is named in either agency role, or no agency filter was given.
    """
    if window_end is None:
        return None
    if award_types not in (None, "contracts", "idvs", "all"):
        return None
    given = [a.strip().lower() for a in agencies if a and a.strip()]
    if given and not any(a in _DOD_NAMES or a == "097" for a in given):
        return None
    end = date.fromisoformat(window_end) if isinstance(window_end, str) else window_end
    cutoff = _today() - timedelta(days=_DOD_LAG_DAYS)
    if end <= cutoff:
        return None
    available = (min(end, _today()) + timedelta(days=_DOD_LAG_DAYS)).isoformat()
    return (
        f"DoD and U.S. Army Corps of Engineers (USACE) contract and IDV actions are "
        f"published {_DOD_LAG_DAYS} days after the action date, so their actions after "
        f"{cutoff.isoformat()} are mostly missing here and any DoD/USACE "
        f"(or government-wide) total for this period is understated "
        f"until about {available}. Don't compare it with earlier full years yet."
    )


def _add_note(result: Any, note: str | None) -> Any:
    if note and isinstance(result, dict):
        result["data_note"] = note
    return result


def _agency_dod_lag_note(toptier_code: str, fy: int | str) -> str | None:
    """DoD (097) fiscal years whose last 90 days are not yet published."""
    if toptier_code not in ("097", "096"):
        return None
    return _dod_lag_note(date(int(fy), 9, 30), award_types=None)


def _window_end(start: str | None, end: str | None) -> str | None:
    """The end of a search window; open-ended and all-time searches include today."""
    if end:
        return end
    return _today().isoformat()


def _last_completed_fiscal_year() -> int:
    """The most recent fiscal year that has ended (FY2026 from 2026-10-01 on).

    Agency and state tools default to it. USAspending's own default is the
    current fiscal year, which for the first weeks after October 1 holds a
    few days of data (DoD showed $1,000,000 of contracts on 2026-10-10).
    """
    return _current_fiscal_year() - 1


def _echo_fiscal_year(
    result: Any, fy: int | str, *, defaulted: bool, key: str = "fiscal_year",
    param: str = "fiscal_year",
) -> Any:
    """Make every agency/state answer say which fiscal year it covers.

    Some endpoints echo the year, some (obligations_by_award_category,
    recipient/state) do not. When the caller gave no year, also say that the
    last completed fiscal year was used and how to ask for the current one.
    """
    if not isinstance(result, dict):
        return result
    if key not in result or result.get(key) in (None, ""):
        result[key] = int(fy) if str(fy).isdigit() else fy
    if defaulted:
        current = _current_fiscal_year()
        result["fiscal_year_note"] = (
            f"No {param} given, so this covers FY{fy}, the last completed federal "
            f"fiscal year (October {int(fy) - 1} through September {fy}). FY{current} "
            f"began October 1 and is only partly reported; pass {param}={current} "
            f"for it to date."
        )
    return result


def _clamp_limit(limit: int, *, cap: int, field: str = "limit") -> int:
    """Clamp a limit to valid bounds, raising on nonsense values."""
    if limit < 1:
        raise ValueError(f"{field} must be >= 1. Got {limit}.")
    if limit > cap:
        raise ValueError(
            f"{field} exceeds maximum of {cap}. Got {limit}. "
            f"Paginate with the 'page' parameter instead."
        )
    return limit


def _coerce_code_list(codes: list[Any] | None, field: str) -> list[str] | None:
    """Coerce a list of codes (int or str) to strings. Rejects empty arrays
    AND arrays where every entry is empty / whitespace-only."""
    if codes is None:
        return None
    if len(codes) == 0:
        raise ValueError(
            f"{field} was passed as an empty array. Omit the parameter instead of passing []."
        )
    cleaned = [str(c).strip() for c in codes if str(c).strip()]
    if not cleaned:
        raise ValueError(
            f"{field}={codes!r} contains only empty / whitespace strings. "
            f"Pass non-empty codes or omit the parameter."
        )
    return cleaned


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")


def _validate_no_control_chars(value: str | None, *, field: str) -> str | None:
    """Reject null bytes, newlines, tabs, and other control characters.

    USASpending's API either 500s on these (autocomplete, transactions) or
    silently accepts them (keyword search), which makes tool results confusing.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if _CONTROL_CHARS_RE.search(value):
        raise ValueError(
            f"{field}={value!r} contains control characters (null byte, newline, "
            f"tab, etc). Remove them and retry."
        )
    return value


def _validate_strings_no_control_chars(values: list[str] | None, *, field: str) -> None:
    """Apply _validate_no_control_chars to each entry in a list."""
    if values is None:
        return
    for i, v in enumerate(values):
        _validate_no_control_chars(v, field=f"{field}[{i}]")


# ---------------------------------------------------------------------------
# Filter construction helpers
# ---------------------------------------------------------------------------

# How a time window is applied (time_period[].date_type). Omitted, USAspending
# counts every award with activity in the window. Verified live 2026-10-10 on
# VA SDVOSB set-asides FY2026: default 11,797 contracts, new_awards_only
# 5,125 (awards first signed in the window).
DateType = Literal["action_date", "date_signed", "last_modified_date", "new_awards_only"]


def _build_filters(
    *,
    keywords: list[str] | None = None,
    award_type_codes: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    recipient_uei: str | None = None,
    award_ids: list[str | int] | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    date_type: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    def_codes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Build a USASpending filters object from flattened parameters."""
    filters: dict[str, Any] = {}

    if keywords is not None:
        if len(keywords) == 0:
            raise ValueError(
                "keywords was passed as an empty array. "
                "Omit the parameter instead of passing []."
            )
        # USASpending API requires each keyword to be at least 3 characters
        short = [k for k in keywords if len(k) < 3]
        if short:
            raise ValueError(
                f"USASpending requires keywords of at least 3 characters. "
                f"Too short: {short}. Use more specific terms."
            )
        filters["keywords"] = keywords
    if award_type_codes:
        filters["award_type_codes"] = award_type_codes

    agencies = []
    # Awarding agency: if subagency is specified, use a single subtier entry
    # with toptier_name context. Otherwise use the toptier alone.
    if awarding_subagency:
        entry: dict[str, Any] = {
            "type": "awarding",
            "tier": "subtier",
            "name": awarding_subagency,
        }
        if awarding_agency:
            entry["toptier_name"] = awarding_agency
        agencies.append(entry)
    elif awarding_agency:
        agencies.append({
            "type": "awarding",
            "tier": "toptier",
            "name": awarding_agency,
        })
    if funding_agency:
        agencies.append({
            "type": "funding",
            "tier": "toptier",
            "name": funding_agency,
        })
    if agencies:
        filters["agencies"] = agencies

    # recipient_search_text matches name, UEI, or DUNS. Do NOT send a UEI as
    # the API's recipient_id filter: that field expects a recipient hash
    # (UUID + -C/-R/-P suffix) and silently matches nothing for a UEI
    # (verified live 2026-08-16).
    recipient_terms: list[str] = []
    if recipient_name:
        recipient_terms.append(recipient_name)
    if recipient_uei:
        recipient_terms.append(recipient_uei.strip().upper())
    if recipient_terms:
        filters["recipient_search_text"] = recipient_terms
    coerced_award_ids = _coerce_code_list(award_ids, "award_ids")
    if coerced_award_ids:
        filters["award_ids"] = coerced_award_ids
    coerced_naics = _coerce_code_list(naics_codes, "naics_codes")
    if coerced_naics:
        filters["naics_codes"] = coerced_naics
    coerced_psc = _coerce_code_list(psc_codes, "psc_codes")
    if coerced_psc:
        filters["psc_codes"] = coerced_psc
    # These three code filters are case-sensitive upstream: lowercase values
    # return HTTP 200 with zero results (unlike psc_codes, which the API
    # rejects loudly). Uppercase them, same treatment as
    # place_of_performance_state. Verified live 2026-08-16.
    coerced_set_aside = _coerce_code_list(set_aside_type_codes, "set_aside_type_codes")
    if coerced_set_aside:
        filters["set_aside_type_codes"] = [c.upper() for c in coerced_set_aside]
    coerced_extent = _coerce_code_list(extent_competed_type_codes, "extent_competed_type_codes")
    if coerced_extent:
        filters["extent_competed_type_codes"] = [c.upper() for c in coerced_extent]
    coerced_pricing = _coerce_code_list(contract_pricing_type_codes, "contract_pricing_type_codes")
    if coerced_pricing:
        filters["contract_pricing_type_codes"] = [c.upper() for c in coerced_pricing]
    if time_period_start or time_period_end:
        start = _validate_date(time_period_start, "time_period_start") if time_period_start else _EARLIEST_SEARCH_DATE
        end = _validate_date(time_period_end, "time_period_end") if time_period_end else "2099-09-30"
        if start > end:
            raise ValueError(
                f"time_period_start ({start}) is after time_period_end ({end}). "
                f"Reverse the values or omit one."
            )
        period: dict[str, str] = {"start_date": start, "end_date": end}
        if date_type:
            period["date_type"] = date_type
        filters["time_period"] = [period]
    elif date_type:
        raise ValueError(
            f"date_type={date_type!r} needs a time window: pass time_period_start "
            f"and/or time_period_end (e.g. a fiscal year, 2025-10-01 to 2026-09-30)."
        )
    if award_amount_min is not None or award_amount_max is not None:
        if (
            award_amount_min is not None
            and award_amount_max is not None
            and award_amount_min > award_amount_max
        ):
            raise ValueError(
                f"award_amount_min ({award_amount_min}) is greater than "
                f"award_amount_max ({award_amount_max}). Reverse the values."
            )
        bounds: dict[str, float] = {}
        if award_amount_min is not None:
            bounds["lower_bound"] = award_amount_min
        if award_amount_max is not None:
            bounds["upper_bound"] = award_amount_max
        filters["award_amounts"] = [bounds]
    if place_of_performance_state:
        state = place_of_performance_state.strip().upper()
        if not re.match(r"^[A-Z]{2}$", state):
            raise ValueError(
                f"place_of_performance_state must be a 2-letter USPS code (e.g. 'MD'). "
                f"Got {place_of_performance_state!r}."
            )
        filters["place_of_performance_locations"] = [{
            "country": "USA",
            "state": state,
        }]
    coerced_def = _coerce_code_list(def_codes, "def_codes")
    if coerced_def:
        filters["def_codes"] = coerced_def

    return filters


def _resolve_award_type(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"]
) -> list[str]:
    """Resolve an award type group name to its list of codes."""
    if award_type not in AWARD_TYPE_GROUPS:
        raise ValueError(
            f"Unknown award_type '{award_type}'. "
            f"Valid: {list(AWARD_TYPE_GROUPS.keys())}"
        )
    return AWARD_TYPE_GROUPS[award_type]


# ---------------------------------------------------------------------------
# Search tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Awards", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def search_awards(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    date_type: DateType | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    award_ids: list[str | int] | None = None,
    def_codes: list[str | int] | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search federal awards (contracts, IDVs, grants, loans, etc.) on USASpending.gov.

    This is the primary workhorse for finding awards. Returns matching awards
    with standard fields (Award ID, Recipient, Description, Amount, Agencies,
    NAICS, PSC, dates). Use get_award_detail() with the generated_internal_id
    from results to get full award details.

    Important rules:
    - award_type groups cannot be mixed; pick one category per call
    - time_period_start/end use YYYY-MM-DD format
    - award_amount_min/max are in USD
    - place_of_performance_state is a 2-letter USPS code (e.g. 'MD', 'VA')
    - For loans, use award_type='loans' and sort='Loan Value'
    - def_codes filters to Disaster Emergency Fund codes (COVID-19, IIJA,
      IRA supplementals); see get_def_codes_reference() for the list

    Filtering to specific contracting commands (NAVSEA, AFRL, etc.):
    USASpending's subtier level is at the service branch (Department of the
    Navy, Army, Air Force), not the contracting command. To filter to a
    specific command, use keywords with the PIID office prefix instead:
    - NAVSEA contracts:  keywords=['N00024']
    - Army Contracting:  keywords=['W91CRB']
    - AFRL:              keywords=['FA8650']
    - NAVAIR:            keywords=['N00019']
    This performs a substring match on the PIID field and is more reliable
    than the award_ids filter for partial matches.

    Common filter value references:
    - set_aside_type_codes: SBA, SBP, 8A, 8AN, HZC, HZS, SDVOSBS, SDVOSBC,
      WOSB, WOSBSS, EDWOSB, EDWOSBSS, VSA
    - extent_competed_type_codes: A (Full & Open), B, C, D, E, F, G, CDO, NDO
    - contract_pricing_type_codes: J (FFP), Y (T&M), Z (LH), U (CPFF),
      V (CPIF), R (CPAF), L (FP Incentive), M (FP Award Fee)

    IMPORTANT: awarding_agency/funding_agency must be the FULL TOPTIER NAME,
    not a slug. Use 'Department of Defense', NOT 'department-of-defense'.
    Slugs silently return zero results, and so does any name that is not a
    toptier agency: the military departments are SUBTIERS, so pass
    awarding_agency='Department of Defense' with
    awarding_subagency='Department of the Navy' (never 'Department of the
    Navy' as awarding_agency). A mismatched pair (a subagency that does not
    belong to the given toptier) also silently returns zero results. Use
    list_toptier_agencies() and get_agency_sub_agencies() for exact names.

    Result caveats: recipient_name matches corporate affiliations, so a
    parent-company search can return joint ventures whose display names
    share no text with the query (a Hanford JV surfaces under 'Leidos');
    verify names before presenting a definitive list. Large pulls can
    exceed MCP client payload budgets (limit=100 has measured ~90K
    characters); page in batches of 25-30 for big result sets.

    "Award Amount" is the award's lifetime obligation, not the amount in
    the time window. There is no period-of-performance end-date filter, so
    expiring-contract (recompete) questions can't be filtered here: sorting
    by 'End Date' over an action-date window returns long-ended awards that
    had a closeout mod; filter the End Date column yourself.

    date_type controls what the time window means. Omitted (the default),
    an award counts if it had any action in the window, so totals and
    counts include old awards that were only modified (a closeout mod in
    2026 puts a 2010 contract in an FY2026 list) and are NOT new awards.
    'new_awards_only' keeps only awards first signed in the window: use it
    for "how many new awards / contracts awarded in FY2026". 'date_signed',
    'action_date' and 'last_modified_date' are the other upstream options.
    date_type needs time_period_start and/or time_period_end.
    """
    codes = _resolve_award_type(award_type)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")

    # Reject control characters in free-text inputs. USASpending either
    # 500s on these or silently treats them as whitespace, both bad UX.
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    _validate_no_control_chars(awarding_subagency, field="awarding_subagency")
    _validate_no_control_chars(funding_agency, field="funding_agency")
    _validate_no_control_chars(recipient_name, field="recipient_name")
    # Negative amounts silently return default results as if no filter.
    if award_amount_min is not None and award_amount_min < 0:
        raise ValueError(
            f"award_amount_min must be >= 0. Got {award_amount_min}. "
            f"Negative minimums are silently ignored by USASpending and "
            f"return unfiltered results."
        )
    if award_amount_max is not None and award_amount_max < 0:
        raise ValueError(
            f"award_amount_max must be >= 0. Got {award_amount_max}."
        )

    if award_type == "contracts":
        fields = list(DEFAULT_CONTRACT_FIELDS)
    elif award_type == "idvs":
        fields = list(DEFAULT_IDV_FIELDS)
    elif award_type == "loans":
        fields = list(DEFAULT_LOAN_FIELDS)
    elif award_type == "grants":
        fields = list(DEFAULT_GRANT_FIELDS)
    else:
        # direct_payments / other: assistance field set ("Award Type",
        # not the contracts-only "Contract Award Type" which comes back null)
        fields = list(DEFAULT_ASSISTANCE_FIELDS)

    # Default sort differs for loans
    if sort is None:
        sort = "Loan Value" if award_type == "loans" else "Award Amount"

    # CRITICAL: sort field MUST be in fields array
    if sort not in fields:
        fields.append(sort)

    filters = _build_filters(
        keywords=keywords,
        award_type_codes=codes,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        funding_agency=funding_agency,
        recipient_name=recipient_name,
        award_ids=award_ids,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        extent_competed_type_codes=extent_competed_type_codes,
        contract_pricing_type_codes=contract_pricing_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        date_type=date_type,
        award_amount_min=award_amount_min,
        award_amount_max=award_amount_max,
        place_of_performance_state=place_of_performance_state,
        def_codes=def_codes,
    )
    # award_type_codes is always present because we always set it, but it's
    # a scope not a filter. Require at least one real filter so that empty
    # calls don't silently return unfiltered recent awards.
    real_filter_keys = [k for k in filters if k != "award_type_codes"]
    if not real_filter_keys:
        raise ValueError(
            "search_awards requires at least one filter beyond award_type. "
            "Typical: keywords + time_period_start/end, or recipient_name, "
            "or awarding_agency, or naics_codes, or psc_codes. Calling "
            "without filters silently returns recent awards and is usually "
            "a typo in parameter names."
        )

    payload = {
        "subawards": False,
        "limit": limit,
        "page": page,
        "sort": sort,
        "order": order,
        "filters": filters,
        "fields": fields,
    }
    result = await _post("/api/v2/search/spending_by_award/", payload)
    return _add_note(result, _dod_lag_note(
        _window_end(time_period_start, time_period_end),
        agencies=(awarding_agency, funding_agency), award_types=award_type,
    ))


@mcp.tool(annotations={"title": "Get Award Count", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_count(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    date_type: DateType | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    def_codes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Count awards matching filters, broken down by award category.

    Returns counts grouped by: contracts, idvs, grants, loans, direct_payments, other.
    Use this for dimensional analysis: how many FFP vs T&M awards, how many
    competed vs sole-source, how many small business set-asides, etc.

    Unlike search_awards, this returns total counts across ALL award categories
    in a single call (not just the one specified in award_type). The award_type
    parameter is ignored here; filters apply to the count query directly.

    def_codes filters to Disaster Emergency Fund codes; see
    get_def_codes_reference().

    At least one filter is required (the API rejects empty filter sets with HTTP 400).
    Typical usage: pass time_period_start + time_period_end, or a keywords/agency filter.

    date_type controls what the time window means. Omitted (the default),
    an award counts if it had any action in the window, so totals and
    counts include old awards that were only modified (a closeout mod in
    2026 puts a 2010 contract in an FY2026 list) and are NOT new awards.
    'new_awards_only' keeps only awards first signed in the window: use it
    for "how many new awards / contracts awarded in FY2026". 'date_signed',
    'action_date' and 'last_modified_date' are the other upstream options.
    date_type needs time_period_start and/or time_period_end.
    """
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    _validate_no_control_chars(recipient_name, field="recipient_name")
    if award_amount_min is not None and award_amount_min < 0:
        raise ValueError(f"award_amount_min must be >= 0. Got {award_amount_min}.")
    if award_amount_max is not None and award_amount_max < 0:
        raise ValueError(f"award_amount_max must be >= 0. Got {award_amount_max}.")

    filters = _build_filters(
        keywords=keywords,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        funding_agency=funding_agency,
        recipient_name=recipient_name,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        extent_competed_type_codes=extent_competed_type_codes,
        contract_pricing_type_codes=contract_pricing_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        date_type=date_type,
        award_amount_min=award_amount_min,
        award_amount_max=award_amount_max,
        place_of_performance_state=place_of_performance_state,
        def_codes=def_codes,
    )
    if not filters:
        raise ValueError(
            "get_award_count requires at least one filter. "
            "Typical: time_period_start + time_period_end, or keywords, or awarding_agency."
        )
    result = await _post("/api/v2/search/spending_by_award_count/", {"filters": filters})
    return _add_note(result, _dod_lag_note(
        _window_end(time_period_start, time_period_end),
        agencies=(awarding_agency, funding_agency), award_types=None,
    ))


@mcp.tool(annotations={"title": "Spending Over Time", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def spending_over_time(
    group: Literal["fiscal_year", "quarter", "month"] = "fiscal_year",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    date_type: DateType | None = None,
    def_codes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Aggregate spending amounts over time, grouped by fiscal year, quarter, or month.

    Use this to visualize spending trends, identify fiscal-year-end spikes,
    or compare spending patterns across years.

    Note: The API returns fiscal_year as a STRING. Cast to int for numeric
    comparisons. quarter and month are FISCAL periods (month 1 = October,
    quarter 1 = October-December). Buckets are clipped to the window, so a
    calendar-2025 window returns a partial fiscal_year '2025' (January-
    September only) and a partial '2026' (October-December); neither is
    that whole fiscal year.

    DoD contract actions are published 90 days late, so when the window
    reaches into the last 90 days and DoD is in scope the answer carries a
    data_note: those months are understated, so don't read them as a drop.

    awarding_agency must be a TOPTIER agency name ('Department of Defense').
    Military departments are subtiers: pass
    awarding_subagency='Department of the Navy'. A non-toptier name in
    awarding_agency (or a subagency that does not belong to the given
    toptier) silently returns all-zero aggregates.

    At least one filter is required (the API rejects empty filter sets with HTTP 400).
    Typical usage: pass time_period_start + time_period_end.

    date_type controls what the time window means. Omitted (the default),
    an award counts if it had any action in the window, so totals and
    counts include old awards that were only modified (a closeout mod in
    2026 puts a 2010 contract in an FY2026 list) and are NOT new awards.
    'new_awards_only' keeps only awards first signed in the window: use it
    for "how many new awards / contracts awarded in FY2026". 'date_signed',
    'action_date' and 'last_modified_date' are the other upstream options.
    date_type needs time_period_start and/or time_period_end.
    """
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    _validate_no_control_chars(recipient_name, field="recipient_name")
    award_type_codes = _resolve_award_type(award_type) if award_type else None
    filters = _build_filters(
        keywords=keywords,
        award_type_codes=award_type_codes,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        funding_agency=funding_agency,
        extent_competed_type_codes=extent_competed_type_codes,
        contract_pricing_type_codes=contract_pricing_type_codes,
        recipient_name=recipient_name,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        date_type=date_type,
        def_codes=def_codes,
    )
    # award_type_codes alone (without other filters) is not enough: the API
    # treats award_type_codes as a scope, not a filter, and still 400s.
    has_real_filter = any(k for k in filters if k != "award_type_codes")
    if not has_real_filter:
        raise ValueError(
            "spending_over_time requires at least one filter beyond award_type. "
            "Typical: time_period_start + time_period_end, or keywords, or awarding_agency."
        )
    result = await _post(
        "/api/v2/search/spending_over_time/",
        {"group": group, "filters": filters},
    )
    return _add_note(result, _dod_lag_note(
        _window_end(time_period_start, time_period_end),
        agencies=(awarding_agency, funding_agency), award_types=award_type,
    ))


@mcp.tool(annotations={"title": "Spending by Category", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def spending_by_category(
    category: Literal[
        "awarding_agency", "awarding_subagency", "funding_agency", "funding_subagency",
        "recipient", "cfda", "naics", "psc", "country", "county", "district",
        "state_territory", "federal_account", "defc"
    ],
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    date_type: DateType | None = None,
    def_codes: list[str | int] | None = None,
    limit: int = 10,
    page: int = 1,
) -> dict[str, Any]:
    """Aggregate spending by a dimension (top vendors, top agencies, top NAICS, etc.).

    The 'category' parameter controls the grouping dimension. Common uses:
    - category='recipient': top vendors for a filter set (vendor landscape analysis)
    - category='awarding_subagency': which contracting offices within an agency
    - category='naics': which work categories got the most spending
    - category='psc': which product/service codes got the most spending
    - category='state_territory': geographic distribution
    - category='cfda': grant assistance listings

    Note: recipient category returns vendor names in ALL CAPS and may contain
    duplicates (subsidiaries, rebrands, re-registrations). For precise market
    share, apply name normalization to the returned 'name' field.

    At least one filter is required. An unfiltered call would silently
    aggregate the entire USASpending database (all years, all agencies),
    which is never what a caller wants.

    date_type controls what the time window means. Omitted (the default),
    an award counts if it had any action in the window, so totals and
    counts include old awards that were only modified (a closeout mod in
    2026 puts a 2010 contract in an FY2026 list) and are NOT new awards.
    'new_awards_only' keeps only awards first signed in the window: use it
    for "how many new awards / contracts awarded in FY2026". 'date_signed',
    'action_date' and 'last_modified_date' are the other upstream options.
    date_type needs time_period_start and/or time_period_end.
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    award_type_codes = _resolve_award_type(award_type) if award_type else None
    filters = _build_filters(
        keywords=keywords,
        award_type_codes=award_type_codes,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        funding_agency=funding_agency,
        recipient_name=recipient_name,
        extent_competed_type_codes=extent_competed_type_codes,
        contract_pricing_type_codes=contract_pricing_type_codes,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        date_type=date_type,
        def_codes=def_codes,
    )
    # Same guard as search_awards: award_type_codes is a scope, not a filter.
    # Without it an unfiltered call returns an all-time all-agency aggregate
    # (a $40T "MULTIPLE RECIPIENTS" row) with no hint it is unscoped.
    has_real_filter = any(k for k in filters if k != "award_type_codes")
    if not has_real_filter:
        raise ValueError(
            "spending_by_category requires at least one filter beyond award_type. "
            "Typical: time_period_start + time_period_end, or keywords, or awarding_agency."
        )
    result = await _post(
        f"/api/v2/search/spending_by_category/{category}/",
        {"filters": filters, "limit": limit, "page": page},
    )
    return _add_note(result, _dod_lag_note(
        _window_end(time_period_start, time_period_end),
        agencies=(awarding_agency, funding_agency), award_types=award_type,
    ))


# ---------------------------------------------------------------------------
# Detail tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Get Award Detail", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_detail(generated_award_id: str) -> dict[str, Any]:
    """Fetch full details for a single award by its generated_internal_id.

    Use the generated_internal_id value returned by search_awards to fetch
    the complete award record. Returns: PIID, full description, total
    obligation, recipient details, parent award info, latest transaction
    contract data (competition, set-aside, pricing type), period of
    performance, place of performance, NAICS hierarchy, PSC hierarchy,
    base and all options value, and sub-award totals. Award-level outlays and
    total_account_obligation are partial or lagged File C measures, not a
    reliable amount paid; compare with total_obligation for coverage.

    Accepts either a generated award id (CONT_AWD_*, CONT_IDV_*, ASST_NON_*,
    ASST_AGG_*) or the numeric internal database id from a prior response.

    Example generated_award_id format: CONT_AWD_N0002424C0085_9700_N0002421D0001_9700
    """
    if not isinstance(generated_award_id, str) or not generated_award_id.strip():
        raise ValueError(
            "generated_award_id cannot be empty. Pass the generated_internal_id "
            "field from search_awards results (e.g. CONT_AWD_...)."
        )
    _validate_no_control_chars(generated_award_id, field="generated_award_id")
    award_id = generated_award_id.strip()
    # The API also accepts the numeric internal award id; anything else must
    # be a well-formed generated id. Before the round 10 audit this tool did
    # no format validation at all, so path metacharacters could walk the
    # request onto arbitrary API endpoints ('../references/toptier_agencies'
    # returned the agency list dressed up as award detail).
    if not award_id.isdigit():
        award_id = _validate_generated_award_id(award_id, field="generated_award_id")
    result = await _get(f"/api/v2/awards/{award_id}/")
    return _add_note(result, "Award-level outlays and total_account_obligation come from File C. "
                     "They can be partial or lagged and do not establish the amount paid to the contractor. "
                     "Compare total_account_obligation with total_obligation for File C coverage.")


@mcp.tool(annotations={"title": "Get Transactions", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_transactions(
    generated_award_id: str,
    limit: int = 100,
    page: int = 1,
    sort: str = "action_date",
    order: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Fetch the full transaction (modification) history for an award.

    Every modification, option exercise, and de-obligation is a transaction.
    Modification number '0' is the original base award. Use to understand
    the full lifecycle of a contract including its descriptive text at each
    point in time.

    Returns per transaction: id, type, action_date, action_type,
    modification_number, description, federal_action_obligation.
    """
    if not isinstance(generated_award_id, str) or not generated_award_id.strip():
        raise ValueError("generated_award_id cannot be empty.")
    _validate_no_control_chars(generated_award_id, field="generated_award_id")
    limit = _clamp_limit(limit, cap=5000)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    return await _post(
        "/api/v2/transactions/",
        {
            "award_id": generated_award_id.strip(),
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


@mcp.tool(annotations={"title": "Get Award Funding", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_funding(
    generated_award_id: str,
    limit: int = 50,
    page: int = 1,
    sort: str = "reporting_fiscal_date",
    order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    """Fetch File C funding data for an award: federal account, object class, program activity.

    Shows which Treasury accounts, object classes, and program activities
    funded an award. File C can be partial or lagged; these rows do not
    establish the full award obligation or amount paid to the contractor.

    Sort fields: reporting_fiscal_date, account_title,
    transaction_obligated_amount, object_class.
    """
    limit = _clamp_limit(limit, cap=100)
    if not isinstance(generated_award_id, str) or not generated_award_id.strip():
        raise ValueError("generated_award_id cannot be empty.")
    _validate_no_control_chars(generated_award_id, field="generated_award_id")
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    result = await _post(
        "/api/v2/awards/funding/",
        {
            "award_id": generated_award_id.strip(),
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )

    return _add_note(result, "File C funding can be partial or lagged; these rows are not the full "
                     "award obligation or amount paid. Compare with get_award_detail total_obligation "
                     "and total_account_obligation for coverage.")

@mcp.tool(annotations={"title": "Get IDV Children", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_idv_children(
    generated_idv_id: str,
    child_type: Literal["child_awards", "child_idvs", "grandchild_awards"] = "child_awards",
    limit: int = 50,
    page: int = 1,
    sort: str = "period_of_performance_start_date",
    order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    """Fetch child awards (task/delivery orders) under an IDV.

    For a Multiple Award IDV, child_awards returns the task orders or delivery
    orders placed against it. For a parent IDV, child_idvs returns the
    downstream IDV structure. grandchild_awards walks the hierarchy.

    Field name differences from search_awards: children use 'piid' (not
    'Award ID'), 'obligated_amount' (not 'Award Amount'), and
    'generated_unique_award_id' (not 'generated_internal_id').

    An active vehicle can legitimately return zero children here:
    USASpending's award cross-linking has gaps. Treat an empty result as a
    reporting gap, not proof that no orders exist. Try get_idv_activity()
    on the same id. A search_awards call with keywords=['<IDV PIID>'] only
    finds orders whose description happens to cite the IDV, so it misses
    orders (often the largest) and is no proof of completeness.
    """
    if not isinstance(generated_idv_id, str) or not generated_idv_id.strip():
        raise ValueError("generated_idv_id cannot be empty.")
    _validate_no_control_chars(generated_idv_id, field="generated_idv_id")
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    return await _post(
        "/api/v2/idvs/awards/",
        {
            "award_id": generated_idv_id.strip(),
            "type": child_type,
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


# ---------------------------------------------------------------------------
# Workflow / convenience tools
# ---------------------------------------------------------------------------

_PIID_FIELDS = {
    "contract": [
        "Award ID", "Recipient Name", "Description",
        "Award Amount", "Start Date", "End Date",
        "Awarding Agency", "Awarding Sub Agency",
        "generated_internal_id",
    ],
    "idv": [
        "Award ID", "Recipient Name", "Description",
        "Award Amount", "Start Date", "Last Date to Order",
        "Awarding Agency", "Awarding Sub Agency",
        "generated_internal_id",
    ],
}


def _parent_idv_piid(generated_id: Any) -> str | None:
    """Parent IDV PIID from a contract's generated id.

    CONT_AWD_<piid>_<agency>_<parent piid>_<parent agency>; '-NONE-' means
    a standalone contract. IDV ids (CONT_IDV_<piid>_<agency>) have none.
    """
    if not isinstance(generated_id, str) or not generated_id.startswith("CONT_AWD_"):
        return None
    parts = generated_id.split("_")
    if len(parts) != 6 or parts[4] == "-NONE-":
        return None
    return parts[4]


async def _piid_search(filters: dict[str, Any], kind: str, limit: int) -> dict[str, Any]:
    group = "contracts" if kind == "contract" else "idvs"
    result = await _post(
        "/api/v2/search/spending_by_award/",
        {
            "subawards": False,
            "limit": limit,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
            "filters": {**filters, "award_type_codes": AWARD_TYPE_GROUPS[group]},
            "fields": _PIID_FIELDS[kind],
        },
    )
    rows = result.get("results") or []
    for row in rows:
        if isinstance(row, dict):
            row["award_type"] = kind
            if kind == "contract":
                row["parent_idv_piid"] = _parent_idv_piid(row.get("generated_internal_id"))
    return {"rows": rows, "hasNext": bool((result.get("page_metadata") or {}).get("hasNext"))}


@mcp.tool(annotations={"title": "Lookup PIID", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def lookup_piid(piid: str, limit: int = 5) -> dict[str, Any]:
    """Look up awards by their exact PIID, across contracts AND IDVs.

    Looks for awards whose own PIID is exactly this value (the award_ids
    filter), in both contracts and IDVs, and says how many share it.
    match='exact' rows are the awards themselves: an IDV PIID returns the
    IDV (award_type='idv'; its Award Amount is what was obligated on the IDV
    record itself, usually 0, so use get_idv_amounts() for the order total).
    PIIDs are not unique: task and delivery order numbers like '0001' repeat
    under different parent IDVs, so check 'ambiguous' and tell matches apart
    by parent_idv_piid and Awarding Agency.

    Only when nothing has that exact PIID does it fall back to keyword
    search, and those rows come back as match='fuzzy': keyword search
    matches the award's own PIID and its description text, NOT its parent
    IDV, so a vehicle PIID or prefix returns only orders whose description
    happens to cite it. For the orders under a vehicle use get_idv_activity()
    or get_idv_children() with the IDV's generated_internal_id; for a
    contracting-office prefix (N00024, W91CRB, FA8650) use search_awards
    keywords with a time window.

    limit applies to contracts and to IDVs separately. Use
    get_award_detail() with a returned generated_internal_id for the full
    record. Handy for enriching PRISM, Contract Court, or FPDS exports where
    you have a PIID but don't know whether it's a contract or IDV.
    """
    piid = (piid or "").strip()
    if len(piid) < 3:
        raise ValueError(
            f"piid must be at least 3 characters (USASpending keyword search minimum). "
            f"Got {piid!r}."
        )
    _validate_no_control_chars(piid, field="piid")
    limit = _clamp_limit(limit, cap=100)

    # Exact pass. award_ids is an exact, case-sensitive match on the award's
    # own PIID (verified live 2026-10-10: 'gs00q14oadu108' finds nothing,
    # 'GS00Q14OADU108' finds the OASIS IDV), and PIIDs are stored uppercase.
    ids = list(dict.fromkeys([piid.upper(), piid]))
    counts = await _post("/api/v2/search/spending_by_award_count/", {"filters": {"award_ids": ids}})
    counted = counts.get("results") or {}
    n_contracts = int(counted.get("contracts") or 0)
    n_idvs = int(counted.get("idvs") or 0)
    if n_contracts or n_idvs:
        rows: list[dict[str, Any]] = []
        has_next = False
        for kind, n in (("contract", n_contracts), ("idv", n_idvs)):
            if n:
                found = await _piid_search({"award_ids": ids}, kind, limit)
                rows.extend(found["rows"])
                has_next = has_next or found["hasNext"]
        total = n_contracts + n_idvs
        kinds = [k for k, n in (("contract", n_contracts), ("idv", n_idvs)) if n]
        out: dict[str, Any] = {
            "match": "exact",
            "piid": piid.upper(),
            "award_type": kinds[0] if len(kinds) == 1 else "contract_and_idv",
            "exact_match_count": {"contracts": n_contracts, "idvs": n_idvs},
            "ambiguous": total > 1,
            "results": rows,
            "page_metadata": {"page": 1, "hasNext": has_next},
        }
        if total > 1:
            out["note"] = (
                f"Ambiguous: {total:,} awards have PIID {piid.upper()} exactly "
                f"({n_contracts:,} contracts, {n_idvs:,} IDVs); the largest are shown. "
                "Order numbers repeat under different parent IDVs, so identify the "
                "award by parent_idv_piid and Awarding Agency, or narrow with "
                "search_awards(award_ids=[...], awarding_agency=..., time window)."
            )
        return out

    # No exact PIID: fall back to full-text keyword search, labeled fuzzy.
    rows = []
    has_next = False
    for kind in ("contract", "idv"):
        found = await _piid_search({"keywords": [piid]}, kind, limit)
        rows.extend(found["rows"])
        has_next = has_next or found["hasNext"]
    if rows:
        return {
            "match": "fuzzy",
            "piid": piid.upper(),
            "award_type": None,
            "exact_match_count": {"contracts": 0, "idvs": 0},
            "ambiguous": False,
            "results": rows,
            "page_metadata": {"page": 1, "hasNext": has_next},
            "note": (
                f"No award has PIID {piid.upper()} exactly. These are keyword "
                "matches (the term appears in the award's own PIID or description "
                "text), not lookups: an award's parent IDV is not searched, so "
                "orders under a vehicle are missing unless their description cites "
                "it. For a vehicle's orders use get_idv_activity() on the IDV."
            ),
        }

    return {
        "match": "none",
        "piid": piid.upper(),
        "award_type": None,
        "exact_match_count": {"contracts": 0, "idvs": 0},
        "ambiguous": False,
        "results": [],
        "message": (
            f"No contracts or IDVs found matching '{piid}'. "
            "Try grants/loans/direct_payments via search_awards with the "
            "appropriate award_type parameter, or widen the time_period range."
        ),
    }


# ---------------------------------------------------------------------------
# Autocomplete tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Autocomplete PSC", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_psc(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete lookup for Product/Service Codes (PSC).

    Works best with code prefixes ('R499', 'D3', 'AJ') or keywords
    ('professional', 'application'). Returns matching PSC entries with
    code and description.

    Minimum 2 characters required. Single-character queries return first-N
    alphabetical results from the upstream API (useless for matching) and
    empty strings return HTTP 400.
    """
    _validate_no_control_chars(search_text, field="search_text")
    search_text = (search_text or "").strip()
    if len(search_text) < 2:
        return {
            "results": [],
            "_note": "autocomplete_psc requires at least 2 characters; upstream API returns arbitrary first-N results otherwise.",
        }
    if len(search_text) > 200:
        raise ValueError(
            f"search_text exceeds 200 chars (got {len(search_text)}). "
            f"Autocomplete is intended for prefix / keyword lookups."
        )
    limit = _clamp_limit(limit, cap=100)
    return await _post(
        "/api/v2/autocomplete/psc/",
        {"search_text": search_text, "limit": limit},
    )


@mcp.tool(annotations={"title": "Autocomplete NAICS", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_naics(
    search_text: str,
    limit: int = 10,
    exclude_retired: bool = True,
) -> dict[str, Any]:
    """Autocomplete lookup for NAICS codes.

    Accepts partial codes ('541') or keywords ('software'). Returns matching
    NAICS entries with code and description.

    Minimum 2 characters required. Short queries silently match substrings
    inside parenthetical notes (e.g. 'x' matches 'except') and produce
    nonsense results, so we require 2+ chars.

    exclude_retired defaults to True. The upstream NAICS taxonomy still
    returns codes retired in 2012/2017/2022; these are almost never what
    callers want. Set exclude_retired=False to include them.
    """
    _validate_no_control_chars(search_text, field="search_text")
    search_text = (search_text or "").strip()
    if len(search_text) < 2:
        return {
            "results": [],
            "_note": "autocomplete_naics requires at least 2 characters; upstream substring-matches into parenthetical notes otherwise.",
        }
    if len(search_text) > 200:
        raise ValueError(
            f"search_text exceeds 200 chars (got {len(search_text)})."
        )
    limit = _clamp_limit(limit, cap=100)
    # Request more from upstream so the client-side retired filter still yields
    # enough results. The old cap of 50 silently starved results below the
    # requested limit (verified live: 58 active codes matched '54' but only
    # 41 were returned). Cap at 500, the API's autocomplete maximum.
    upstream_limit = min(limit * 3, 500) if exclude_retired else limit
    response = await _post(
        "/api/v2/autocomplete/naics/",
        {"search_text": search_text, "limit": upstream_limit},
    )
    if exclude_retired:
        results = response.get("results") or []
        current = [r for r in results if r.get("year_retired") is None]
        retired_count = len(results) - len(current)
        active = current[:limit]
        response["results"] = active
        response["_note"] = (
            f"Filtered {retired_count} retired codes from the fetched matches. "
            f"{len(current) - len(active)} additional current codes were omitted by limit={limit}. "
            "Increase limit to request more current matches. "
            "Pass exclude_retired=False to include retired codes."
        )
    return response


# ---------------------------------------------------------------------------
# Reference tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "List Toptier Agencies", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def list_toptier_agencies() -> dict[str, Any]:
    """List all top-tier federal agencies tracked by USASpending.

    Returns agency codes, names, abbreviations, and current-year budgetary
    resources. Use the returned 'toptier_code' values with get_agency_overview().
    """
    return await _get("/api/v2/references/toptier_agencies/")


def _normalize_toptier(toptier_code: str, *, field: str = "toptier_code") -> str:
    """Normalize a toptier agency code: strip, validate numeric, left-pad to
    3 digits, require 3-4 digits after padding.

    This is the single normalizer for all eight agency tools. Before the
    round 10 audit, get_agency_overview and get_agency_awards padded '97' to
    '097' while the other six agency tools rejected it, so the same input
    behaved differently across the family.
    """
    if toptier_code is None or not str(toptier_code).strip():
        raise ValueError(
            f"{field} cannot be empty: pass a 3-4 digit numeric agency code "
            f"(e.g. '097' for DoD). Use list_toptier_agencies() to find valid codes."
        )
    code = str(toptier_code).strip()
    if not code.isdigit():
        raise ValueError(
            f"{field}={toptier_code!r} must be a 3-4 digit numeric agency code "
            f"(e.g. '097' for DoD, '075' for HHS); shorter all-digit inputs are "
            f"zero-padded automatically. Use list_toptier_agencies() to find "
            f"valid codes."
        )
    code = code.zfill(3)
    if len(code) > 4:
        raise ValueError(
            f"{field}={toptier_code!r} has too many digits: toptier codes are "
            f"a 3-4 digit numeric agency code (e.g. '097' for DoD, '075' for HHS)."
        )
    return code


def _validate_fiscal_year(fiscal_year: int) -> int:
    """Reject fiscal years outside the API's accepted window (2008 .. current FY)."""
    current = _current_fiscal_year()
    if fiscal_year < 2008:
        raise ValueError(
            f"fiscal_year must be >= 2008 (USASpending data starts FY2008). Got {fiscal_year}."
        )
    if fiscal_year > current:
        raise ValueError(
            f"fiscal_year must be <= {current} (current FY). Got {fiscal_year}."
        )
    return fiscal_year


@mcp.tool(annotations={"title": "Get Agency Overview", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_overview(
    toptier_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get descriptive information for an agency: name, mission, website,
    data notes and DEF codes. It has no dollar figures; for spending use
    get_agency_obligations_by_award_category() (split by award type) or
    get_agency_budgetary_resources() (obligations and outlays by year).

    toptier_code is the 3- or 4-digit agency code (e.g. '097' for DoD,
    '075' for HHS, '080' for NASA). Shorter inputs like '97' are left-padded
    to '097' automatically. Get valid codes via list_toptier_agencies().

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default). The answer always carries fiscal_year.
    """
    code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = _last_completed_fiscal_year() if defaulted else _validate_fiscal_year(fiscal_year)
    result = await _get(f"/api/v2/agency/{code}/", params={"fiscal_year": str(fy)})
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


@mcp.tool(annotations={"title": "Get Agency Awards", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_awards(
    toptier_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get one obligation total and transaction count for an agency's awards
    in a fiscal year.

    The total covers ALL award types together (contracts, IDVs, grants,
    loans, direct payments, other), so for most civilian agencies it is far
    larger than contract spending (VA FY2026: $313B here vs $84B contracts).
    For the split by award type use get_agency_obligations_by_award_category().
    toptier_code is auto-padded to 3 digits if a shorter numeric value is
    supplied.

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default, which right after October 1 holds only a
    few days of data). The answer always carries fiscal_year.
    """
    code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = _last_completed_fiscal_year() if defaulted else _validate_fiscal_year(fiscal_year)
    result = await _get(f"/api/v2/agency/{code}/awards/", params={"fiscal_year": str(fy)})
    result = _add_note(result, _agency_dod_lag_note(code, fy))
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


@mcp.tool(annotations={"title": "Get NAICS Details", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_naics_details(code: str) -> dict[str, Any]:
    """Get details for a NAICS code (2-6 digits).

    Returns the NAICS description, parent categories, and child subcategories
    if applicable.
    """
    if not code or not code.strip().isdigit():
        raise ValueError(
            f"NAICS code must be numeric (2, 4, or 6 digits). Got {code!r}."
        )
    return await _get(f"/api/v2/references/naics/{code.strip()}/")


@mcp.tool(annotations={"title": "Get PSC Filter Tree", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_psc_filter_tree(
    path: str = "",
) -> dict[str, Any]:
    """Get the PSC hierarchy tree.

    Pass an empty path for the top-level. Drill down with paths like
    'Service/R/' to get the service professional services tree, or
    'Product/5' for product codes starting with 5.
    """
    # The drill-down path is interpolated into the URL: '/' is the legitimate
    # level separator, but '..' segments would walk the request onto other
    # API endpoints and '%' smuggles encoded forms. Round 10 audit hardening,
    # same class as the get_award_detail path escape.
    if path and any(tok in path for tok in ("..", "%", "\\")):
        raise ValueError(
            f"path={path!r} contains URL path characters ('..', '%', or '\\\\'). "
            f"PSC tree paths look like 'Service/R' or 'Product/5'."
        )
    # P2 bug fix in 0.2.8: USASpending PSC filter tree endpoint requires
    # a trailing slash. Without it, the API returns HTTP 301 redirect.
    # Caught by round 6 live audit.
    endpoint = "/api/v2/references/filter_tree/psc/"
    if path:
        endpoint = f"{endpoint}{path.lstrip('/').rstrip('/')}/"
    return await _get(endpoint)


@mcp.tool(annotations={"title": "Get State Profile", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_state_profile(state_fips: str, year: str | int | None = None) -> dict[str, Any]:
    """Get the federal award totals for recipients located in a US state.

    Examples: '06' = California, '48' = Texas, '24' = Maryland, '51' = Virginia.
    Returns one summary: state name and code, total_prime_amount and
    total_prime_awards (all award types together), loan face value,
    award_amount_per_capita, total_outlays, and population / median household
    income (older Census vintages: see pop_year and mhi_year). It has no
    breakdown by agency, recipient or district; for those use
    spending_by_geography() or spending_by_category() with a time window.

    year: a fiscal year like 2026, 'all' (every year on file) or 'latest'
    (USAspending's own default: the current fiscal year to date, which right
    after October 1 holds only a few days of data). Defaults to the last
    completed fiscal year. The answer always carries fiscal_year.
    """
    if not state_fips or not state_fips.strip().isdigit() or len(state_fips.strip()) != 2:
        raise ValueError(
            f"state_fips must be a 2-digit numeric FIPS code (e.g., '06' for CA, '51' for VA). "
            f"Got {state_fips!r}."
        )
    defaulted = year is None or not str(year).strip()
    if defaulted:
        year_str = str(_last_completed_fiscal_year())
    else:
        year_str = str(year).strip().lower()
        if year_str not in ("all", "latest"):
            year_str = str(_validate_fiscal_year(_parse_year_int(year_str, field="year")))
    result = await _get(f"/api/v2/recipient/state/{state_fips.strip()}/", params={"year": year_str})
    end = date(int(year_str), 9, 30) if year_str.isdigit() else _today()
    result = _add_note(result, _dod_lag_note(end, award_types=None))
    return _echo_fiscal_year(result, year_str, defaulted=defaulted, param="year")


def _parse_year_int(value: str, *, field: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"{field} must be a fiscal year like 2026, 'all', or 'latest'. Got {value!r}."
        ) from exc


# ===========================================================================
# v0.3 expansion: subawards, recipient depth, agency depth, award depth,
# transaction/geography/timeline search, IDV depth, autocomplete helpers,
# reference data, federal accounts.
# ===========================================================================


# ---------------------------------------------------------------------------
# Subawards (FFATA)
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Subawards", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def search_subawards(
    award_id: str | None = None,
    sort: Literal["amount", "action_date", "subaward_number", "recipient_name", "description"] = "amount",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search FFATA subaward reports on USASpending.

    Returns the FFATA subaward records (subcontracts under prime contracts and
    subawards under prime grants). Complementary to the SAM.gov FFATA endpoints
    but expressed at the USASpending data model.

    award_id: optional generated_internal_id (CONT_AWD_..., ASST_NON_..., etc.)
    to scope subawards to a single prime award. If omitted, returns subawards
    across all primes for the page.

    Pagination uses page (1-indexed) and limit (1-100).
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    payload: dict[str, Any] = {
        "sort": sort,
        "order": order,
        "limit": limit,
        "page": page,
    }
    if award_id is not None:
        award_id = _validate_no_control_chars(award_id, field="award_id")
        if not award_id.strip():
            raise ValueError("award_id cannot be empty whitespace; omit instead.")
        payload["award_id"] = award_id.strip()
    return await _post("/api/v2/subawards/", payload)


@mcp.tool(annotations={"title": "Spending by Subaward Grouped", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def spending_by_subaward_grouped(
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_type_codes: list[str] | None = None,
    awarding_agency: str | None = None,
    funding_agency: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    def_codes: list[str | int] | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Find matching prime awards and their cumulative FFATA report totals.

    Filters select prime records, but subaward_count and subaward_obligation
    cover all reported subawards under each prime, not just subaward actions
    within time_period_start/end. This ranking is not a fiscal-period
    subaward ranking. For dated reports, pass a returned
    award_generated_internal_id to search_subawards(award_id=...), read every
    page, and retain action_date values inside the desired period.

    sort accepts: award_id, subaward_count, award_generated_internal_id,
    subaward_obligation. (These differ from search_subawards, which sorts by
    amount/action_date/etc.) Anything else returns HTTP 400 from the API.

    page_metadata.hasNext is worked out here: the endpoint itself always
    says false, even with more pages. Rows include primes with no
    subawards (subaward_count 0). subaward_obligation sums FFATA reports,
    which can repeat cumulative amounts, so a subaward_to_award_ratio
    above 1 is a reporting artefact, not more subcontracting than the prime.
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    filters = _build_filters(
        award_type_codes=award_type_codes,
        awarding_agency=awarding_agency,
        funding_agency=funding_agency,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        def_codes=def_codes,
    )
    payload: dict[str, Any] = {
        "filters": filters,
        "limit": limit,
        "page": page,
        "order": order,
    }
    if sort:
        payload["sort"] = sort
    path = "/api/v2/search/spending_by_subaward_grouped/"
    result = await _post(path, payload)
    # Upstream hasNext is always false (verified live 2026-10-10: DHS
    # FY2026 page 2 at limit 5 returns 5 more primes, still hasNext false).
    # A full page means there may be more: ask for the single next row.
    rows = result.get("results") or []
    has_next = False
    if len(rows) >= limit:
        probe = await _post(path, {**payload, "limit": 1, "page": page * limit + 1})
        has_next = bool(probe.get("results"))
    meta = result.get("page_metadata") if isinstance(result.get("page_metadata"), dict) else {}
    result["page_metadata"] = {**meta, "page": page, "hasNext": has_next}
    periods = filters.get("time_period") or []
    window = "; ".join(f"{period['start_date']} through {period['end_date']}" for period in periods)
    scope = f" The requested filter window is {window}." if window else ""
    return _add_note(result, (
        "Filters select matching prime records. subaward_count and subaward_obligation "
        "are cumulative reported totals for those primes, not subaward actions limited "
        "to the requested date window; this is not a fiscal-period subaward ranking."
        + scope + " For dated results, pass award_generated_internal_id to "
        "search_subawards(award_id=...), read every page, and retain action_date values "
        "inside the desired period. FFATA reports may repeat cumulative amounts, so "
        "summing their reported amounts does not establish net new subcontract spending."
    ))


# ---------------------------------------------------------------------------
# Recipient depth
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Recipients", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def search_recipients(
    keyword: str | None = None,
    award_type: Literal["all", "contracts", "grants", "loans", "direct_payments", "other"] = "all",
    sort: Literal["amount", "name", "duns", "uei"] = "amount",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search USASpending recipients (vendors and grantees) by keyword.

    Returns paginated recipients with their UEI, DUNS, name, and a recipient
    'id' hash for get_recipient_profile() and new_awards_over_time().
    For get_recipient_children(), use the UEI (or legacy DUNS) from the
    parent (-P) row, not a recipient hash.

    keyword can match recipient name, UEI, or DUNS. If omitted, returns the
    top recipients ranked by `sort`.
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    keyword = _validate_no_control_chars(keyword, field="keyword")
    payload: dict[str, Any] = {
        "limit": limit,
        "page": page,
        "order": order,
        "sort": sort,
        "award_type": award_type,
    }
    if keyword and keyword.strip():
        payload["keyword"] = keyword.strip()
    result = await _post("/api/v2/recipient/", payload)
    return _add_note(result, "Recipient search amounts cover the trailing 12 months. Parent (-P) rows "
                     "include child (-C) rows; do not sum both levels. Recipient profiles use a separate "
                     "rollup and may differ from transaction-search totals or name matches.")


# Case-insensitive: the API accepts uppercase hex (verified live), and the
# lowercase-only version of this regex falsely rejected pasted uppercase
# hashes. We lowercase before sending so the wire format stays canonical.
_RECIPIENT_HASH_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-[CRP]$",
    re.IGNORECASE,
)


def _validate_recipient_hash(value: str, *, field: str = "recipient_hash") -> str:
    """USASpending recipient IDs look like '7fe0d08f-685f-...-R' (UUID + -C/-R/-P)."""
    if not value or not value.strip():
        raise ValueError(f"{field} cannot be empty.")
    s = value.strip()
    if not _RECIPIENT_HASH_RE.match(s):
        raise ValueError(
            f"{field}={value!r} is not a valid recipient hash. "
            f"Expected UUID format with -C/-R/-P suffix (e.g. "
            f"'7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22-R'). Use search_recipients() "
            f"to find the correct hash (its results carry it in the 'id' field; "
            f"autocomplete_recipient does not return hashes)."
        )
    # Canonical wire format: lowercase hex, uppercase level suffix.
    return s[:-1].lower() + s[-1].upper()


def _normalize_year(year: str | int | None, *, field: str = "year") -> str | None:
    """Coerce the recipient 'year' query param: int 2026 and str '2026' are
    both fine, as are the keywords 'all' and 'latest'. Returns None for
    None/blank so the param is omitted entirely."""
    if year is None:
        return None
    s = str(year).strip()
    return s or None


@mcp.tool(annotations={"title": "Get Recipient Profile", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_recipient_profile(
    recipient_hash: str,
    year: str | int | None = None,
) -> dict[str, Any]:
    """Get full profile for a recipient by their USASpending hash.

    Returns recipient details: name, UEI, DUNS, business categories, location,
    parent (if any), and lifetime award totals. The hash is the 'id' field
    returned by search_recipients(). (autocomplete_recipient does NOT return
    hashes; it is a name lookup only.)

    year: optional 'all' or a fiscal year like 2026 (int or str both
    accepted). Default is 'latest' (trailing 12 months). Parent (-P) totals
    include their children. Profiles use a separate recipient rollup and can
    differ from transaction searches by recipient_name and award-type scope.
    """
    recipient_hash = _validate_recipient_hash(recipient_hash)
    params = {}
    year_str = _normalize_year(year)
    if year_str:
        params["year"] = year_str
    return await _get(f"/api/v2/recipient/{recipient_hash}/", params=params)


_UEI_RE = re.compile(r"^[A-Z0-9]{12}$", re.IGNORECASE)
_DUNS_RE = re.compile(r"^\d{9}$")


@mcp.tool(annotations={"title": "Get Recipient Children", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_recipient_children(
    uei_or_duns: str,
    year: str | int | None = None,
) -> dict[str, Any]:
    """Get the child recipients (subsidiaries) of a parent recipient.

    Pass the parent recipient's 12-character UEI (or legacy 9-digit DUNS).
    Do NOT pass a recipient hash: the /recipient/children/ endpoint is the
    one recipient endpoint keyed by UEI/DUNS, and it rejects hashes with
    HTTP 400. Get the UEI from search_recipients() results (the 'uei' field
    of the -P row) or from get_recipient_profile().

    Returns the child recipients, each with its own -C suffixed recipient_id
    hash usable with get_recipient_profile(). Useful for mapping corporate
    structures (e.g. Lockheed Martin parent -> all its subsidiaries).

    year: optional 'all', 'latest', or a fiscal year like 2026.

    The upstream endpoint returns a JSON array; it is wrapped here as
    {"results": [...], "total": N} to keep the dict-only response invariant.
    """
    if not uei_or_duns or not str(uei_or_duns).strip():
        raise ValueError("uei_or_duns cannot be empty.")
    ident = str(uei_or_duns).strip()
    _validate_no_control_chars(ident, field="uei_or_duns")
    if _RECIPIENT_HASH_RE.match(ident):
        raise ValueError(
            f"uei_or_duns={uei_or_duns!r} looks like a recipient hash. The "
            f"children endpoint takes a UEI or DUNS, not a hash (the API "
            f"rejects hashes with HTTP 400). Use search_recipients() and pass "
            f"the 'uei' field of the parent (-P) row instead."
        )
    if _DUNS_RE.match(ident):
        pass  # legacy 9-digit DUNS, send as-is
    elif _UEI_RE.match(ident):
        ident = ident.upper()  # UEIs are canonically uppercase
    else:
        raise ValueError(
            f"uei_or_duns={uei_or_duns!r} is not a 12-character UEI or 9-digit "
            f"DUNS. Find the parent recipient's UEI via search_recipients()."
        )
    params = {}
    year_str = _normalize_year(year)
    if year_str:
        params["year"] = year_str
    # The endpoint returns a top-level JSON array (like /recipient/state/),
    # so this tool bypasses _get and wraps the array. Before the round 10
    # audit this call went through _get, whose dict-only guard would have
    # rejected every successful response; nobody noticed because the hash
    # validation above the call meant no request could ever succeed.
    return await _cached(
        "GET", f"/api/v2/recipient/children/{ident}/", _parse_recipient_children, params=params,
    )


def _parse_recipient_children(content: bytes) -> dict[str, Any]:
    data = _json.loads(content)
    if isinstance(data, list):
        return {"results": data, "total": len(data)}
    if isinstance(data, dict):
        return data
    raise RuntimeError(
        f"USASpending /recipient/children/ returned an unexpected "
        f"{type(data).__name__} (expected list or dict)."
    )


@mcp.tool(annotations={"title": "Autocomplete Recipient", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_recipient(
    search_text: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Find recipient names by partial name or UEI/DUNS.

    This is a recipient-name lookup; it does not supply the recipient hash
    for get_recipient_profile() or new_awards_over_time(), and its UEI/DUNS
    fields may be null. Pass a returned name to search_recipients(): use
    its 'id' hash for profiles/trends, and the UEI (or legacy DUNS) from
    the parent (-P) row for get_recipient_children().
    """
    limit = _clamp_limit(limit, cap=500)
    search_text = _validate_no_control_chars(search_text, field="search_text") or ""
    if not search_text.strip():
        raise ValueError("search_text cannot be empty.")
    payload = {"search_text": search_text.strip(), "limit": limit}
    return await _post("/api/v2/autocomplete/recipient/", payload)


@mcp.tool(annotations={"title": "List States", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def list_states() -> dict[str, Any]:
    """List all states with their FIPS codes and award totals.

    Returns the full list of US states/territories with FIPS codes you can
    pass to get_state_profile().

    The /recipient/state/ endpoint returns a JSON array (not an object). We
    wrap it in {"results": [...]} to keep the tool return type consistent
    with every other endpoint in this MCP.
    """
    return await _cached("GET", "/api/v2/recipient/state/", _parse_state_list)


def _parse_state_list(content: bytes) -> dict[str, Any]:
    data = _json.loads(content)
    if isinstance(data, list):
        return {"results": data, "total": len(data)}
    if isinstance(data, dict):
        return data
    raise RuntimeError(
        f"USASpending /recipient/state/ returned an unexpected "
        f"{type(data).__name__} (expected list or dict)."
    )


# ---------------------------------------------------------------------------
# Agency depth
# ---------------------------------------------------------------------------

def _validate_fy(fy: int | str | None, *, field: str = "fiscal_year") -> str | None:
    if fy is None:
        return None
    try:
        fy_int = int(str(fy).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an int year like 2026. Got {fy!r}.") from exc
    current = _current_fiscal_year()
    # Cap at the CURRENT fiscal year. The old bound of current + 1 let a
    # guaranteed-to-fail year through: the API 422s anything above the
    # current FY ("Field 'fiscal_year' value '2027' is above max '2026'").
    if fy_int < 2017 or fy_int > current:
        raise ValueError(
            f"{field}={fy_int} out of range. USASpending agency and federal "
            f"account profile data covers FY2017 through FY{current} "
            f"(the current fiscal year)."
        )
    return str(fy_int)


@mcp.tool(annotations={"title": "Get Agency Budgetary Resources", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_budgetary_resources(toptier_code: str) -> dict[str, Any]:
    """Get an agency's budgetary resources by fiscal year.

    Returns agency budgetary resources, obligations and outlays for each
    fiscal year on file, plus government-wide budgetary resources and the
    agency's obligations by reported fiscal period. This endpoint does not
    provide a discretionary-versus-mandatory breakdown.
    """
    toptier_code = _normalize_toptier(toptier_code)
    return await _get(f"/api/v2/agency/{toptier_code}/budgetary_resources/")


@mcp.tool(annotations={"title": "Get Agency Sub-Agencies", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_sub_agencies(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "total_obligations", "transaction_count", "new_award_count"] = "total_obligations",
) -> dict[str, Any]:
    """List the subordinate (subtier) organizations of a toptier agency.

    Returns each sub-agency with its obligations, transaction count, and
    new-award count for the given fiscal year. Useful for finding the
    canonical subtier name to pass into search_awards() awarding_subagency.

    sort accepts name, total_obligations, transaction_count, or
    new_award_count (this endpoint has no outlay column; a former
    'total_outlays' option was rejected by the API with HTTP 400).

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default, which right after October 1 holds only a
    few days of data). The answer always carries fiscal_year.
    """
    toptier_code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = str(_last_completed_fiscal_year()) if defaulted else _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {
        "page": str(page), "limit": str(limit), "order": order, "sort": sort, "fiscal_year": fy,
    }
    result = await _get(f"/api/v2/agency/{toptier_code}/sub_agency/", params=params)
    result = _add_note(result, _agency_dod_lag_note(toptier_code, fy))
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


@mcp.tool(annotations={"title": "Get Agency Federal Accounts", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_federal_accounts(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "obligated_amount", "gross_outlay_amount"] = "obligated_amount",
) -> dict[str, Any]:
    """List the Treasury Account Symbols (federal accounts) used by an agency.

    Returns each federal account with its obligated amount and gross outlay
    for the given fiscal year. Useful for understanding how an agency's
    money flows through Treasury.

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default, which right after October 1 holds only a
    few days of data). The answer always carries fiscal_year.
    """
    toptier_code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = str(_last_completed_fiscal_year()) if defaulted else _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {
        "page": str(page), "limit": str(limit), "order": order, "sort": sort, "fiscal_year": fy,
    }
    result = await _get(f"/api/v2/agency/{toptier_code}/federal_account/", params=params)
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


@mcp.tool(annotations={"title": "Get Agency Object Classes", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_object_classes(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "obligated_amount", "gross_outlay_amount"] = "obligated_amount",
) -> dict[str, Any]:
    """List the object class breakdown (what an agency spends money on).

    Object classes are OMB categories: Personnel Compensation, Travel,
    Contractual Services, Equipment, Grants, etc. Useful for understanding
    what types of expenditures an agency makes.

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default, which right after October 1 holds only a
    few days of data). The answer always carries fiscal_year.
    """
    toptier_code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = str(_last_completed_fiscal_year()) if defaulted else _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {
        "page": str(page), "limit": str(limit), "order": order, "sort": sort, "fiscal_year": fy,
    }
    result = await _get(f"/api/v2/agency/{toptier_code}/object_class/", params=params)
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


@mcp.tool(annotations={"title": "Get Agency Program Activities", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_program_activities(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "obligated_amount", "gross_outlay_amount"] = "obligated_amount",
) -> dict[str, Any]:
    """List the program activities (specific programs) within an agency.

    Program activities are the specific named programs that obligate funds
    (e.g., 'Cybersecurity and Infrastructure Security Agency'). Useful for
    pinpointing which program funds a specific activity.

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default, which right after October 1 holds only a
    few days of data). The answer always carries fiscal_year.
    """
    toptier_code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = str(_last_completed_fiscal_year()) if defaulted else _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {
        "page": str(page), "limit": str(limit), "order": order, "sort": sort, "fiscal_year": fy,
    }
    result = await _get(f"/api/v2/agency/{toptier_code}/program_activity/", params=params)
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


@mcp.tool(annotations={"title": "Get Agency Obligations by Award Category", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_agency_obligations_by_award_category(
    toptier_code: str,
    fiscal_year: int | str | None = None,
) -> dict[str, Any]:
    """Get an agency's obligation breakdown by award category.

    Returns total obligated dollars split by category: contracts, IDVs, grants,
    loans, direct payments, other. Quick way to see what mix of award types
    an agency uses (heavy contractor agency vs grant-issuing agency vs mixed).
    For DoD ('097') a fiscal year whose last 90 days are not yet published
    (DoD's 90-day delay) carries a data_note saying the total is understated.

    fiscal_year defaults to the last completed fiscal year, not the current
    one (USAspending's own default, which right after October 1 holds only a
    few days of data). The answer always carries fiscal_year.
    """
    toptier_code = _normalize_toptier(toptier_code)
    defaulted = fiscal_year is None
    fy = str(_last_completed_fiscal_year()) if defaulted else _validate_fy(fiscal_year)
    result = await _get(
        f"/api/v2/agency/{toptier_code}/obligations_by_award_category/",
        params={"fiscal_year": fy},
    )
    result = _add_note(result, _agency_dod_lag_note(toptier_code, fy))
    return _echo_fiscal_year(result, fy, defaulted=defaulted)


# ---------------------------------------------------------------------------
# Award depth
# ---------------------------------------------------------------------------

def _validate_generated_award_id(award_id: str, *, field: str = "award_id") -> str:
    """Generated award IDs look like 'CONT_AWD_W912QR25C0022_9700_...' or
    'CONT_IDV_GS00Q14OADU131_4732_...' or 'ASST_NON_FA86502125028_097'.
    """
    if not award_id or not award_id.strip():
        raise ValueError(f"{field} cannot be empty.")
    award_id = _validate_no_control_chars(award_id.strip(), field=field) or ""
    # These ids are interpolated into URL paths. Reject URL path
    # metacharacters outright: '..' segments walk the request onto other
    # API endpoints, '/' splits the path, '%' smuggles encoded forms of
    # both. Real generated ids never contain any of them. Round 10 audit
    # finding ('../references/toptier_agencies' returned the agency list
    # through get_award_detail).
    if any(tok in award_id for tok in ("/", "\\", "..", "%")):
        raise ValueError(
            f"{field}={award_id!r} contains URL path characters "
            f"('/', '\\\\', '..', or '%'). Generated award ids never contain "
            f"these; pass the id exactly as returned by search_awards()."
        )
    if not award_id.startswith(("CONT_AWD_", "CONT_IDV_", "ASST_NON_", "ASST_AGG_")):
        raise ValueError(
            f"{field}={award_id!r} is not a valid generated award id. "
            f"Expected prefix: CONT_AWD_, CONT_IDV_, ASST_NON_, or ASST_AGG_. "
            f"Find the right id from search_awards() results."
        )
    return award_id


@mcp.tool(annotations={"title": "Get Award Funding Rollup", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_funding_rollup(award_id: str) -> dict[str, Any]:
    """Get a rollup of an award's funding totals.

    Returns total transaction obligated amount, awarding agency count,
    funding agency count, and federal account count for a single award.
    Useful for a one-line summary of an award's funding picture.
    """
    award_id = _validate_generated_award_id(award_id)
    result = await _post("/api/v2/awards/funding_rollup/", {"award_id": award_id})
    return _add_note(result, "File C funding can be partial or lagged; this rollup is not "
                     "the full award obligation or amount paid. Compare with "
                     "get_award_detail total_obligation for award obligations.")


@mcp.tool(annotations={"title": "Get Award Subaward Count", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_subaward_count(award_id: str) -> dict[str, Any]:
    """Count of subawards (FFATA subcontracts/subawards) reported on an award."""
    award_id = _validate_generated_award_id(award_id)
    return await _get(f"/api/v2/awards/count/subaward/{award_id}/")


@mcp.tool(annotations={"title": "Get Award Federal Account Count", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_federal_account_count(award_id: str) -> dict[str, Any]:
    """Count of distinct federal accounts (TAS) funding an award."""
    award_id = _validate_generated_award_id(award_id)
    return await _get(f"/api/v2/awards/count/federal_account/{award_id}/")


@mcp.tool(annotations={"title": "Get Award Transaction Count", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_transaction_count(award_id: str) -> dict[str, Any]:
    """Count of transactions (modifications) on an award."""
    award_id = _validate_generated_award_id(award_id)
    return await _get(f"/api/v2/awards/count/transaction/{award_id}/")


@mcp.tool(annotations={"title": "Awards Last Updated", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def awards_last_updated() -> dict[str, Any]:
    """Get the timestamp of the last USASpending award data refresh.

    Use this to determine data freshness when comparing to other sources
    (SAM.gov Contract Awards API for example).
    """
    return await _get("/api/v2/awards/last_updated/")


# ---------------------------------------------------------------------------
# Search depth (transactions, geography, timeline)
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Spending by Transaction", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def spending_by_transaction(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    funding_agency: str | None = None,
    recipient_uei: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    sort: str = "Action Date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search at the transaction (modification) level.

    Unlike search_awards which returns one row per award, this returns one
    row per transaction (initial action plus every modification). Useful for
    tracking obligation events over time, ceiling adjustments, deobligations,
    and admin mods.

    recipient_uei is matched through the API's recipient text search (which
    covers name, UEI, and DUNS), so pass the plain 12-character UEI.

    Returns standard transaction fields: Action Date, Mod, Award ID,
    Action Type, Awarding Agency, Recipient Name.
    """
    codes = _resolve_award_type(award_type)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    filters = _build_filters(
        keywords=keywords,
        award_type_codes=codes,
        awarding_agency=awarding_agency,
        funding_agency=funding_agency,
        recipient_uei=recipient_uei,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        award_amount_min=award_amount_min,
        award_amount_max=award_amount_max,
    )
    fields = [
        "Action Date", "Mod", "Award ID", "Action Type",
        "Awarding Agency", "Recipient Name", "Transaction Amount",
        "Transaction Description", "internal_id", "generated_internal_id",
    ]
    payload = {
        "filters": filters, "fields": fields,
        "sort": sort, "order": order, "limit": limit, "page": page,
    }
    result = await _post("/api/v2/search/spending_by_transaction/", payload)
    return _add_note(result, _dod_lag_note(
        _window_end(time_period_start, time_period_end),
        agencies=(awarding_agency, funding_agency), award_types=award_type,
    ))


@mcp.tool(annotations={"title": "Spending by Geography", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def spending_by_geography(
    scope: Literal["recipient_location", "place_of_performance"] = "place_of_performance",
    geo_layer: Literal["state", "county", "district"] = "state",
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other", "all"] = "all",
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    awarding_agency: str | None = None,
    funding_agency: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    def_codes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Geographic breakdown of spending.

    scope: 'recipient_location' (where the recipient is) or 'place_of_performance'
    (where the work happens).
    geo_layer: 'state', 'county', or 'district'.

    At least one filter is required. The API returns HTTP 500 on an empty
    filter set, so the requirement is enforced here with a clear error.
    """
    codes = None if award_type == "all" else _resolve_award_type(award_type)
    filters = _build_filters(
        award_type_codes=codes,
        awarding_agency=awarding_agency,
        funding_agency=funding_agency,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        def_codes=def_codes,
    )
    # Same guard as search_awards. Unfiltered calls 500 upstream; award_type
    # alone is a scope, not a filter.
    has_real_filter = any(k for k in filters if k != "award_type_codes")
    if not has_real_filter:
        raise ValueError(
            "spending_by_geography requires at least one filter beyond award_type. "
            "Typical: time_period_start + time_period_end, or awarding_agency, "
            "or naics_codes/psc_codes."
        )
    payload = {"filters": filters, "scope": scope, "geo_layer": geo_layer}
    result = await _post("/api/v2/search/spending_by_geography/", payload)
    return _add_note(result, _dod_lag_note(
        _window_end(time_period_start, time_period_end),
        agencies=(awarding_agency, funding_agency), award_types=award_type,
    ))


@mcp.tool(annotations={"title": "New Awards Over Time", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def new_awards_over_time(
    recipient_id: str,
    group: Literal["fiscal_year", "quarter", "month"] = "month",
    time_period_start: str | None = None,
    time_period_end: str | None = None,
) -> dict[str, Any]:
    """Pipeline trend of new awards to a recipient over time.

    REQUIRES recipient_id (the recipient hash with -P suffix for parent-level
    rollup, or -R for a single recipient). Returns counts of new awards
    grouped by month, quarter, or fiscal year.

    The endpoint rejects calls without recipient_id with HTTP 422, and it
    also requires a time_period. When you omit the dates, a default range
    covering all searchable data (2007-10-01 through 2099-09-30) is sent
    automatically.
    """
    recipient_id = _validate_recipient_hash(recipient_id, field="recipient_id")
    filters: dict[str, Any] = {"recipient_id": recipient_id}
    # The API requires filters.time_period (HTTP 422 "'filters|time_period'
    # is a required field" otherwise, verified live 2026-08-16), so always
    # send one, defaulting to the full searchable range.
    start = _validate_date(time_period_start, "time_period_start") if time_period_start else _EARLIEST_SEARCH_DATE
    end = _validate_date(time_period_end, "time_period_end") if time_period_end else "2099-09-30"
    if start > end:
        raise ValueError(
            f"time_period_start ({start}) is after time_period_end ({end}). "
            f"Reverse the values or omit one."
        )
    filters["time_period"] = [{"start_date": start, "end_date": end}]
    # The upstream annual histogram uses calendar years but labels them
    # fiscal_year. Its quarter/month histograms correctly use federal FYs.
    # Counts are exact distinct award_ids, each with one date_signed, so
    # fiscal quarters partition these new awards without double counting.
    source_group = "quarter" if group == "fiscal_year" else group
    payload = {"group": source_group, "filters": filters}
    result = await _post("/api/v2/search/new_awards_over_time/", payload)
    if group == "fiscal_year":
        by_year: dict[str, int] = {}
        for row in result["results"]:
            year = row["time_period"]["fiscal_year"]
            by_year[year] = by_year.get(year, 0) + row["new_award_count_in_period"]
        result = {
            **result,
            "group": "fiscal_year",
            "results": [
                {"new_award_count_in_period": by_year[year],
                 "time_period": {"fiscal_year": year}}
                for year in sorted(by_year, key=int)
            ],
        }
    result = _add_note(result, _dod_lag_note(end, award_types=None))
    if isinstance(result, dict):
        result["time_period_note"] = (
            "Buckets use federal fiscal years (October through September): month 1 "
            "is October, month 12 is September; quarter 1 is October-December. "
            "Only the requested date window is included, so a fiscal-year bucket "
            "can represent a partial year."
        )
    return result


# ---------------------------------------------------------------------------
# IDV depth
# ---------------------------------------------------------------------------

def _validate_idv_award_id(award_id: str, *, field: str = "award_id") -> str:
    """IDV-specific endpoints require CONT_IDV_ prefix."""
    award_id = _validate_generated_award_id(award_id, field=field)
    if not award_id.startswith("CONT_IDV_"):
        raise ValueError(
            f"{field}={award_id!r} is not an IDV award id (CONT_IDV_*). "
            f"This endpoint is IDV-only. For non-IDV contracts use the awards "
            f"endpoints instead."
        )
    return award_id


@mcp.tool(annotations={"title": "Get IDV Amounts", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_idv_amounts(award_id: str) -> dict[str, Any]:
    """Top-line amounts for an Indefinite Delivery Vehicle (IDV).

    Returns child IDV count, child award count, child award total obligation,
    and base/option values rolled up across all task/delivery orders under
    the IDV. Pass a CONT_IDV_* generated_internal_id.
    """
    award_id = _validate_idv_award_id(award_id)
    result = await _get(f"/api/v2/idvs/amounts/{award_id}/")
    return _add_note(result, "Child award obligations and option values describe reported "
                     "contracts; child account obligations and outlays come from File C "
                     "and can be partial or lagged. File C outlays do not establish the "
                     "amount paid to each contractor.")


@mcp.tool(annotations={"title": "Get IDV Funding", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_idv_funding(
    award_id: str,
    sort: Literal["reporting_fiscal_date", "transaction_obligated_amount", "piid"] = "reporting_fiscal_date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """List File C funding records associated with an IDV.

    Rows can identify the IDV itself as well as associated awards; they are
    not a complete list of child orders. File C coverage can be partial or
    lagged and does not establish the full child-order obligation or amount
    paid. Use get_idv_amounts() for reported child-order obligation totals
    and get_idv_activity() or get_idv_children() for child-order records.
    """
    award_id = _validate_idv_award_id(award_id)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    payload = {
        "award_id": award_id, "sort": sort, "order": order,
        "limit": limit, "page": page,
    }
    result = await _post("/api/v2/idvs/funding/", payload)
    return _add_note(result, "File C funding records associated with this IDV can be partial "
                     "or lagged; they do not establish the full child-order obligation or "
                     "amount paid. Use get_idv_amounts for child-order obligation totals.")


@mcp.tool(annotations={"title": "Get IDV Funding Rollup", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_idv_funding_rollup(award_id: str) -> dict[str, Any]:
    """Funding rollup totals for an IDV (single dict, not paginated)."""
    award_id = _validate_idv_award_id(award_id)
    result = await _post("/api/v2/idvs/funding_rollup/", {"award_id": award_id})
    return _add_note(result, "File C funding can be partial or lagged; this rollup is not "
                     "the full child-order obligation or amount paid. Compare with "
                     "get_idv_amounts for child-order obligation totals.")


@mcp.tool(annotations={"title": "Get IDV Activity", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_idv_activity(
    award_id: str,
    hide_edge_cases: bool = False,
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """List child task/delivery orders awarded under an IDV.

    Results are ALWAYS sorted by obligated amount, descending; the endpoint
    accepts no sort or order parameters. (Earlier releases exposed sort/order
    here, but the API silently ignored them: the advertised default of
    period_of_performance_start_date was never the actual ordering. Round 10
    audit finding.) For date-ordered children use get_idv_children(), whose
    endpoint does honor sort/order.

    hide_edge_cases=True filters out child awards missing obligated/awarded
    amounts or end dates.
    """
    award_id = _validate_idv_award_id(award_id)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    payload = {
        "award_id": award_id, "hide_edge_cases": hide_edge_cases,
        "limit": limit, "page": page,
    }
    return await _post("/api/v2/idvs/activity/", payload)


# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------

def _autocomplete_payload(search_text: str, limit: int) -> dict[str, Any]:
    search_text = _validate_no_control_chars(search_text, field="search_text") or ""
    if not search_text.strip():
        raise ValueError("search_text cannot be empty.")
    return {"search_text": search_text.strip(), "limit": _clamp_limit(limit, cap=500)}


@mcp.tool(annotations={"title": "Autocomplete Awarding Agency", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_awarding_agency(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find awarding agency names by partial match.

    USASpending search filters require the EXACT awarding agency name
    (slugs return zero). Use this to resolve a partial name to the canonical
    one before passing to search_awards() awarding_agency parameter.
    """
    return await _post("/api/v2/autocomplete/awarding_agency/", _autocomplete_payload(search_text, limit))


@mcp.tool(annotations={"title": "Autocomplete Funding Agency", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_funding_agency(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find funding agency names by partial match (companion to awarding agency)."""
    return await _post("/api/v2/autocomplete/funding_agency/", _autocomplete_payload(search_text, limit))


@mcp.tool(annotations={"title": "Autocomplete CFDA", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_cfda(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find CFDA (Catalog of Federal Domestic Assistance) program numbers
    by partial title or program number. CFDA codes are used in grants."""
    return await _post("/api/v2/autocomplete/cfda/", _autocomplete_payload(search_text, limit))


@mcp.tool(annotations={"title": "Autocomplete Glossary", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def autocomplete_glossary(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find glossary terms (acquisition + spending vocabulary) by partial match."""
    return await _post("/api/v2/autocomplete/glossary/", _autocomplete_payload(search_text, limit))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Get Award Types Reference", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_award_types_reference() -> dict[str, Any]:
    """Return the full mapping of award type codes to descriptions.

    Returns the canonical reference: contracts (A=BPA Call, B=Purchase Order,
    C=Delivery Order, D=Definitive Contract), IDVs, grants, loans, etc.
    Authoritative source if you're unsure what a code letter means.
    """
    return await _get("/api/v2/references/award_types/")


@mcp.tool(annotations={"title": "Get DEF Codes Reference", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_def_codes_reference() -> dict[str, Any]:
    """Return all Disaster Emergency Fund (DEFC) codes with public laws.

    DEFCs are used to filter awards funded by specific supplemental
    appropriations (COVID-19, IIJA, IRA, etc.).
    """
    return await _get("/api/v2/references/def_codes/")


@mcp.tool(annotations={"title": "Get Glossary", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_glossary(
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    """Get the full USASpending glossary of acquisition + spending terms."""
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=500)
    return await _get("/api/v2/references/glossary/", params={"page": str(page), "limit": str(limit)})


@mcp.tool(annotations={"title": "Get Submission Periods", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_submission_periods() -> dict[str, Any]:
    """List the reporting calendar and submission/certification deadlines.

    Returns available fiscal reporting periods and their scheduled start,
    due, certification and reveal dates. These are global calendar periods,
    not records of when individual agencies actually submitted or certified
    data. A listed period does not establish complete agency data coverage.
    """
    result = await _get("/api/v2/references/submission_periods/")
    return _add_note(result, "These are reporting-calendar periods and submission/certification "
                     "deadlines, not records of when individual agencies actually submitted "
                     "or certified data. A listed period does not establish complete agency "
                     "data coverage.")


# ---------------------------------------------------------------------------
# Federal accounts
# ---------------------------------------------------------------------------

_TAS_RE = re.compile(r"^[\w\-]+$")


def _validate_tas(tas: str, *, field: str = "account_code") -> str:
    if not tas or not tas.strip():
        raise ValueError(f"{field} cannot be empty.")
    s = tas.strip()
    if not _TAS_RE.match(s):
        raise ValueError(
            f"{field}={tas!r} contains invalid characters. Treasury account "
            f"symbols look like '097-0100' or similar alphanumeric/hyphen."
        )
    return s


@mcp.tool(annotations={"title": "List Federal Accounts", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def list_federal_accounts(
    keyword: str | None = None,
    fiscal_year: int | str | None = None,
    sort: dict[str, str] | None = None,
    page: int = 1,
    limit: int = 25,
) -> dict[str, Any]:
    """List Treasury federal accounts (TAS) with budgetary resources.

    keyword filters by account name or AID. fiscal_year controls the reported
    budgetary-resource values, not which account rows are included. When
    omitted, the source uses its latest available fiscal year, which may
    differ from the current fiscal year; check the returned fy value.
    sort is a dict like {'field':'budgetary_resources','direction':'desc'}.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    keyword = _validate_no_control_chars(keyword, field="keyword")
    fy = _validate_fy(fiscal_year)
    payload: dict[str, Any] = {"page": page, "limit": limit}
    if keyword and keyword.strip():
        payload["keyword"] = keyword.strip()
    if fy:
        payload["filters"] = {"fy": fy}
    if sort:
        payload["sort"] = sort
    try:
        return await _post("/api/v2/federal_accounts/", payload)
    except RuntimeError as exc:
        # A normal current-FY request can precede source reporting availability.
        # Only the authoritative available-year rejection is an anticipated
        # tool error; keep unrelated failures on their existing path.
        source_error = exc.__cause__
        if fy and isinstance(source_error, httpx.HTTPStatusError) and source_error.response.status_code == 400:
            try:
                source_body = source_error.response.json()
            except ValueError:
                source_body = None
            detail = source_body.get("detail") if isinstance(source_body, dict) else None
            if isinstance(detail, str) and re.fullmatch(
                r"Field 'filters' is outside valid values \[(?:'\d{4}'(?:, )?)+\]", detail,
            ):
                available = re.findall(r"'(\d{4})'", detail)
                if fy not in available:
                    raise ToolError(
                        f"{exc}. Requested fiscal year {fy} is not available from the source. "
                        "Omit fiscal_year to retrieve the source's latest available year, "
                        "and check the returned fy before interpreting its resource values."
                    ) from exc
        raise


@mcp.tool(annotations={"title": "Get Federal Account Detail", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_federal_account_detail(account_code: str) -> dict[str, Any]:
    """Get an individual federal account's metadata + budgetary resources."""
    account_code = _validate_tas(account_code)
    return await _get(f"/api/v2/federal_accounts/{account_code}/")


@mcp.tool(annotations={"title": "Get Federal Account Object Classes", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_federal_account_object_classes(account_code: str) -> dict[str, Any]:
    """Get the object class breakdown of obligations for a federal account.

    IMPORTANT: the returned obligations are CUMULATIVE across all reported
    fiscal years (FY2017 onward, the DATA Act window), not a single year.
    They are NOT comparable to get_federal_account_fy_snapshot(), which is
    single-year (verified live: account 021-0725 summed to $3.38B here vs
    $0.42B obligated in its FY2024 snapshot). The upstream endpoint has no
    year control: a fiscal_year body parameter is accepted but ignored, so
    none is exposed here.

    Note: this endpoint requires POST (not GET like the other federal account
    sub-endpoints). Live audit caught this; the body is empty.
    """
    account_code = _validate_tas(account_code)
    return await _post(f"/api/v2/federal_accounts/{account_code}/object_classes/total/", {})


@mcp.tool(annotations={"title": "Get Federal Account Program Activities", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_federal_account_program_activities(
    account_code: str,
    fiscal_year: int | str | None = None,
) -> dict[str, Any]:
    """List program activity codes and names associated with a federal account.

    The source lists distinct programs across all reported fiscal years; it
    has no fiscal-year filter and includes no dollar amounts. fiscal_year is
    retained for compatibility, but does not filter this list. The response
    explicitly discloses any requested year that was not applied.

    Retrieves source pages internally, up to 2,000 records, and reports whether
    the list is complete. For single-year account resources and obligations,
    use get_federal_account_fy_snapshot with the numeric account_id returned
    by list_federal_accounts. get_agency_program_activities provides fiscal-year
    program amounts for an agency, not for this individual federal account.
    """
    account_code = _validate_tas(account_code)
    fy = _validate_fy(fiscal_year)
    results: list[dict[str, Any]] = []
    first: dict[str, Any] | None = None
    complete = False
    for page in range(1, 21):
        part = await _get(
            f"/api/v2/federal_accounts/{account_code}/program_activities/",
            params={"page": page, "limit": 100},
        )
        if "results" not in part:
            return part
        if first is None:
            first = part
        results.extend(part["results"])
        metadata = part.get("page_metadata", {})
        if not metadata.get("hasNext"):
            complete = True
            break
    assert first is not None
    result = {**first, "results": results}
    if page > 1:
        result["page_metadata"] = {
            **first["page_metadata"], "page": 1, "limit": len(results),
            "next": None if complete else metadata.get("next"),
            "hasNext": not complete,
        }
    result.update(
        requested_fiscal_year=fy,
        fiscal_year_filter_applied=False,
        program_activity_scope="all_reported_fiscal_years",
        program_activity_list_complete=complete,
        source_pages_retrieved=page,
    )
    note = (
        "Program activity codes and names span all reported fiscal years; "
        "this source does not filter by fiscal year or return program dollar amounts. "
    )
    if fy:
        note += f"The requested FY{fy} was not applied to this list. "
    if complete:
        note += f"The complete source list contains {len(results)} records. "
    else:
        note += "Only the first 2,000 source records were retrieved; the list is incomplete. "
    note += (
        "For single-year account resources and obligations, use "
        "get_federal_account_fy_snapshot with the numeric account_id from "
        "list_federal_accounts. get_agency_program_activities returns "
        "fiscal-year amounts for the whole agency, not this account."
    )
    return _add_note(result, note)


@mcp.tool(annotations={"title": "Get Federal Account Fiscal Year Snapshot", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_federal_account_fy_snapshot(
    account_id: int | str,
    fiscal_year: int | str | None = None,
) -> dict[str, Any]:
    """Get a single-fiscal-year snapshot of a federal account's resources.

    Important: this endpoint takes the numeric `account_id` (e.g. 4595), NOT
    the alphanumeric `account_number` (e.g. "027-5183") used by the other
    federal-account endpoints. The list_federal_accounts response includes
    both fields per record. Pass the integer account_id here.
    """
    aid = str(account_id).strip()
    if not aid:
        raise ValueError("account_id cannot be empty.")
    if not aid.lstrip("-").isdigit():
        raise ValueError(
            f"account_id={account_id!r} must be a numeric integer ID (e.g. 4595). "
            f"This endpoint differs from get_federal_account_detail which takes "
            f"the alphanumeric account_number. Pull both fields from "
            f"list_federal_accounts and pass the right one to each tool."
        )
    fy = _validate_fy(fiscal_year)
    if fy:
        return await _get(f"/api/v2/federal_accounts/{aid}/fiscal_year_snapshot/{fy}/")
    return await _get(f"/api/v2/federal_accounts/{aid}/fiscal_year_snapshot/")


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _apply_tool_profile() -> None:
    """Expose either the complete catalog or the acquisition-agent subset."""
    profile = os.environ.get(USASPENDING_TOOL_PROFILE_ENV, "full").strip() or "full"
    if profile == "full":
        return
    if profile != "acquisition-agent":
        raise RuntimeError(
            f"Unknown {USASPENDING_TOOL_PROFILE_ENV}={profile!r}. "
            "Supported profiles are 'full' and 'acquisition-agent'."
        )

    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
    missing = ACQUISITION_AGENT_TOOLS - registered
    if missing:
        raise RuntimeError(
            "The acquisition-agent USASpending profile references unregistered "
            f"tools: {', '.join(sorted(missing))}."
        )
    for tool_name in registered - ACQUISITION_AGENT_TOOLS:
        mcp.remove_tool(tool_name)

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_awards(keyword='cyber') (real
    param is `search_text`) would succeed with the typo discarded and
    return unfiltered data. extra='forbid' raises "Extra inputs are not
    permitted" on typos before any HTTP call.
    """
    for tool in mcp._tool_manager.list_tools():
        am = tool.fn_metadata.arg_model
        am.model_config = {**am.model_config, "extra": "forbid"}
        am.model_rebuild(force=True)


_apply_tool_profile()
_forbid_extra_params_on_all_tools()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
