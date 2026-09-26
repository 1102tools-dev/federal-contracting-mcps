# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Regulations.gov MCP server.

Federal rulemaking dockets, documents, public comments, and comment period
tracking. Requires a free api.data.gov key in REGULATIONS_GOV_API_KEY; without
it, data tools return setup instructions. The hosted deployment
(REGULATIONS_HOSTED=1) uses the publisher key.

Complements the Federal Register MCP (what was published) by providing the
rulemaking docket structure, public comments, and comment period status.
"""

from __future__ import annotations

import collections
import copy
import json as _json
import os
import time
import re
import urllib.parse
from datetime import date as _date, datetime as _datetime
from typing import Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from ._pacing import FederalApiPacer
from .constants import (
    BASE_URL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    MAX_TOOL_PAGE_SIZE,
    MIN_PAGE_SIZE,
    PROCUREMENT_AGENCIES,
    USER_AGENT,
)

mcp = MCPServer(
    "regulationsgov",
    version=__version__,
    # Regulations.gov authenticates in the query string and HTTPX logs full
    # request URLs at INFO. Do not allow credentials into host stderr logs.
    log_level="WARNING",
)

# Every data tool calls the Regulations.gov API (open-world); the status tool
# only inspects local configuration.
_OPEN_WORLD = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}
_LOCAL_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}


# ---------------------------------------------------------------------------
# Defensive helpers (ported from sam-gov / ecfr / bls-oews hardening)
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(f"{field} exceeds maximum of {hi}. Got {value}. Paginate instead.")
    return value


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
# Input validation
# ---------------------------------------------------------------------------

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SEARCH_TERM_MAX = 500
_ID_MAX_LEN = 128

_YYYYMMDD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YYYYMMDD_HMS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

# Valid sort fields per Regulations.gov API docs
_DOCUMENT_SORT_FIELDS = {
    "postedDate", "lastModifiedDate", "title", "documentId", "commentEndDate",
}
_COMMENT_SORT_FIELDS = {"postedDate", "lastModifiedDate", "documentId"}
_DOCKET_SORT_FIELDS = {"title", "docketId", "lastModifiedDate"}


def _validate_sort(value: Any, *, field: str, valid_fields: set[str]) -> str | None:
    """Validate a sort parameter: comma-separated fields, each with an
    optional leading '-'. The API documents multi-field sorts, and its own
    deep-pagination recipe requires 'lastModifiedDate,documentId'."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string like '-postedDate'.")
    s = value.strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split(",")]
    if any(not p for p in parts):
        raise ValueError(f"{field}={value!r} has an empty entry in the comma list.")
    for part in parts:
        bare = part[1:] if part.startswith("-") else part
        if bare not in valid_fields:
            sample = ", ".join(sorted(valid_fields))
            raise ValueError(
                f"{field} entry {part!r} is not a valid sort field. "
                f"Use one of: {sample} (prefix with '-' for descending; "
                f"comma-separate for multi-field sorts)."
            )
    return ",".join(parts)


def _validate_date_ymd(value: str | None, *, field: str) -> str | None:
    """YYYY-MM-DD with real calendar check. Regulations.gov rejects everything else."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string. Got {type(value).__name__}.")
    s = value.strip()
    if not s:
        return None
    if not _YYYYMMDD_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be YYYY-MM-DD (e.g. '2026-04-18'). "
            f"ISO 8601 with T/Z is rejected by the API."
        )
    try:
        parts = s.split("-")
        _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{field}={value!r} is not a valid calendar date: {exc}") from exc
    return s


def _validate_datetime_ymdhms(value: str | None, *, field: str) -> str | None:
    """'YYYY-MM-DD HH:MM:SS' (space-separated). This is a Regulations.gov quirk;
    the modified-date filters require this exact format, not ISO 8601."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a datetime string.")
    s = value.strip()
    if not s:
        return None
    if not _YYYYMMDD_HMS_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be 'YYYY-MM-DD HH:MM:SS' (space-separated, "
            f"24-hour time, no T or Z). Example: '2026-04-18 14:30:00'. "
            f"ISO 8601 is rejected by the API."
        )
    try:
        _datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"{field}={value!r} is not a valid datetime: {exc}") from exc
    return s


def _check_date_range(
    ge: str | None, le: str | None, *, field_pair: tuple[str, str]
) -> None:
    """Reject a range where the ge bound is after the le bound."""
    if ge and le and ge > le:
        raise ValueError(
            f"{field_pair[0]}={ge!r} is after {field_pair[1]}={le!r}. "
            f"The 'ge' (>=) bound must be <= the 'le' (<=) bound."
        )


def _validate_search_term(value: str | None, *, field: str = "search_term") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    # Check raw value for control chars BEFORE strip() eats \n/\r/\t.
    if _CONTROL_CHARS_RE.search(value) or any(c in value for c in ("\n", "\r", "\t")):
        raise ValueError(
            f"{field}={value!r} contains control characters. Remove them and retry."
        )
    s = value.strip()
    if not s:
        return None
    if len(s) > _SEARCH_TERM_MAX:
        raise ValueError(
            f"{field} exceeds {_SEARCH_TERM_MAX} chars. Regulations.gov silently "
            f"truncates long searches -- narrow your query first."
        )
    return s


_AGENCY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,19}$")


def _validate_agency_id(value: str | None, *, field: str = "agency_id") -> str | None:
    """Agency IDs are short letter-prefixed codes (FAR, DARS, GSA, DoD, etc).
    Comma-separated lists are accepted: the API documents
    filter[agencyId]=GSA,EPA as the multi-agency form (verified live).

    Empty string is explicitly rejected so that callers do not accidentally
    issue an unfiltered query that returns every document in Regulations.gov
    (verified live: empty string returns ~1.95M records).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    s = value.strip()
    if not s:
        raise ValueError(
            f"{field} cannot be empty. An empty agency_id returns ALL "
            f"documents in Regulations.gov (~1.95M). Pass None to skip the "
            f"filter or a valid agency code like 'FAR', 'DARS', 'GSA'."
        )
    tokens = [t.strip() for t in s.split(",")]
    if any(not t for t in tokens):
        raise ValueError(
            f"{field}={value!r} has an empty entry in the comma list. "
            f"Use 'FAR,GSA' with no trailing comma."
        )
    for token in tokens:
        if not _AGENCY_ID_RE.match(token):
            raise ValueError(
                f"{field} entry {token!r} is not a valid agency code. Agency "
                f"codes are short letter-prefixed strings like 'FAR', 'DARS', "
                f"'GSA', 'DoD'; comma-separate for multiple agencies."
            )
    return ",".join(tokens)


_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]{0,%d}$" % (_ID_MAX_LEN - 1))
_OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{10,32}$")


def _validate_optional_id(value: str | None, *, field: str) -> str | None:
    """Optional-ID params: None skips the filter; empty string is REJECTED.

    Before this guard, docket_id='' silently dropped the filter and searched
    all ~2M documents / ~26M comments: the exact empty-string bug class the
    0.2.0 release headline-fixed for agency_id, left open here.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        raise ValueError(
            f"{field} cannot be empty or whitespace. An empty {field} would "
            f"silently drop the filter and search the entire corpus. Pass "
            f"None to skip the filter."
        )
    return _validate_id(value, field=field)


def _validate_comment_on_id(value: str | None, *, field: str = "comment_on_id") -> str | None:
    """filter[commentOnId] takes the document's hex objectId, NOT its
    documentId. Passing a documentId (e.g. 'FAR-2023-0008-0024') returns
    zero comments with no error (verified live), which is the number-one
    cause of falsely-empty comment searches. Reject non-hex shapes with
    directions to the objectId."""
    s = _validate_optional_id(value, field=field)
    if s is None:
        return None
    if not _OBJECT_ID_RE.match(s):
        raise ValueError(
            f"{field}={s!r} looks like a documentId, but the API requires the "
            f"document's hex objectId (e.g. '0900006486531e6b'). Get it from "
            f"get_document_detail or search_documents: it is the "
            f"attributes.objectId field. Passing a documentId silently "
            f"returns 0 comments."
        )
    return s


def _validate_id(value: Any, *, field: str) -> str:
    """Validate a Regulations.gov ID (document_id, docket_id, comment_id).

    IDs look like 'FAR-2023-0008', 'FAR-2023-0008-0023'. Slashes, control
    chars, and path traversal sequences all fail the API differently
    (500/301); pre-reject them so callers get a clear error.
    """
    if value is None:
        raise ValueError(f"{field} is required.")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    # Check raw value for control chars BEFORE strip() eats them.
    if _CONTROL_CHARS_RE.search(value) or any(c in value for c in ("\n", "\r", "\t")):
        raise ValueError(f"{field}={value!r} contains control characters.")
    s = value.strip()
    if not s:
        raise ValueError(f"{field} cannot be empty.")
    if not _ID_SAFE_RE.match(s):
        raise ValueError(
            f"{field}={value!r} contains characters outside [A-Za-z0-9_.-] "
            f"or starts with a non-alphanumeric. Example valid IDs: "
            f"'FAR-2023-0008', 'FAR-2023-0008-0023'."
        )
    return s


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _hosted() -> bool:
    """True in the 1102tools hosted container, which holds the publisher key."""
    return os.environ.get("REGULATIONS_HOSTED", "").strip() == "1"


def _configured_key() -> str:
    return os.environ.get("REGULATIONS_GOV_API_KEY", "").strip()


_HOSTED_KEY_MISSING = (
    "Regulations.gov service credential is not configured. This is a "
    "server-side problem with the hosted service, not something the user "
    "can fix; try again later."
)


def _get_api_key() -> str:
    key = _configured_key()
    if key:
        return key
    raise ToolError(_HOSTED_KEY_MISSING if _hosted() else _KEY_MISSING)


def _live_access_mode() -> str:
    if _hosted():
        return "hosted_publisher_key" if _configured_key() else "hosted_key_missing"
    return "configured_unverified" if _configured_key() else "key_missing"


_KEY_MISSING = (
    "Regulations.gov needs a free api.data.gov key: register at "
    "https://open.gsa.gov/api/regulationsgov/#getting-started, set "
    "REGULATIONS_GOV_API_KEY, and restart the server."
)


@mcp.tool(annotations={"title": "Check Regulations.gov Data Access", **_LOCAL_ONLY})
def get_access_status() -> dict[str, Any]:
    """Check Regulations.gov credential presence without returning or validating it."""
    mode = _live_access_mode()
    if _hosted():
        return {
            "service": "Regulations.gov API",
            "status": mode,
            "users_need_key": False,
            "validation": "presence_only",
        }
    return {
        "service": "Regulations.gov API",
        "status": mode,
        "credential_env": "REGULATIONS_GOV_API_KEY",
        "required_for": ["every Regulations.gov data tool"],
        "setup_url": "https://open.gsa.gov/api/regulationsgov/#getting-started",
        "validation": "presence_only",
        "restart_required": True,
    }


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
        default_interval=REGISTERED_KEY_INTERVAL,
        credential=api_key,
    )


# api.data.gov limits a registered key per rolling hour (1,000 by default), not per
# second, so a registered key can burst.
REGISTERED_KEY_INTERVAL = 0.6
HOURLY_UPSTREAM_CAP = int(os.environ.get("API_DATA_GOV_HOURLY_CAP", "950"))
_upstream_starts: collections.deque[float] = collections.deque()

# Hosted deployments opt in to a bounded response cache (off by default locally).
# Regulations.gov pages can be hundreds of KB, so the cache is bounded by
# approximate serialized size, not just entry count (the hosted container is a
# small instance). Single responses above the per-entry limit are not cached.
RESPONSE_CACHE_SECONDS = float(os.environ.get("MCP_RESPONSE_CACHE_SECONDS", "0") or 0)
_RESPONSE_CACHE_MAX_ENTRIES = 2048
_RESPONSE_CACHE_MAX_BYTES = int(os.environ.get("MCP_RESPONSE_CACHE_MAX_BYTES", str(24 * 1024 * 1024)))
_RESPONSE_CACHE_MAX_ENTRY_BYTES = 1024 * 1024
_response_cache: dict[str, tuple[float, Any, int]] = {}
_response_cache_bytes = 0


def _reserve_hourly_upstream() -> None:
    now = time.monotonic()
    while _upstream_starts and _upstream_starts[0] <= now - 3600:
        _upstream_starts.popleft()
    if len(_upstream_starts) >= HOURLY_UPSTREAM_CAP:
        retry = int(_upstream_starts[0] + 3600 - now) + 1
        raise ToolError(
            f"The hourly Regulations.gov request budget ({HOURLY_UPSTREAM_CAP} upstream "
            f"calls) is used up. Retry in about {retry} seconds."
        )
    _upstream_starts.append(now)


def _cache_get(cache_key: str) -> Any:
    if RESPONSE_CACHE_SECONDS <= 0:
        return None
    hit = _response_cache.get(cache_key)
    if hit is None:
        return None
    expires, value, _size = hit
    if expires <= time.monotonic():
        _cache_evict(cache_key)
        return None
    return copy.deepcopy(value)


def _cache_evict(cache_key: str) -> None:
    global _response_cache_bytes
    hit = _response_cache.pop(cache_key, None)
    if hit is not None:
        _response_cache_bytes -= hit[2]


def _cache_put(cache_key: str, value: Any) -> None:
    global _response_cache_bytes
    if RESPONSE_CACHE_SECONDS <= 0:
        return
    size = len(_json.dumps(value, default=str))
    if size > _RESPONSE_CACHE_MAX_ENTRY_BYTES:
        return
    _cache_evict(cache_key)
    while _response_cache and (
        len(_response_cache) >= _RESPONSE_CACHE_MAX_ENTRIES
        or _response_cache_bytes + size > _RESPONSE_CACHE_MAX_BYTES
    ):
        _cache_evict(next(iter(_response_cache)))
    _response_cache[cache_key] = (time.monotonic() + RESPONSE_CACHE_SECONDS, copy.deepcopy(value), size)
    _response_cache_bytes += size


def _format_error(status: int, body: Any, api_key: str | None = None) -> str:
    cleaned = _clean_error_body(body, api_key)
    low = cleaned.lower() if isinstance(cleaned, str) else ""
    mode = _live_access_mode()
    if status == 403:
        # 403 from api.data.gov means key rejected (API_KEY_INVALID /
        # API_KEY_MISSING). 403 from regulations.gov itself usually means its
        # WAF blocked angle brackets or other patterns in the search terms.
        if "api_key" in low or "api key" in low or "unauthorized" in low:
            if mode.startswith("hosted"):
                return (
                    "HTTP 403: api.data.gov rejected this service's Regulations.gov "
                    "credential. This is a server-side problem with the hosted "
                    "service, not something the user can fix; try again later."
                )
            return (
                "HTTP 403: api.data.gov rejected the configured REGULATIONS_GOV_API_KEY. "
                "Check the key at https://open.gsa.gov/api/regulationsgov/#getting-started"
            )
        return (
            f"HTTP 403: Request blocked. Common cause: Regulations.gov's WAF "
            f"rejects angle brackets and a handful of other patterns. Remove "
            f"special characters from search terms. API response: {cleaned}"
        )
    if status == 429:
        if mode.startswith("hosted"):
            return (
                "HTTP 429: the Regulations.gov API rate limit for this service was "
                "reached. Retry in a few minutes."
            )
        return (
            "HTTP 429: the configured REGULATIONS_GOV_API_KEY reached its "
            "api.data.gov hourly limit (1,000 req/hr by default). Retry later."
        )
    if status == 400:
        if "page" in low and "size" in low:
            return (
                f"HTTP 400: page_size must be {MIN_PAGE_SIZE}-{MAX_TOOL_PAGE_SIZE}. "
                f"API response: {cleaned}"
            )
        if "page number" in low:
            return (
                f"HTTP 400: page_number out of range. The API allows pages "
                f"1-40 (its own 400 names 40 as the max). For larger sets, "
                f"split the query into date windows: posted_date_ge/le on "
                f"documents and comments, last_modified_date_ge/le on dockets. "
                f"API: {cleaned}"
            )
        if "date" in low:
            return (
                f"HTTP 400: Date format error. postedDate and commentEndDate "
                f"use YYYY-MM-DD. lastModifiedDate requires "
                f"'YYYY-MM-DD HH:MM:SS' (space-separated, no T or Z). "
                f"API response: {cleaned}"
            )
        if "filter" in low:
            return (
                f"HTTP 400: Invalid filter. Values are CASE-SENSITIVE: "
                f"'Proposed Rule' not 'proposed rule', 'Rulemaking' not "
                f"'rulemaking'. API response: {cleaned}"
            )
        if "sort" in low:
            return (
                f"HTTP 400: Invalid sort field (prefix with '-' for descending). "
                f"Documents: {', '.join(sorted(_DOCUMENT_SORT_FIELDS))}. "
                f"Comments: {', '.join(sorted(_COMMENT_SORT_FIELDS))}. "
                f"Dockets: {', '.join(sorted(_DOCKET_SORT_FIELDS))}. "
                f"API response: {cleaned}"
            )
        return f"HTTP 400: {cleaned}"
    if status == 404:
        return (
            f"HTTP 404: Resource not found. Verify the ID (e.g. "
            f"'FAR-2023-0008-0001' is documentId; 'FAR-2023-0008' is docketId). "
            f"API response: {cleaned}"
        )
    if status == 503:
        return (
            "HTTP 503: Regulations.gov upstream service unavailable. "
            "This often happens when the request contains characters that "
            "trigger their firewall (SQL keywords, angle brackets). Remove "
            "special characters and retry."
        )
    return f"HTTP {status}: {cleaned}"


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET helper. Returns parsed JSON; empty/null bodies become {}."""
    cache_key = path + "?" + urllib.parse.urlencode(sorted((params or {}).items()))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    key = _get_api_key()
    _reserve_hourly_upstream()
    # The key travels in the X-Api-Key header (as Regulations.gov documents),
    # never in the URL, so upstream and infrastructure URL logs cannot hold it.
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(dict(params or {}))}"
    try:
        async with _pacer(key).request_slot() as pacing:
            r = await _get_client().get(url, headers={"X-Api-Key": key})
            pacing.observe_response(r)
            pacing.raise_if_rate_limited(
                r,
                service="Regulations.gov",
                guidance=_format_error(r.status_code, r.text, key),
            )
    except httpx.RequestError as e:
        safe_error = _redact_sensitive_text(str(e), key)
        raise ToolError(f"Network error calling Regulations.gov: {safe_error}") from e
    except RuntimeError as e:
        raise ToolError(_redact_sensitive_text(str(e), key)) from e
    if r.status_code >= 400:
        raise ToolError(_format_error(r.status_code, r.text, key))
    try:
        data = r.json()
    except (ValueError, _json.JSONDecodeError) as e:
        preview = _clean_error_body(r.text or "(empty body)", key)[:200]
        ct = r.headers.get("content-type", "?")
        raise ToolError(
            f"Regulations.gov returned a non-JSON response (status {r.status_code}, "
            f"content-type={ct!r}): {preview}"
        ) from e
    data = _redact_sensitive_payload(data, key)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ToolError(
            f"Regulations.gov returned unexpected JSON type {type(data).__name__}: "
            f"{str(data)[:200]}"
        )
    _cache_put(cache_key, data)
    return data


def _validate_page_size(page_size: Any, max_size: int = MAX_TOOL_PAGE_SIZE) -> int:
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        raise ValueError(f"page_size must be an int {MIN_PAGE_SIZE}-{max_size}.")
    if page_size > max_size:
        raise ValueError(
            f"page_size exceeds maximum of {max_size}. Got {page_size}. "
            f"Paginate with page_number instead."
        )
    return _clamp(page_size, field="page_size", lo=MIN_PAGE_SIZE, hi=max_size)


def _validate_page_number(page_number: Any) -> int:
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise ValueError("page_number must be a positive int.")
    # The published docs say 20 pages, but the live API accepts up to 40
    # (its own 400 at page 1000 says "Maximum value is 40", and page 21
    # returns real data). 40 x 250 = 10,000 reachable records per query.
    return _clamp(page_number, field="page_number", lo=1, hi=40)


_FACET_LIMIT = 10


def _agency_codes_from_aggregations(meta: dict[str, Any], limit: int = 25) -> list[str]:
    agg = _safe_dict(meta.get("aggregations")).get("agencyId")
    codes = []
    for entry in _as_list(agg):
        entry = _safe_dict(entry)
        code = entry.get("value") or entry.get("label")
        if isinstance(code, str) and code:
            codes.append(code)
    return codes[:limit]


def _compact_record(value: Any) -> Any:
    """Drop JSON:API self-links and empty attributes from one record."""
    if not isinstance(value, dict):
        return value
    out = {k: v for k, v in value.items() if k != "links"}
    attrs = out.get("attributes")
    if isinstance(attrs, dict):
        out["attributes"] = {k: v for k, v in attrs.items() if v not in (None, "", [], {})}
    return out


def _compact_listing(response: dict[str, Any]) -> dict[str, Any]:
    """Shrink a Regulations.gov search response without losing data rows.

    The API attaches meta.aggregations to every search: facet counts for
    every agency (about 300 entries), subtype, and dates, often larger than
    the rows themselves. They become meta.facets: the top counts per facet,
    as {value: count}. Rows lose JSON:API self-links and empty attributes.
    """
    response = dict(response)
    response.pop("links", None)
    response["data"] = [_compact_record(r) for r in _as_list(response.get("data"))]
    meta = dict(_safe_dict(response.get("meta")))
    aggregations = _safe_dict(meta.pop("aggregations", None))
    facets: dict[str, Any] = {}
    for name, entries in aggregations.items():
        counts = {}
        for entry in _as_list(entries):
            entry = _safe_dict(entry)
            label = entry.get("value") or entry.get("label")
            count = entry.get("docCount")
            if label is not None and isinstance(count, int) and count > 0:
                counts[str(label)] = count
        if not counts:
            continue
        top = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:_FACET_LIMIT])
        facets[name] = top
        if len(counts) > _FACET_LIMIT:
            facets[f"{name}_more"] = len(counts) - _FACET_LIMIT
    if facets:
        meta["facets"] = facets
    if meta:
        response["meta"] = meta
    return response


def _compact_detail(response: dict[str, Any]) -> dict[str, Any]:
    response = dict(response)
    response.pop("links", None)
    if isinstance(response.get("data"), dict):
        response["data"] = _compact_record(response["data"])
    if isinstance(response.get("included"), list):
        response["included"] = [_compact_record(r) for r in response["included"]]
    return response


def _flag_no_data(
    response: dict[str, Any], *, context: str, page_size: int = 25, page_number: int = 1,
    hints: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Add a no_data hint when an agency/id filter silently returns zero,
    OR a paged_past_end hint when the caller walked past the last page."""
    data_items = _as_list(response.get("data"))
    meta = _safe_dict(response.get("meta"))
    total = meta.get("totalElements") if isinstance(meta, dict) else None
    if data_items:
        return response
    response = dict(response)
    if total in (0, None):
        checks = [
            "agency_id is an exact Regulations.gov agency code (e.g. FAR, DARS, GSA, DOD); "
            "codes are matched case-insensitively and unknown codes return zero "
            "results with no error",
            *hints,
            "date ranges are not inverted",
        ]
        response["no_data"] = True
        response["no_data_reason"] = (
            f"No results for this query ({context}). If you expected results, verify: "
            + "; ".join(f"({i}) {c}" for i, c in enumerate(checks, 1)) + "."
        )
        codes = _agency_codes_from_aggregations(meta)
        if codes and "agency_id=None" not in context:
            response["agency_codes_with_most_records"] = codes
    elif isinstance(total, int) and page_number * page_size > total:
        response["paged_past_end"] = True
        response["paged_past_end_reason"] = (
            f"No data on page {page_number} (page_size={page_size}), but total "
            f"matching records = {total}. You paged past the end. Last page "
            f"with data is page {max(1, (total + page_size - 1) // page_size)}."
        )
    return response


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Documents", **_OPEN_WORLD})
async def search_documents(
    search_term: str | None = None,
    agency_id: str | None = None,
    document_type: Literal["Proposed Rule", "Rule", "Notice", "Supporting & Related Material", "Other"] | None = None,
    docket_id: str | None = None,
    within_comment_period: bool | None = None,
    posted_date_ge: str | None = None,
    posted_date_le: str | None = None,
    comment_end_date_ge: str | None = None,
    comment_end_date_le: str | None = None,
    sort: str = "-postedDate",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search Regulations.gov documents (proposed rules, final rules, notices).

    Filter values are CASE-SENSITIVE. Use exact casing:
    - document_type: 'Proposed Rule', 'Rule', 'Notice', 'Supporting & Related Material', 'Other'
    - Lowercase values silently return 0 results (no error)

    Key parameters:
    - agency_id: FAR, DARS, GSA, SBA, OFPP, DOD, NASA, VA, etc.
      Comma-separate for multiple agencies ('FAR,GSA'). Empty string is rejected.
    - docket_id: e.g., 'FAR-2023-0008' for a specific FAR case
    - within_comment_period: True to find documents currently accepting
      comments. False is NOT supported by the API (it 400s); omit the
      parameter instead to search regardless of comment status.
    - posted_date_ge/le: YYYY-MM-DD format (calendar-checked)
    - comment_end_date_ge/le: YYYY-MM-DD format

    Response meta.facets gives the top counts by document type, agency,
    and comment period status; meta.totalElements is the full match count.

    Page size: 5-100. page_number: 1-40. For larger result sets, split the
    query into posted_date_ge/le windows.

    sort: '-postedDate' (newest first, default), 'postedDate', '-commentEndDate',
    'lastModifiedDate', 'title', 'documentId'. Comma-separate for
    multi-field sorts ('lastModifiedDate,documentId').
    """
    return await _search_documents(
        search_term=search_term, agency_id=agency_id, document_type=document_type,
        docket_id=docket_id, within_comment_period=within_comment_period,
        posted_date_ge=posted_date_ge, posted_date_le=posted_date_le,
        comment_end_date_ge=comment_end_date_ge, comment_end_date_le=comment_end_date_le,
        sort=sort, page_size=page_size, page_number=page_number,
    )


async def _search_documents(
    *,
    search_term: str | None = None,
    agency_id: str | None = None,
    document_type: str | None = None,
    docket_id: str | None = None,
    within_comment_period: bool | None = None,
    posted_date_ge: str | None = None,
    posted_date_le: str | None = None,
    comment_end_date_ge: str | None = None,
    comment_end_date_le: str | None = None,
    sort: str = "-postedDate",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
    max_page_size: int = MAX_TOOL_PAGE_SIZE,
) -> dict[str, Any]:
    page_size = _validate_page_size(page_size, max_page_size)
    page_number = _validate_page_number(page_number)
    search_term = _validate_search_term(search_term, field="search_term")
    agency_id = _validate_agency_id(agency_id, field="agency_id")
    docket_id = _validate_optional_id(docket_id, field="docket_id")
    if within_comment_period is False:
        raise ValueError(
            "within_comment_period=False is not supported by the API "
            "(only 'true' is an acceptable filter value; false returns "
            "HTTP 400). Omit the parameter to search all documents "
            "regardless of comment-period status."
        )
    posted_date_ge = _validate_date_ymd(posted_date_ge, field="posted_date_ge")
    posted_date_le = _validate_date_ymd(posted_date_le, field="posted_date_le")
    comment_end_date_ge = _validate_date_ymd(comment_end_date_ge, field="comment_end_date_ge")
    comment_end_date_le = _validate_date_ymd(comment_end_date_le, field="comment_end_date_le")
    _check_date_range(posted_date_ge, posted_date_le,
                      field_pair=("posted_date_ge", "posted_date_le"))
    _check_date_range(comment_end_date_ge, comment_end_date_le,
                      field_pair=("comment_end_date_ge", "comment_end_date_le"))
    sort = _validate_sort(sort, field="sort", valid_fields=_DOCUMENT_SORT_FIELDS)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
    }
    if sort:
        params["sort"] = sort
    if search_term:
        params["filter[searchTerm]"] = search_term
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if document_type:
        params["filter[documentType]"] = document_type
    if docket_id:
        params["filter[docketId]"] = docket_id
    if within_comment_period:
        params["filter[withinCommentPeriod]"] = "true"
    if posted_date_ge:
        params["filter[postedDate][ge]"] = posted_date_ge
    if posted_date_le:
        params["filter[postedDate][le]"] = posted_date_le
    if comment_end_date_ge:
        params["filter[commentEndDate][ge]"] = comment_end_date_ge
    if comment_end_date_le:
        params["filter[commentEndDate][le]"] = comment_end_date_le

    result = await _get("documents", params)
    ctx = f"agency_id={agency_id!r}, document_type={document_type!r}"
    return _compact_listing(_flag_no_data(
        result, context=ctx, page_size=page_size, page_number=page_number,
        hints=("document_type uses exact casing ('Proposed Rule', not 'proposed rule')",),
    ))


@mcp.tool(annotations={"title": "Get Document Detail", **_OPEN_WORLD})
async def get_document_detail(
    document_id: str,
    include_attachments: bool = False,
) -> dict[str, Any]:
    """Get full details for a single Regulations.gov document.

    Returns fileFormats (download URLs), cfrPart, displayProperties, and
    other detail fields not available in search results.

    Set include_attachments=True to get attachment objects with download URLs.

    document_id format: FAR-2023-0008-0023
    """
    document_id = _validate_id(document_id, field="document_id")
    params: dict[str, Any] = {}
    if include_attachments:
        params["include"] = "attachments"
    return _compact_detail(await _get(f"documents/{document_id}", params))


@mcp.tool(annotations={"title": "Search Comments", **_OPEN_WORLD})
async def search_comments(
    search_term: str | None = None,
    agency_id: str | None = None,
    comment_on_id: str | None = None,
    docket_id: str | None = None,
    posted_date_ge: str | None = None,
    posted_date_le: str | None = None,
    sort: str = "-postedDate",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search public comments on Regulations.gov.

    To find comments on a specific document, use comment_on_id with the
    hex objectId from document detail/search results (attributes.objectId,
    e.g. '0900006486531e6b'). The human-readable documentId is REJECTED
    here because the API silently returns 0 comments for it.

    docket_id filters comments to all documents in a docket.

    Page size: 5-100; page_number 1-40. Comments sorted by '-postedDate' by
    default. For larger result sets, split the query into posted_date_ge/le
    windows. Most comment text is in attachments; get_comment_detail with
    include_attachments=True returns their download URLs.
    """
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)
    search_term = _validate_search_term(search_term, field="search_term")
    agency_id = _validate_agency_id(agency_id, field="agency_id")
    comment_on_id = _validate_comment_on_id(comment_on_id, field="comment_on_id")
    docket_id = _validate_optional_id(docket_id, field="docket_id")
    posted_date_ge = _validate_date_ymd(posted_date_ge, field="posted_date_ge")
    posted_date_le = _validate_date_ymd(posted_date_le, field="posted_date_le")
    _check_date_range(posted_date_ge, posted_date_le,
                      field_pair=("posted_date_ge", "posted_date_le"))
    sort = _validate_sort(sort, field="sort", valid_fields=_COMMENT_SORT_FIELDS)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
    }
    if sort:
        params["sort"] = sort
    if search_term:
        params["filter[searchTerm]"] = search_term
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if comment_on_id:
        params["filter[commentOnId]"] = comment_on_id
    if docket_id:
        params["filter[docketId]"] = docket_id
    if posted_date_ge:
        params["filter[postedDate][ge]"] = posted_date_ge
    if posted_date_le:
        params["filter[postedDate][le]"] = posted_date_le

    result = await _get("comments", params)
    ctx = (
        f"agency_id={agency_id!r}, docket_id={docket_id!r}, "
        f"comment_on_id={comment_on_id!r}"
    )
    return _compact_listing(_flag_no_data(
        result, context=ctx, page_size=page_size, page_number=page_number,
        hints=("comment_on_id is the document's hex objectId, not its documentId",),
    ))


@mcp.tool(annotations={"title": "Get Comment Detail", **_OPEN_WORLD})
async def get_comment_detail(
    comment_id: str,
    include_attachments: bool = False,
) -> dict[str, Any]:
    """Get full details for a single comment.

    Returns the comment text field, organization, submitter info (if public),
    tracking number, and duplicate comment count. Many comments put their
    substance in attachments and the text field only says "See attached";
    include_attachments=True returns the attachment download URLs.

    Some fields (firstName, lastName, organization) are agency-configurable
    and may be hidden.
    """
    comment_id = _validate_id(comment_id, field="comment_id")
    params: dict[str, Any] = {}
    if include_attachments:
        params["include"] = "attachments"
    return _compact_detail(await _get(f"comments/{comment_id}", params))


@mcp.tool(annotations={"title": "Search Dockets", **_OPEN_WORLD})
async def search_dockets(
    search_term: str | None = None,
    agency_id: str | None = None,
    docket_type: Literal["Rulemaking", "Nonrulemaking"] | None = None,
    last_modified_date_ge: str | None = None,
    last_modified_date_le: str | None = None,
    sort: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search Regulations.gov dockets.

    Dockets are containers for related regulatory documents (proposed rules,
    comments, supporting materials). FAR cases, DFARS cases, and agency
    rulemaking actions each have a docket.

    docket_type is CASE-SENSITIVE: 'Rulemaking' or 'Nonrulemaking'.

    lastModifiedDate format: 'YYYY-MM-DD HH:MM:SS' (space-separated, NOT ISO).
    This is a Regulations.gov quirk; ISO 8601 is rejected.

    Limited filters: only searchTerm, agencyId, docketType, lastModifiedDate.

    Page size: 5-100; page_number 1-40. For larger result sets, split the
    query into last_modified_date_ge/le windows.
    """
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)
    search_term = _validate_search_term(search_term, field="search_term")
    agency_id = _validate_agency_id(agency_id, field="agency_id")
    last_modified_date_ge = _validate_datetime_ymdhms(
        last_modified_date_ge, field="last_modified_date_ge"
    )
    last_modified_date_le = _validate_datetime_ymdhms(
        last_modified_date_le, field="last_modified_date_le"
    )
    _check_date_range(
        last_modified_date_ge, last_modified_date_le,
        field_pair=("last_modified_date_ge", "last_modified_date_le"),
    )
    sort = _validate_sort(sort, field="sort", valid_fields=_DOCKET_SORT_FIELDS)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
    }
    if sort:
        params["sort"] = sort
    if search_term:
        params["filter[searchTerm]"] = search_term
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if docket_type:
        params["filter[docketType]"] = docket_type
    if last_modified_date_ge:
        params["filter[lastModifiedDate][ge]"] = last_modified_date_ge
    if last_modified_date_le:
        params["filter[lastModifiedDate][le]"] = last_modified_date_le

    result = await _get("dockets", params)
    ctx = f"agency_id={agency_id!r}, docket_type={docket_type!r}"
    return _compact_listing(_flag_no_data(
        result, context=ctx, page_size=page_size, page_number=page_number,
        hints=("docket_type uses exact casing ('Rulemaking', not 'rulemaking')",),
    ))


@mcp.tool(annotations={"title": "Get Docket Detail", **_OPEN_WORLD})
async def get_docket_detail(docket_id: str) -> dict[str, Any]:
    """Get full details for a single docket.

    Returns title, abstract, RIN (links to Unified Agenda), agency,
    keywords, and modification date.

    docket_id format: FAR-2023-0008, DARS-2025-0071, SBA-2024-0002
    """
    docket_id = _validate_id(docket_id, field="docket_id")
    return _compact_detail(await _get(f"dockets/{docket_id}"))


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

def _page_fields(total: Any, page_size: int, page_number: int, returned: int) -> dict[str, Any]:
    """Pagination metadata shared by the workflow tools."""
    fields: dict[str, Any] = {"page_number": page_number, "page_size": page_size, "returned": returned}
    shown_through = (page_number - 1) * page_size + returned
    if isinstance(total, int) and total > shown_through and returned == page_size and page_number < 40:
        fields["truncated"] = True
        fields["next_page_number"] = page_number + 1
    return fields


@mcp.tool(annotations={"title": "Open Comment Periods", **_OPEN_WORLD})
async def open_comment_periods(
    agency_ids: list[str] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Find documents with currently open comment periods.

    Searches for documents where withinCommentPeriod=true, sorted by
    soonest closing deadline (ascending commentEndDate), so page 1 holds
    the deadlines you can still act on. Returns document IDs, titles,
    agencies, comment end dates, docket IDs, and the API-true total_open.
    When more documents exist, truncated=true and next_page_number gives
    the page that continues the list (later pages close later).

    page_size: 5-100 documents per page (default 25). page_number: 1-40.

    Default searches FAR, DARS, GSA, SBA, OFPP, DOD, NASA, VA in a single
    comma-joined query. Pass agency_ids to narrow or expand the scope. An
    empty list is rejected; pass None to use the defaults.
    """
    if agency_ids is not None:
        if not isinstance(agency_ids, list):
            raise ValueError("agency_ids must be a list of agency codes.")
        if len(agency_ids) == 0:
            raise ValueError(
                "agency_ids cannot be empty. Pass None to use the default "
                "procurement-agency list, or a non-empty list of codes like "
                "['FAR', 'DARS']."
            )
        if len(agency_ids) > 20:
            raise ValueError(
                f"agency_ids capped at 20 entries (got {len(agency_ids)})."
            )
        validated = []
        for i, a in enumerate(agency_ids):
            validated.append(_validate_agency_id(a, field=f"agency_ids[{i}]"))
        agencies = validated
    else:
        agencies = list(PROCUREMENT_AGENCIES)
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)

    # One comma-joined call (documented multi-agency form) replaces the old
    # per-agency loop of 8 round-trips. Ascending sort is the load-bearing
    # fix: the old -commentEndDate DESCENDING sort plus a 50-row page kept
    # the FURTHEST deadlines and silently dropped the soonest-closing
    # documents, the exact ones this tool exists to surface.
    result = await _search_documents(
        agency_id=",".join(agencies),
        within_comment_period=True,
        sort="commentEndDate",
        page_size=page_size,
        page_number=page_number,
    )

    all_docs: list[dict[str, Any]] = []
    for item in _as_list(result.get("data")):
        item = _safe_dict(item)
        attrs = _safe_dict(item.get("attributes"))
        all_docs.append({
            "document_id": item.get("id"),
            "agency": attrs.get("agencyId"),
            "title": attrs.get("title"),
            "document_type": attrs.get("documentType"),
            "comment_end_date": attrs.get("commentEndDate"),
            "docket_id": attrs.get("docketId"),
            "url": f"https://www.regulations.gov/document/{item.get('id')}",
        })

    dated = [d for d in all_docs if d.get("comment_end_date")]
    dated.sort(key=lambda x: x["comment_end_date"] or "")
    undated = [d for d in all_docs if not d.get("comment_end_date")]

    api_total = _safe_dict(result.get("meta")).get("totalElements")
    total_open = api_total if isinstance(api_total, int) else len(all_docs)

    response: dict[str, Any] = {
        "agencies_searched": agencies,
        "total_open": total_open,
        **_page_fields(api_total, page_size, page_number, len(all_docs)),
        "documents": dated + undated,
    }
    if response.get("truncated"):
        first = (page_number - 1) * page_size + 1
        response["truncated_note"] = (
            f"Showing open documents {first}-{first + len(all_docs) - 1} of {api_total}, "
            f"soonest-closing first. The rest close later: request "
            f"page_number={page_number + 1}, or a larger page_size (up to {MAX_TOOL_PAGE_SIZE})."
        )
    if undated:
        response["undated_note"] = (
            f"{len(undated)} open document(s) on this page report no commentEndDate; "
            f"they are listed after the dated ones instead of being dropped."
        )
    return response


@mcp.tool(annotations={"title": "FAR Case History", **_OPEN_WORLD})
async def far_case_history(
    docket_id: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Get the lifecycle of a FAR/DFARS rulemaking case, summary first.

    Returns the docket metadata (title, abstract, RIN linking to the
    Unified Agenda), the docket's total document count, counts by document
    type and of documents open for comment across the whole docket, and one
    page of its documents, most recent first, with types, dates, and URLs.
    When the docket has more documents, truncated=true and next_page_number
    gives the page that continues the list.

    page_size: 5-100 documents per page (default 25). page_number: 1-40.

    docket_id examples: FAR-2023-0008, DARS-2025-0071
    """
    docket_id = _validate_id(docket_id, field="docket_id")
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)

    docket = await get_docket_detail(docket_id)
    docket_attrs = _safe_dict(_safe_dict(docket.get("data")).get("attributes"))

    docs_result = await _search_documents(
        docket_id=docket_id,
        sort="-postedDate",
        page_size=page_size,
        page_number=page_number,
    )
    documents: list[dict[str, Any]] = []
    for item in _as_list(docs_result.get("data")):
        item = _safe_dict(item)
        attrs = _safe_dict(item.get("attributes"))
        documents.append({
            "document_id": item.get("id"),
            "document_type": attrs.get("documentType"),
            "title": attrs.get("title"),
            "posted_date": attrs.get("postedDate"),
            "comment_end_date": attrs.get("commentEndDate"),
            "within_comment_period": attrs.get("withinCommentPeriod"),
            "url": f"https://www.regulations.gov/document/{item.get('id')}",
        })
    meta = _safe_dict(docs_result.get("meta"))
    facets = _safe_dict(meta.get("facets"))
    api_total = meta.get("totalElements")

    out: dict[str, Any] = {
        "docket_id": docket_id,
        "title": docket_attrs.get("title"),
        "abstract": docket_attrs.get("dkAbstract"),
        "rin": docket_attrs.get("rin"),
        "agency": docket_attrs.get("agencyId"),
        "url": f"https://www.regulations.gov/docket/{docket_id}",
        "total_documents": api_total if isinstance(api_total, int) else len(documents),
    }
    if facets.get("documentType"):
        out["documents_by_type"] = facets["documentType"]
    if "withinCommentPeriod" in facets:
        out["open_for_comment"] = _safe_dict(facets["withinCommentPeriod"]).get("true", 0)
    out.update(_page_fields(api_total, page_size, page_number, len(documents)))
    out["documents"] = documents
    if out.get("truncated"):
        first = (page_number - 1) * page_size + 1
        out["truncated_note"] = (
            f"Showing documents {first}-{first + len(documents) - 1} of {api_total}, most "
            f"recent first. Request page_number={page_number + 1} for older documents."
        )
    return out


# ---------------------------------------------------------------------------
# Strict parameter validation (cross-fix from sam-gov-mcp 0.3.1)
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_documents(keyword='audit') (real
    param is `search_term`) succeeded with the typo silently discarded,
    returning unfiltered data. extra='forbid' raises "Extra inputs are
    not permitted" on typos before any HTTP call.
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
