# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""GSA CALC+ MCP server.

Provides access to awarded GSA MAS schedule ceiling rates for labor
categories. No authentication required.

These are NOT-TO-EXCEED hourly rates from GSA MAS contracts, not prices
paid or BLS wages. Use for IGCE development, price reasonableness
determinations, and market research.

Data refreshes nightly from GSA MAS contract price proposal tables.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from typing import Any, Literal, Union

import httpx
from mcp.server import MCPServer
from pydantic import BeforeValidator
from typing_extensions import Annotated

from . import __version__
from ._throughput import GsaCalcPacer, CalcBudgetUnavailable
from ._response_cache import HOUR, ResponseCache, cache_key
from mcp.server.mcpserver.exceptions import ToolError
from .constants import (
    BASE_URL,
    DEFAULT_TIMEOUT,
    EDUCATION_LEVELS,
    LOW_SAMPLE_MIN_RATES,
    MAX_PAGE_SIZE,
    ORDERING_FIELDS,
    USER_AGENT,
)

class UserInputError(ValueError, ToolError):
    """Expected user-input failure with recoverable guidance on MCP 2.x."""


mcp = MCPServer("gsa-calc", version=__version__)


# ---------------------------------------------------------------------------
# Defensive response parsing helpers
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict[str, Any]:
    """Return value if it's a dict, else empty dict. Tolerates None, list, str."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Return value as a list. XML-to-JSON collapse tolerant."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _safe_bucket_key(b: Any) -> tuple[Any, Any] | None:
    """Extract (key, doc_count) from a bucket item. Returns None if invalid."""
    if not isinstance(b, dict):
        return None
    key = b.get("key")
    count = b.get("doc_count")
    if key is None or count is None:
        return None
    return (key, count)


def _safe_number(value: Any) -> float | int | None:
    """Coerce to a real number, rejecting None, NaN, Inf. Used for stats values."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


# ---------------------------------------------------------------------------
# Input validators
# ---------------------------------------------------------------------------

_ASCII_PRINTABLE_SAFE_RE = re.compile(r"^[A-Za-z0-9 \-_,.:/()&#+|*@$]*$")

# WAF triggers for GSA CALC's firewall. The 0.2.0 filter was copied from
# sam-gov-mcp and included many false positives. Live-verified in the 0.2.1
# audit: GSA CALC accepts apostrophes, backticks, semicolons, and SQL
# keywords as literal search text (e.g. "O'Reilly Labor Category" now works).
# The only patterns that genuinely trigger a 403 are angle brackets,
# path traversal, and null bytes.
_WAF_PATTERNS = [
    (re.compile(r"\.\./"), "path traversal ('../')"),
    (re.compile(r"<[a-z/]", re.IGNORECASE), "HTML angle brackets"),
    (re.compile(r"\x00"), "null byte"),
]

# Control chars (null byte, newline, tab, CR, backspace, etc.). These reach
# the GSA API URL-encoded and produce silent zero-result queries when they
# were unintentional (copy-paste artifacts, accidental whitespace). Check
# BEFORE strip(), which would eat \n/\r/\t and hide the problem.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _validate_no_control_chars(value: Any, *, field: str) -> Any:
    """Reject strings containing control characters.

    Must be called BEFORE any strip() -- strip() eats \\n, \\r, \\t and masks
    the problem, while the downstream API still sees URL-encoded control
    chars from the internal portion of multi-line input.
    """
    if value is None:
        return None
    if isinstance(value, str) and _CONTROL_CHARS_RE.search(value):
        raise UserInputError(
            f"{field}={value!r} contains control characters "
            f"(null byte / newline / tab / CR / backspace). These typically come "
            f"from copy-paste artifacts and cause silent zero-result queries. "
            f"Remove them and retry."
        )
    return value


def _validate_waf_safe(value: str | None, *, field: str) -> str | None:
    """Reject strings containing characters that trigger GSA's WAF."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    for pattern, description in _WAF_PATTERNS:
        if pattern.search(value):
            raise UserInputError(
                f"{field}={value!r} contains characters that trigger GSA CALC+'s "
                f"web application firewall ({description}). Remove the offending "
                f"characters and try again (empirically: quotes, SQL keywords, "
                f"angle brackets, path traversal, semicolons all trigger 403/503)."
            )
    return value


def _validate_finite(value: float | int | None, *, field: str) -> float | int | None:
    """Reject NaN/Inf in numeric fields. pydantic's `float` type accepts both."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise UserInputError(f"{field} must be a number, not a boolean. Got {value!r}.")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise UserInputError(
            f"{field} must be a finite number. Got {value!r}. "
            f"NaN/Inf reach the API URL-encoded and return HTTP 406."
        )
    return value


def _clamp_text_len(value: str | None, *, field: str, maximum: int = 500) -> str | None:
    """Length-check free-text fields. GSA returns 406 on >500-char strings."""
    if value is None:
        return None
    if len(value) > maximum:
        raise UserInputError(
            f"{field} exceeds {maximum} chars ({len(value)}). Very long strings "
            f"trigger HTTP 406 URI-too-long errors from GSA."
        )
    return value


def _strip_or_none(value: str | None) -> str | None:
    """Strip whitespace; return None if result is empty."""
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else str(value).strip()
    return s or None


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise UserInputError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise UserInputError(
            f"{field} exceeds maximum of {hi}. Got {value}. Paginate instead."
        )
    return value


# GSA CALC is backed by Elasticsearch with a 10,000-result window
# (index.max_result_window default). Requests where page * page_size > 10,000
# return HTTP 406. Pre-clamp locally with a clear message instead of
# round-tripping to a cryptic API error.
_ES_MAX_WINDOW = 10_000


def _validate_es_window(page: int, page_size: int) -> None:
    if page * page_size > _ES_MAX_WINDOW:
        raise UserInputError(
            f"page ({page}) * page_size ({page_size}) = {page * page_size} exceeds "
            f"GSA CALC+'s 10,000-result Elasticsearch window. Narrow your search "
            f"with filters (education_level, sin, price_range) to get under 10k results, "
            f"or use suggest_contains() to find exact vendor/category names first."
        )


def _attach_pagination_flags(response: dict[str, Any], *, page: int, page_size: int, total: int | None) -> dict[str, Any]:
    """Mark responses that are empty because we paged past the end vs truly no data.

    Without this, an empty 'hits' on page 100 of a 50-record query looks the same
    as a zero-match query, and callers mistakenly conclude there's no market data.
    """
    if not isinstance(response, dict):
        return response
    if not isinstance(total, int) or total <= 0:
        return response
    offset = (page - 1) * page_size
    if offset >= total:
        last_page = max(1, (total + page_size - 1) // page_size)
        response["paged_past_end"] = True
        response["paged_past_end_reason"] = (
            f"No data on page {page}; last page with data is page {last_page} "
            f"({total} total records at page_size {page_size})."
        )
    return response


def _validate_ordering(value: str | None) -> str:
    """Validate against ORDERING_FIELDS whitelist. Returns default if None."""
    if value is None:
        return "current_price"
    s = value.strip() if isinstance(value, str) else str(value).strip()
    if not s:
        return "current_price"
    if s not in ORDERING_FIELDS:
        raise UserInputError(
            f"ordering={value!r} is not a valid field. "
            f"Valid: {', '.join(ORDERING_FIELDS)}."
        )
    return s


def _validate_sort(value: str) -> str:
    if value is None:
        return "asc"
    s = value.strip().lower() if isinstance(value, str) else str(value).strip().lower()
    if s not in ("asc", "desc"):
        raise UserInputError(f"sort must be 'asc' or 'desc'. Got {value!r}.")
    return s


def _validate_education_level(value: str | None) -> str | None:
    """Validate an education level. Supports pipe-delimited OR (e.g. 'BA|MA')."""
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else str(value).strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split("|")]
    for p in parts:
        if not p:
            raise UserInputError(f"education_level {value!r} has an empty entry between pipes.")
        if p not in EDUCATION_LEVELS:
            valid = ", ".join(sorted(EDUCATION_LEVELS.keys()))
            raise UserInputError(
                f"education_level entry {p!r} not valid. Valid codes: {valid}. "
                f"Pipe-delimit for OR (e.g. 'BA|MA')."
            )
    return "|".join(parts)


def _validate_worksite(value: str | None) -> None:
    """Reject any worksite value: the CALC+ v3 API silently ignores this filter.

    Live-verified in the 1.0.1 audit: every value (the old Customer /
    Contractor / Both enum, the raw v3 data values Customer_Facility /
    Contractor_Facility / Virtual, a space form, a top-level worksite=
    param, and a site: filter) returned identical unfiltered totals.
    Accepting the parameter meant answering a customer-site-only question
    with all-site statistics. Raise loudly until GSA supports the filter.
    """
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else str(value).strip()
    if not s:
        return None
    raise UserInputError(
        "worksite filtering is not supported by the CALC+ v3 API; the filter "
        "is silently ignored upstream (every value returns unfiltered "
        "results). Remove the worksite argument. The underlying data does "
        "carry a worksite field (Customer_Facility, Contractor_Facility, "
        "Virtual), so individual hit records still show it."
    )


def _reject_bool_pre(value: Any) -> Any:
    """pydantic BeforeValidator that rejects booleans before Union coercion.

    Needed because `Union[str, int, None]` accepts bool (True/False) and
    coerces to int 1/0 before our server-side validator runs. The coerced
    value passes the alphanumeric regex and reaches the API as 'sin:1' /
    'sin:0', silently producing zero-match queries.
    """
    if isinstance(value, bool):
        raise UserInputError(
            f"Expected a string or int, not a boolean. Got {value!r}. "
            f"This usually means the caller passed the wrong argument type."
        )
    return value


SinInput = Annotated[Union[str, int, None], BeforeValidator(_reject_bool_pre)]


def _validate_sin(value: Any) -> str | None:
    """SIN codes are alphanumeric (e.g., '54151S', '541330ENG'). No special chars."""
    if value is None:
        return None
    # Reject booleans explicitly: True/False coerce via int to "1"/"0" and
    # pass the alphanumeric regex, silently producing a zero-match query.
    if isinstance(value, bool):
        raise UserInputError(
            f"sin={value!r} is a boolean, not a SIN. "
            f"Pass a string like '54151S' or an int like 541611."
        )
    s = str(value).strip()
    if not s:
        return None
    if len(s) > 20:
        raise UserInputError(
            f"sin={value!r} exceeds 20 chars ({len(s)}). Real SINs are <=10 chars "
            f"(e.g. '54151S', '541330ENG')."
        )
    if not re.match(r"^[A-Za-z0-9]+$", s):
        raise UserInputError(
            f"sin={value!r} must be alphanumeric (e.g. '54151S', '541330ENG'). "
            f"No spaces or special characters."
        )
    return s


def _validate_experience_range(emin: int | None, emax: int | None) -> tuple[int | None, int | None]:
    emin = _validate_finite(emin, field="experience_min")
    emax = _validate_finite(emax, field="experience_max")
    if emin is not None and emin < 0:
        raise UserInputError(f"experience_min must be >= 0. Got {emin}.")
    if emax is not None and emax < 0:
        raise UserInputError(f"experience_max must be >= 0. Got {emax}.")
    if emin is not None and emax is not None and emin > emax:
        raise UserInputError(
            f"experience_min ({emin}) must be <= experience_max ({emax})."
        )
    return emin, emax


def _validate_price_range(pmin: float | None, pmax: float | None) -> tuple[float | None, float | None]:
    pmin = _validate_finite(pmin, field="price_min")
    pmax = _validate_finite(pmax, field="price_max")
    if pmin is not None and pmin < 0:
        raise UserInputError(f"price_min must be >= 0. Got {pmin}.")
    if pmax is not None and pmax <= 0:
        # price_max=0 builds price_range:0,0, which matches nothing and
        # returns a silent zero-result response. Reject locally.
        raise UserInputError(
            f"price_max must be > 0. Got {pmax}. A zero or negative ceiling "
            f"matches no rates and returns silent empty results."
        )
    if pmin is not None and pmax is not None and pmin > pmax:
        raise UserInputError(
            f"price_min (${pmin}) must be <= price_max (${pmax})."
        )
    return pmin, pmax


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML bodies from upstream error responses for clean messages."""
    if not text:
        return ""
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
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
_pacer = GsaCalcPacer()
# Hosted only (MCP_RESPONSE_CACHE=1). GSA refreshes CALC+ ceiling rates once a
# day overnight, so 12 hours keeps an answer at most one refresh behind.
_cache = ResponseCache(max_bytes=48 * 1024 * 1024, max_entry_bytes=4 * 1024 * 1024)
_CACHE_SECONDS = 12 * HOUR


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: str) -> str:
    cleaned = _clean_error_body(body)
    if status == 403:
        return (
            "HTTP 403: Forbidden. GSA's web application firewall blocked this request. "
            "This typically happens when the query contains characters that look like "
            "injection attempts (single quotes, angle brackets, path traversal sequences). "
            "Remove special characters from your search terms and try again."
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. Common causes: (1) keyword or query string "
            "is too long; (2) page number is out of valid range; (3) ordering field "
            "name is invalid. Valid ordering: "
            f"{', '.join(ORDERING_FIELDS)}. "
            f"API response: {cleaned}"
        )
    if status == 429:
        return (
            "HTTP 429: GSA CALC+ rate limited the request. The provider does "
            "not publish a numeric limit for this endpoint. Do not retry in a "
            "burst; wait for provider guidance and reduce batch concurrency."
        )
    if status == 503:
        return (
            "HTTP 503: GSA upstream service unavailable. This often happens when "
            "the request URL contains characters that trigger their firewall. "
            "Remove special characters (quotes, angle brackets, SQL keywords) and retry."
        )
    if status == 400:
        return f"HTTP 400: Bad request. Check filter format (field:value) and page_size (max 500). API response: {cleaned}"
    return f"HTTP {status}: {cleaned}"


async def _get(params_str: str) -> dict[str, Any]:
    """GET helper. Builds full URL from query string."""
    url = f"{BASE_URL}?{params_str}"
    try:
        return await _cache.get_or_fetch(
            cache_key("GET", url), _CACHE_SECONDS, lambda: _fetch(url), _parse_body,
        )
    except CalcBudgetUnavailable as e:
        raise ToolError(str(e)) from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling GSA CALC+: {e}") from e


async def _fetch(url: str) -> bytes:
    """One paced GSA CALC+ request; only cache misses get here."""
    async with _pacer.request_slot() as pacing:
        r = await _get_client().get(url)
        pacing.observe_response(r)
        try:
            pacing.raise_if_rate_limited(
                r,
                service="GSA CALC+",
                guidance=_format_error(r.status_code, r.text[:500]),
            )
        except RuntimeError as e:
            # This helper raises only for an expected provider 429. Show
            # its retry guidance while keeping unrelated crashes masked.
            raise ToolError(str(e)) from e
    r.raise_for_status()
    return r.content


def _parse_body(content: bytes) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        body_preview = _clean_error_body(content.decode("utf-8", "replace") or "(empty body)")
        raise RuntimeError(
            f"GSA CALC+ returned non-JSON response on 200 OK. "
            f"This often happens during API maintenance or when an HTML "
            f"error page is served without an error status. "
            f"Body: {body_preview}"
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError(
            f"GSA CALC+ response was not a JSON object. "
            f"Got {type(data).__name__}: {str(data)[:200]}"
        )
    return data


# ---------------------------------------------------------------------------
# Filter/param helpers
# ---------------------------------------------------------------------------

def _build_filters(
    *,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    security_clearance: Literal["yes", "no"] | None = None,
    sin: str | None = None,
) -> list[str]:
    """Build filter strings for the CALC+ API.

    Values are URL-encoded at the call site of _build_query_string. This helper
    only composes the `field:value` pieces.
    """
    filters: list[str] = []
    if education_level:
        filters.append(f"education_level:{education_level}")
    # Experience: support either both, min-only, or max-only
    if experience_min is not None and experience_max is not None:
        filters.append(f"experience_range:{experience_min},{experience_max}")
    elif experience_min is not None:
        # Must be experience_range, not min_years_experience: the API treats
        # min_years_experience:N as an exact term match (only records requiring
        # exactly N years). Live-verified in the 1.0.1 audit:
        # min_years_experience:5 matched 7,343 records where
        # experience_range:5,999 matched the expected 29,120. The 999 sentinel
        # mirrors the price_range approach below.
        filters.append(f"experience_range:{experience_min},999")
    elif experience_max is not None:
        filters.append(f"experience_range:0,{experience_max}")
    # Price: support either both, min-only, or max-only
    if price_min is not None and price_max is not None:
        filters.append(f"price_range:{price_min},{price_max}")
    elif price_min is not None:
        # No hardcoded upper bound: use an explicit sentinel that won't truncate real data
        filters.append(f"price_range:{price_min},999999")
    elif price_max is not None:
        filters.append(f"price_range:0,{price_max}")
    if business_size:
        filters.append(f"business_size:{business_size}")
    if security_clearance:
        filters.append(f"security_clearance:{security_clearance}")
    if sin:
        filters.append(f"sin:{sin}")
    return filters


def _build_query_string(
    *,
    keyword: str | None = None,
    search_field: str | None = None,
    search_value: str | None = None,
    suggest_field: str | None = None,
    suggest_term: str | None = None,
    filters: list[str] | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: str = "asc",
    exclude: str | None = None,
) -> str:
    """Build the full query parameter string. All values URL-encoded."""
    # Filters param must be a list; protect against accidental string passage.
    if filters is not None and not isinstance(filters, list):
        raise UserInputError(
            f"filters must be a list of 'field:value' strings. "
            f"Got {type(filters).__name__}."
        )

    parts: list[str] = []

    # Precedence: keyword > search > suggest. Reject combinations to prevent
    # silent dropping of the non-selected search mode.
    search_modes = sum([
        keyword is not None,
        bool(search_field and search_value),
        bool(suggest_field and suggest_term),
    ])
    if search_modes > 1:
        raise UserInputError(
            "Only one search mode allowed per query: keyword, search (field+value), "
            "or suggest (field+term). Combining silently drops the lower-priority modes."
        )

    if keyword is not None:
        parts.append(f"keyword={urllib.parse.quote_plus(keyword)}")
    elif search_field and search_value:
        parts.append(
            f"search={search_field}:{urllib.parse.quote_plus(search_value)}"
        )
    elif suggest_field and suggest_term:
        parts.append(
            f"suggest-contains={suggest_field}:{urllib.parse.quote_plus(suggest_term)}"
        )

    # URL-encode each filter's value portion. Filters are "field:value" strings;
    # split once, encode value, rejoin.
    if filters:
        for f in filters:
            if not isinstance(f, str) or not f:
                continue
            if ":" in f:
                field, value = f.split(":", 1)
                parts.append(f"filter={field}:{urllib.parse.quote_plus(value)}")
            else:
                parts.append(f"filter={urllib.parse.quote_plus(f)}")

    parts.append(f"page={page}")
    parts.append(f"page_size={min(page_size, MAX_PAGE_SIZE)}")
    parts.append(f"ordering={urllib.parse.quote_plus(ordering)}")
    parts.append(f"sort={urllib.parse.quote_plus(sort)}")

    if exclude:
        parts.append(f"exclude={urllib.parse.quote_plus(exclude)}")

    return "&".join(parts)


def _extract_stats(data: Any) -> dict[str, Any]:
    """Extract key statistics from the aggregations in a response.

    Fully defensive: tolerates every GSA CALC+ / ES response shape observed
    in testing: aggregations as null / list / str, wage_stats as null, percentile
    values as null, std_deviation_bounds as null, bucket items with None entries
    or missing key/doc_count, hits.total as int or None, wage_stats.avg/std as
    NaN/Inf. Never raises; returns a structured response with Nones for missing
    values.
    """
    data = _safe_dict(data)
    aggs = _safe_dict(data.get("aggregations"))
    wage_stats = _safe_dict(aggs.get("wage_stats"))
    percentiles = _safe_dict(_safe_dict(aggs.get("histogram_percentiles")).get("values"))
    ed_counts = _as_list(_safe_dict(aggs.get("education_level_counts")).get("buckets"))
    biz_size = _as_list(_safe_dict(aggs.get("business_size")).get("buckets"))
    # Counts only: GSA ignores a worksite filter, so a per-site price split
    # is not available from one call, but the counts show the mix.
    worksites = _as_list(_safe_dict(aggs.get("worksite")).get("buckets"))
    std_bounds = _safe_dict(wage_stats.get("std_deviation_bounds"))

    hits = _safe_dict(data.get("hits"))
    hits_total = hits.get("total")
    if isinstance(hits_total, dict):
        total_value = hits_total.get("value", 0)
        capped = hits_total.get("relation") == "gte"
    elif isinstance(hits_total, int):
        # ES 6 legacy format: total is just an int
        total_value = hits_total
        capped = False
    else:
        total_value = 0
        capped = False

    wage_count = wage_stats.get("count")
    true_count = wage_count if isinstance(wage_count, int) else total_value

    def _round_or_none(v: Any) -> float | None:
        n = _safe_number(v)
        return round(n, 2) if n is not None else None

    def _bucket_dict(buckets: list[Any]) -> dict[Any, Any]:
        out: dict[Any, Any] = {}
        for b in buckets:
            pair = _safe_bucket_key(b)
            if pair is not None:
                out[pair[0]] = pair[1]
        return out

    # Percentile keys might be "10.0" string or 10 int or even 10.0 float
    def _pct(key: float) -> Any:
        for k in (f"{key}", f"{key:.1f}", key, int(key)):
            if k in percentiles:
                return _safe_number(percentiles[k])
        return None

    # avg - 2 sigma goes negative on wide populations (SIN 541611: -$0.61);
    # a negative hourly rate is meaningless, so floor it at $0 and say so.
    outlier_bounds: dict[str, Any] = {
        "lower": _safe_number(std_bounds.get("lower")),
        "upper": _safe_number(std_bounds.get("upper")),
    }
    if outlier_bounds["lower"] is not None and outlier_bounds["lower"] < 0:
        outlier_bounds["lower"] = 0
        outlier_bounds["lower_clamped_to_zero"] = True

    return {
        "total_rates": true_count if true_count is not None else 0,
        "hits_capped": capped,
        "min_rate": _safe_number(wage_stats.get("min")),
        "max_rate": _safe_number(wage_stats.get("max")),
        "avg_rate": _round_or_none(wage_stats.get("avg")),
        "std_deviation": _round_or_none(wage_stats.get("std_deviation")),
        "percentiles": {
            "p10": _pct(10.0),
            "p25": _pct(25.0),
            "p50_median": _pct(50.0),
            "p75": _pct(75.0),
            "p90": _pct(90.0),
        },
        "outlier_bounds_2sigma": outlier_bounds,
        "education_breakdown": _bucket_dict(ed_counts),
        "business_size_breakdown": _bucket_dict(biz_size),
        "worksite_breakdown": _bucket_dict(worksites),
    }


def _title_summary(data: Any, top_n: int) -> dict[str, Any]:
    """Labor category titles behind a result, from the labor_category
    aggregation (case-sensitive, most records first).

    GSA caps that aggregation at 500 buckets. When titles were left off
    (sum_other_doc_count > 0) the distinct count is unknown: distinct is
    None and distinct_min gives the floor.
    """
    agg = _safe_dict(_safe_dict(_safe_dict(data).get("aggregations")).get("labor_category"))
    pairs = [p for p in (_safe_bucket_key(b) for b in _as_list(agg.get("buckets"))) if p is not None]
    other = agg.get("sum_other_doc_count")
    complete = not (isinstance(other, int) and other > 0)
    out: dict[str, Any] = {
        "top": [{"title": k, "count": c} for k, c in pairs[:top_n]],
        "distinct": len(pairs) if complete else None,
    }
    if not complete:
        out["distinct_min"] = len(pairs)
        out["records_in_titles_not_listed"] = other
    return out


def _population_scope(data: Any, keyword: str) -> dict[str, Any]:
    """Identify off-title matches from GSA's cross-field keyword search.

    Keyword searches also match vendor_name and idv_piid. An IGCE phrase
    such as Systems Engineering can therefore include every title at a
    vendor named Systems Engineering Inc. The terms list may be truncated
    and distributed counts approximate, so give examples rather than a
    purported exact count of unrelated rows.
    """
    agg = _safe_dict(_safe_dict(_safe_dict(data).get("aggregations")).get("labor_category"))
    pattern = re.compile(re.escape(keyword).replace(r"\*", ".*"), re.IGNORECASE)
    off_title = [p for p in (_safe_bucket_key(b) for b in _as_list(agg.get("buckets")))
                 if p is not None and isinstance(p[0], str) and not pattern.search(p[0])]
    buckets = agg.get("buckets")
    complete = (
        isinstance(buckets, list) and bool(buckets)
        and all((p := _safe_bucket_key(b)) is not None and isinstance(p[0], str) and bool(p[0]) for b in buckets)
        and agg.get("sum_other_doc_count") == 0
        and agg.get("doc_count_error_upper_bound", 0) == 0
    )
    return {
        "search_fields": ["labor_category", "vendor_name", "idv_piid"],
        "off_title_matches_detected": bool(off_title),
        "title_list_complete": complete,
        "title_only_population_verified": complete and not off_title,
        "off_title_examples": [{"title": k, "count": c} for k, c in off_title[:5]],
    }


# ---------------------------------------------------------------------------
# Core search tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Keyword Search", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def keyword_search(
    keyword: str,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    security_clearance: Literal["yes", "no"] | None = None,
    sin: SinInput = None,
    worksite: str | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: Literal["asc", "desc"] = "asc",
    exclude: str | None = None,
) -> dict[str, Any]:
    """Search GSA CALC+ ceiling rates by keyword.

    Performs wildcard matching across labor_category, vendor_name, and
    idv_piid fields. This is the primary search tool for finding rates.

    Returns matching rate records plus aggregation statistics (wage_stats,
    percentiles, education breakdown, business size) covering the FULL
    result set even when individual hits are capped at 10,000.

    Important notes:
    - These are NTE (not-to-exceed) ceiling rates, not prices paid
    - Rates are fully burdened hourly rates from GSA MAS contracts
    - Data refreshes nightly from vendor price proposal tables
    - Use P50 from percentiles for median (more accurate than median_price)

    Filter parameters:
    - education_level: AA, BA, HS, MA, PHD, TEC (pipe-delimited for OR: 'BA|MA')
    - experience_min/max: years of experience range
    - price_min/max: hourly rate range in USD
    - business_size: 'S' (small) or 'O' (other/large)
    - security_clearance: 'yes' or 'no'
    - sin: Special Item Number (e.g., '54151S' for IT Professional Services)
    - worksite: NOT supported (the v3 API silently ignores it; passing a
      value raises so callers are not handed unfiltered data)

    ordering: current_price, labor_category, vendor_name, education_level,
    min_years_experience, next_year_price, idv_piid, business_size.
    sort: 'asc' or 'desc'.

    exclude: pipe-delimited hit _id values to exclude from results and stats.
    """
    _validate_no_control_chars(keyword, field="keyword")
    keyword = _strip_or_none(keyword)
    if keyword is None:
        raise UserInputError(
            "keyword cannot be empty. For unfiltered browsing use filtered_browse() instead."
        )
    keyword = _clamp_text_len(keyword, field="keyword", maximum=500)
    keyword = _validate_waf_safe(keyword, field="keyword")
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    _validate_es_window(page, page_size)
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    price_min, price_max = _validate_price_range(price_min, price_max)
    education_level = _validate_education_level(education_level)
    _validate_worksite(worksite)
    sin = _validate_sin(sin)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)
    _validate_no_control_chars(exclude, field="exclude")
    exclude = _strip_or_none(exclude)
    exclude = _clamp_text_len(exclude, field="exclude", maximum=500)
    exclude = _validate_waf_safe(exclude, field="exclude")

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size, security_clearance=security_clearance,
        sin=sin,
    )
    qs = _build_query_string(
        keyword=keyword, filters=filters, page=page, page_size=page_size,
        ordering=ordering, sort=sort, exclude=exclude,
    )
    data = await _get(qs)
    stats = _extract_stats(data)
    result = {**data, "_stats": stats}
    return _attach_pagination_flags(result, page=page, page_size=page_size, total=stats.get("total_rates"))


@mcp.tool(annotations={"title": "Exact Search", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def exact_search(
    field: Literal["labor_category", "vendor_name", "idv_piid"],
    value: str,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Exact match search on a specific field.

    Use suggest_contains() first to discover the exact field value, then
    pass it here. The API requires exact string matching -- partial matches
    return 0 results.

    Fields: labor_category, vendor_name, idv_piid (GSA MAS contract number).
    """
    _validate_no_control_chars(value, field="value")
    value = _strip_or_none(value)
    if value is None:
        raise UserInputError("value cannot be empty. Use suggest_contains() to discover valid values.")
    value = _clamp_text_len(value, field="value", maximum=500)
    value = _validate_waf_safe(value, field="value")
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    _validate_es_window(page, page_size)
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    price_min, price_max = _validate_price_range(price_min, price_max)
    education_level = _validate_education_level(education_level)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size,
    )
    qs = _build_query_string(
        search_field=field, search_value=value, filters=filters,
        page=page, page_size=page_size, ordering=ordering, sort=sort,
    )
    data = await _get(qs)
    stats = _extract_stats(data)
    result = {**data, "_stats": stats}
    return _attach_pagination_flags(result, page=page, page_size=page_size, total=stats.get("total_rates"))


@mcp.tool(annotations={"title": "Suggest Contains", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def suggest_contains(
    field: Literal["labor_category", "vendor_name", "idv_piid"],
    term: str,
) -> dict[str, Any]:
    """Discover exact field values via autocomplete/contains matching.

    Returns aggregation buckets showing matching values and their record
    counts. Use this BEFORE exact_search() to find the right value string.

    Minimum 2 characters required for the search term.

    GSA lists at most 100 values, most records first. When more values
    match, truncated is true and other_records counts the records under
    values not shown; use a longer term to narrow the list.

    Example workflow:
    1. suggest_contains('vendor_name', 'booz') -> finds 'Booz Allen Hamilton Inc.'
    2. exact_search('vendor_name', 'Booz Allen Hamilton Inc.') -> all their rates
    """
    _validate_no_control_chars(term, field="term")
    term = _strip_or_none(term)
    if term is None or len(term) < 2:
        raise UserInputError(
            "suggest_contains requires at least 2 non-whitespace characters."
        )
    term = _clamp_text_len(term, field="term", maximum=500)
    term = _validate_waf_safe(term, field="term")

    qs = _build_query_string(suggest_field=field, suggest_term=term)
    data = await _get(qs)

    field_agg = _safe_dict(_safe_dict(data.get("aggregations")).get(field))
    buckets = _as_list(field_agg.get("buckets"))
    # GSA returns at most 100 values; sum_other_doc_count is the number of
    # records under values that were left off the list.
    other = field_agg.get("sum_other_doc_count")
    other_records = other if isinstance(other, int) and not isinstance(other, bool) and other > 0 else 0
    suggestions: list[dict[str, Any]] = []
    for b in buckets:
        pair = _safe_bucket_key(b)
        if pair is not None:
            suggestions.append({"value": pair[0], "count": pair[1]})

    hits = _safe_dict(data.get("hits"))
    total_obj = hits.get("total")
    if isinstance(total_obj, dict):
        total = total_obj.get("value", 0)
    elif isinstance(total_obj, int):
        total = total_obj
    else:
        total = 0

    result = {
        "field": field,
        "search_term": term,
        "suggestions": suggestions,
        "total_matching_records": total,
        "total_matching_records_is_lower_bound": (
            isinstance(total_obj, dict) and total_obj.get("relation") == "gte"
        ),
        "truncated": other_records > 0,
        "other_records": other_records,
    }
    if result["total_matching_records_is_lower_bound"]:
        result["_count_note"] = (
            f"GSA reports at least {total} matching records, not an exact total. "
            "Its suggestion response caps hits.total and omits wage_stats. "
            "Narrow the term or use keyword_search/exact_search for full statistics."
        )
    return result


@mcp.tool(annotations={"title": "Filtered Browse", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def filtered_browse(
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    security_clearance: Literal["yes", "no"] | None = None,
    sin: SinInput = None,
    worksite: str | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Browse rates with filters only (no search keyword).

    Useful for market segment statistics: "what do all BA-level rates with
    5-15 years experience look like across all of GSA MAS?" Returns rate
    records plus full aggregation statistics.
    """
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    _validate_es_window(page, page_size)
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    price_min, price_max = _validate_price_range(price_min, price_max)
    education_level = _validate_education_level(education_level)
    _validate_worksite(worksite)
    sin = _validate_sin(sin)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size, security_clearance=security_clearance,
        sin=sin,
    )
    # GSA CALC returns 265k+ records for an unfiltered browse; callers who
    # omit all filters almost always meant to pass something. Require at
    # least one filter to prevent silent unbounded-default responses.
    if not filters:
        raise UserInputError(
            "filtered_browse requires at least one filter. Typical filters: "
            "education_level='MA', experience_min=5, sin='54151S', "
            "business_size='S', price_min=50. For keyword search use keyword_search()."
        )
    qs = _build_query_string(
        filters=filters, page=page, page_size=page_size,
        ordering=ordering, sort=sort,
    )
    data = await _get(qs)
    stats = _extract_stats(data)
    result = {**data, "_stats": stats}
    return _attach_pagination_flags(result, page=page, page_size=page_size, total=stats.get("total_rates"))


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "IGCE Benchmark", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def igce_benchmark(
    labor_category: str,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    business_size: Literal["S", "O"] | None = None,
    sin: SinInput = None,
    security_clearance: Literal["yes", "no"] | None = None,
) -> dict[str, Any]:
    """Get ceiling rate benchmarks for IGCE development.

    Returns statistical summary for a labor category: count, min, max, avg,
    median, standard deviation, percentile distribution (P10-P90), education
    breakdown, worksite counts (worksite_breakdown: Customer_Facility /
    Contractor_Facility / Virtual; counts only, prices are pooled across
    sites), and outlier bounds.

    GSA's keyword search matches labor_category, vendor_name and idv_piid.
    The returned statistics pool all matching rate rows, including unrelated
    labor titles when a vendor name or contract number matches the phrase.
    Check population_scope and matched_titles before using the statistics.
    off_title_matches_detected flags observed titles that do not match the
    requested phrase; title_only_population_verified is false when the title
    aggregation is missing, empty, truncated or approximate.

    For title-only rates, call suggest_contains on labor_category to discover
    an exact title, then exact_search on labor_category. Different spellings
    remain separate searches ('Cyber Security Analyst' vs 'Cybersecurity
    Analyst'). Statistics are on current-year ceiling rates (current_price),
    not next-year or option-year prices.

    These are not-to-exceed ceiling rates, not prices paid. Ceiling-rate
    comparisons alone do not establish a proposed price's reasonableness.

    Optional filters: education_level, experience_min/max, business_size
    ('S' or 'O'), sin (e.g. '541611'), security_clearance ('yes' or 'no').
    """
    _validate_no_control_chars(labor_category, field="labor_category")
    labor_category = _strip_or_none(labor_category)
    if labor_category is None:
        raise UserInputError("labor_category cannot be empty.")
    labor_category = _clamp_text_len(labor_category, field="labor_category", maximum=500)
    labor_category = _validate_waf_safe(labor_category, field="labor_category")
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    education_level = _validate_education_level(education_level)
    sin = _validate_sin(sin)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, business_size=business_size, sin=sin,
        security_clearance=security_clearance,
    )
    qs = _build_query_string(
        keyword=labor_category, filters=filters, page=1, page_size=10,
    )
    data = await _get(qs)
    stats = _extract_stats(data)

    return {
        "labor_category": labor_category,
        "filters_applied": filters,
        **stats,
        # Which titles were pooled: "Senior Software Engineer" matches 53
        # titles (I-IV, Health IT ..., Principal ...), not one.
        "matched_titles": _title_summary(data, top_n=10),
        "population_scope": _population_scope(data, labor_category),
        "_note": (
            "Ceiling rates (NTE), not prices paid. Sample size matters for "
            "IGCE reliability. GSA's keyword search matches labor titles, "
            "vendor names and contract numbers. A literal phrase can match "
            "any of these fields. Statistics pool all those "
            "matches, including off-title rows when a vendor or contract "
            "matches (see population_scope and matched_titles). For title-only "
            "rates, discover a title with suggest_contains and use exact_search "
            "on labor_category. Different spellings remain separate searches "
            "('Cyber Security' vs 'Cybersecurity'). Statistics are on "
            "current-year ceiling rates."
        ),
    }


@mcp.tool(annotations={"title": "Price Reasonableness Check", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def price_reasonableness_check(
    labor_category: str,
    proposed_rate: float,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    business_size: Literal["S", "O"] | None = None,
    sin: SinInput = None,
    security_clearance: Literal["yes", "no"] | None = None,
) -> dict[str, Any]:
    """Evaluate a proposed hourly rate against GSA ceiling rate distribution.

    GSA's keyword search matches labor titles, vendor names and contract
    numbers. Check population_scope: unrelated titles can enter the pooled
    statistics through a matching vendor or contract.

    Returns MIXED_SEARCH_FIELDS with no verdict when off-title matches are
    detected, or UNVERIFIED_POPULATION with no verdict when the title list
    is missing, empty, truncated or approximate. Discover an exact title with
    suggest_contains, then use exact_search on labor_category for title-only
    rates. Filters match igce_benchmark, including sin and security_clearance.

    A verified title population with at least 20 rates returns z-score,
    median comparison, IQR position and delta from average. The z-score is
    null when the mean or standard deviation is unavailable or variance is
    zero. Missing means produce null average deltas.

    A verified population with fewer than 20 rates returns LOW_SAMPLE
    without a high/low verdict;
    zero rates return NO_DATA. Statistics compare not-to-exceed ceiling
    rates, not prices paid, and do not by themselves establish price
    reasonableness or performance risk.
    """
    if not isinstance(proposed_rate, (int, float)) or isinstance(proposed_rate, bool):
        raise UserInputError("proposed_rate must be a positive number.")
    if isinstance(proposed_rate, float) and (math.isnan(proposed_rate) or math.isinf(proposed_rate)):
        raise UserInputError(
            f"proposed_rate must be a finite number. Got {proposed_rate!r}. "
            f"NaN comparisons fall through to 'above P75' / 'equal' silently."
        )
    if proposed_rate <= 0:
        raise UserInputError(f"proposed_rate must be > 0. Got {proposed_rate}.")

    benchmark = await igce_benchmark(
        labor_category, education_level=education_level,
        experience_min=experience_min, experience_max=experience_max,
        business_size=business_size, sin=sin,
        security_clearance=security_clearance,
    )

    if benchmark.get("total_rates", 0) == 0:
        return {
            "status": "NO_DATA",
            "proposed_rate": proposed_rate,
            "message": f"No comparable ceiling rates found for '{labor_category}' with the given filters.",
        }

    scope = benchmark.get("population_scope", {})
    if not scope.get("title_only_population_verified"):
        off_title = scope.get("off_title_matches_detected")
        return {
            **benchmark,
            "status": "MIXED_SEARCH_FIELDS" if off_title else "UNVERIFIED_POPULATION",
            "proposed_rate": proposed_rate,
            "message": (
                ("GSA's keyword search also matched vendor names or contract "
                 "numbers, returning labor titles that do not contain the "
                 "requested phrase. " if off_title else
                 "GSA's labor title aggregation is missing or incomplete, so "
                 "off-title vendor/contract matches cannot be ruled out. ") +
                "These pooled statistics do not establish "
                "a comparable title population, so no high/low verdict is given. "
                "Use suggest_contains and exact_search on labor_category to "
                "inspect title-only rates, then select comparable requirements."
            ),
            "analysis": {
                "z_score": None, "vs_median": None, "iqr_position": None,
                "delta_from_avg": None, "delta_from_avg_pct": None,
            },
        }

    avg = benchmark.get("avg_rate")
    delta = round(proposed_rate - avg, 2) if avg is not None else None
    delta_pct = round(((proposed_rate - avg) / avg) * 100, 1) if avg is not None and avg > 0 else None
    n = benchmark.get("total_rates", 0)
    if n < LOW_SAMPLE_MIN_RATES:
        # A literal-phrase keyword ("Help Desk Specialist Tier 1") can shrink
        # the population to one rate; a high/low call on that is noise.
        return {
            **benchmark,
            "status": "LOW_SAMPLE",
            "proposed_rate": proposed_rate,
            "message": (
                f"Only {n} comparable rate{'s' if n != 1 else ''} found for "
                f"'{labor_category}'. That sample is too small for a high/low "
                f"verdict (this check needs at least {LOW_SAMPLE_MIN_RATES}). "
                f"The statistics are shown for reference only. Try a shorter "
                f"labor category phrase (the keyword is matched as a literal "
                f"phrase), drop a filter, or run suggest_contains to see the "
                f"exact titles."
            ),
            "analysis": {
                "z_score": None,
                "vs_median": None,
                "iqr_position": None,
                "delta_from_avg": delta,
                "delta_from_avg_pct": delta_pct,
            },
        }
    std = benchmark.get("std_deviation")
    median = benchmark.get("percentiles", {}).get("p50_median")
    p25 = benchmark.get("percentiles", {}).get("p25")
    p75 = benchmark.get("percentiles", {}).get("p75")

    z_score = round((proposed_rate - avg) / std, 2) if avg is not None and std is not None and std > 0 else None

    iqr_position = None
    if p25 is not None and p75 is not None:
        if proposed_rate < p25:
            iqr_position = "below P25 (low)"
        elif proposed_rate <= p75:
            iqr_position = "within IQR P25-P75 (typical)"
        else:
            iqr_position = "above P75 (high)"

    # Don't force "above" when median is missing; say "unknown"
    if median is None:
        vs_median = "unknown (median unavailable)"
    elif proposed_rate < median:
        vs_median = "below"
    elif proposed_rate > median:
        vs_median = "above"
    else:
        vs_median = "equal"

    analysis = {
        "z_score": z_score,
        "vs_median": vs_median,
        "iqr_position": iqr_position,
        "delta_from_avg": delta,
        "delta_from_avg_pct": delta_pct,
    }
    if z_score is None:
        analysis["z_score_reason"] = (
            "Z-score unavailable: the average or standard deviation is missing, "
            "or the standard deviation is zero. A zero z-score would incorrectly "
            "claim the proposed rate equals the population average."
        )
    return {
        **benchmark,
        "proposed_rate": proposed_rate,
        "analysis": analysis,
    }


@mcp.tool(annotations={"title": "Vendor Rate Card", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def vendor_rate_card(
    vendor_name: str,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "labor_category",
    sort: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Get ceiling rates for a specific vendor, one page at a time.

    Auto-discovers the exact vendor name via suggest-contains, then pulls
    their rate records. Returns labor categories, rates, education levels,
    experience requirements, SINs, contract numbers, contract end dates, and
    worksite. A vendor often lists the same category twice at two prices,
    one for work at the customer's site (Customer_Facility) and one at the
    contractor's site (Contractor_Facility); check worksite before comparing.

    Pass a partial name (e.g., 'booz' for Booz Allen Hamilton). The tool
    finds the exact registered name automatically. Use part of the legal
    name, not an acronym ('Science Applications', not 'SAIC').

    total_rates counts rate rows, not titles: one title can have several
    rows (worksite, contract, SIN). distinct_labor_categories is the number
    of distinct titles (case-sensitive); when a vendor has more than 500 it
    is null and distinct_labor_categories_min gives the floor.

    Large vendors span many pages: Booz Allen Hamilton carries ~1,900 rate
    rows (more than 500 distinct titles). The default page_size is 100 (~23KB) because a 500-row page
    for a vendor that size is ~114KB and overflows MCP client output limits.
    Rows are ordered by labor_category ascending by default, so a partial
    card is alphabet-biased; check has_more and keep calling with next_page
    until it is false before treating the card as complete.

    There is no server-side way to intersect a vendor with a labor-category
    keyword (the v3 API ignores vendor_name and labor_category as filter
    fields; live-verified). To find specific categories, page through the
    full card and match client-side.

    If the discovery term matches multiple vendors, this tool picks the one
    with the most rate records and returns a _candidates list so the caller
    can re-query with a more specific term if needed.
    """
    _validate_no_control_chars(vendor_name, field="vendor_name")
    vendor_name = _strip_or_none(vendor_name)
    if vendor_name is None or len(vendor_name) < 2:
        raise UserInputError("vendor_name must be at least 2 non-whitespace characters.")
    vendor_name = _clamp_text_len(vendor_name, field="vendor_name", maximum=500)
    vendor_name = _validate_waf_safe(vendor_name, field="vendor_name")
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    _validate_es_window(page, page_size)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)

    # Step 1: discover exact name
    discovery = await suggest_contains("vendor_name", vendor_name)
    suggestions = discovery.get("suggestions", [])
    if not suggestions:
        return {
            "vendor_search": vendor_name,
            "error": (
                f"No vendor found matching '{vendor_name}'. CALC+ lists vendors "
                f"by their registered legal name, not acronyms or brand names: "
                f"for example SAIC is 'SCIENCE APPLICATIONS INTERNATIONAL "
                f"CORPORATION', so search 'Science Applications'. Try part of "
                f"the legal name, or a shorter or different term."
            ),
        }

    exact_name = suggestions[0]["value"]
    multi_match_note = None
    if len(suggestions) > 1:
        multi_match_note = (
            f"{len(suggestions)} vendors matched '{vendor_name}'. Picked the one "
            f"with the most rate records ({suggestions[0].get('count')}). If this "
            f"isn't the intended vendor, pass a more specific term."
        )

    # Step 2: pull one page of rates for that vendor
    qs = _build_query_string(
        search_field="vendor_name", search_value=exact_name,
        page=page, page_size=page_size, ordering=ordering, sort=sort,
    )
    data = await _get(qs)

    hits_list = _as_list(_safe_dict(data.get("hits")).get("hits"))
    rates: list[dict[str, Any]] = []
    for h in hits_list:
        if not isinstance(h, dict):
            continue
        src = _safe_dict(h.get("_source"))
        rates.append({
            "labor_category": src.get("labor_category"),
            "current_price": _safe_number(src.get("current_price")),
            "next_year_price": _safe_number(src.get("next_year_price")),
            "education_level": src.get("education_level"),
            "min_years_experience": src.get("min_years_experience"),
            "sin": src.get("sin"),
            "idv_piid": src.get("idv_piid"),
            "business_size": src.get("business_size"),
            # A vendor often carries one title at two prices, one per site
            # (Customer_Facility / Contractor_Facility / Virtual); without
            # this the two rows look like duplicates at different prices.
            "worksite": src.get("worksite"),
            "contract_end": src.get("contract_end"),
        })

    hits_total = _safe_dict(data.get("hits")).get("total")
    if isinstance(hits_total, dict):
        total = hits_total.get("value", 0)
    elif isinstance(hits_total, int):
        total = hits_total
    else:
        total = 0

    # Pagination metadata: without it, a 100-row page of a 1,886-row card
    # presents as the complete rate card (the CALC-3 field finding).
    returned = len(rates)
    start_row = (page - 1) * page_size + 1
    end_row = (page - 1) * page_size + returned
    has_more = returned > 0 and end_row < total

    # total is a row count: one title can have several rows (worksite,
    # contract, SIN). Distinct titles come from the labor_category
    # aggregation, which GSA caps at 500 buckets; past that, give a floor.
    titles = _title_summary(data, top_n=0)

    response: dict[str, Any] = {
        "vendor": exact_name,
        "total_rates": total,
        "distinct_labor_categories": titles["distinct"] or None,
        "page": page,
        "returned": returned,
        "returned_range": f"rows {start_row}-{end_row} of {total}" if returned else None,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
        "rates": rates,
        "_stats": _extract_stats(data),
    }
    if "distinct_min" in titles:
        response["distinct_labor_categories_min"] = titles["distinct_min"]
    if has_more:
        response["_truncation_note"] = (
            f"Partial rate card: rows are ordered by {ordering} ({sort}), so "
            f"this slice is biased toward the start of that ordering "
            f"(alphabetical by labor category with the defaults). Categories "
            f"later in the ordering, like 'Software Engineer' or 'Systems "
            f"Engineer', may not appear until later pages. Call again with "
            f"page={page + 1} to continue; do not present a partial slice as "
            f"the complete card."
        )
    if multi_match_note:
        response["_note"] = multi_match_note
        response["_candidates"] = [
            {"value": s.get("value"), "count": s.get("count")}
            for s in suggestions[:10]
        ]
    return _attach_pagination_flags(response, page=page, page_size=page_size, total=total if isinstance(total, int) else None)


@mcp.tool(annotations={"title": "SIN Analysis", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def sin_analysis(
    sin_code: Annotated[Union[str, int], BeforeValidator(_reject_bool_pre)],
    page_size: int = 100,
) -> dict[str, Any]:
    """Get rate distribution and statistics for a specific SIN.

    Returns rate statistics, education breakdown, business size breakdown,
    and labor_categories for a GSA MAS Special Item Number: the 25 titles
    with the most rates on the SIN, with counts (exact, case-sensitive
    titles). It does not return individual rate rows or per-title prices;
    for what a title costs on the SIN, call igce_benchmark(title, sin=...).
    When GSA's 500-title list is cut off, labor_categories.distinct is null
    and records_in_titles_not_listed counts the rates under titles not
    listed.

    Common SINs for professional services (live-verified to return records):
    - 54151S: IT Professional Services
    - 541611: Management and Financial Consulting
    - 541715: Engineering R&D
    - 541330ENG: Engineering Services
    - 561210FAC: Facilities Maintenance and Management
    - 611430: Training
    """
    sin_code = _validate_sin(sin_code)
    if sin_code is None:
        raise UserInputError("sin_code cannot be empty.")
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)

    filters = [f"sin:{sin_code}"]
    qs = _build_query_string(
        filters=filters, page=1, page_size=page_size,
        ordering="current_price", sort="asc",
    )
    data = await _get(qs)
    stats = _extract_stats(data)

    result: dict[str, Any] = {
        "sin": sin_code,
        **stats,
        # The titles on the SIN, most rates first (the Q14 "what labor
        # categories are on 54151S" question had no answer before).
        "labor_categories": _title_summary(data, top_n=25),
    }
    if not stats.get("total_rates"):
        # A valid-looking SIN with zero records is usually a retired code,
        # not an empty market. Live-verified: 541512, 541513, 541610, and
        # 541519 all return 0 records (absorbed or retired under MAS
        # consolidation).
        result["_note"] = (
            "0 records for this SIN. It may be retired under MAS "
            "consolidation (for example 541512/541513 work now falls under "
            "54151S). Verify the current MAS SIN or use keyword_search on "
            "the labor category instead."
        )
    return result


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like keyword_search(keyword='engineer') (real
    param is `q`) would succeed with the typo silently discarded, returning
    unfiltered data. extra='forbid' raises "Extra inputs are not permitted"
    on typos before any HTTP call.
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
