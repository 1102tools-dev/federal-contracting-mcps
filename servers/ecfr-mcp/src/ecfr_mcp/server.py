# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""eCFR MCP server.

Provides access to the full text, structure, version history, and search
of the Code of Federal Regulations via the eCFR API (ecfr.gov).

No authentication required. All endpoints are public and free.

The server parses XML content responses into clean text so the calling LLM
never needs to process raw XML. Structure and metadata endpoints return JSON.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import html
import json as _json
import re
import time
from datetime import date as _date, timedelta
from typing import Any

import httpx
from mcp.server import MCPServer

from . import __version__, _definitions, _xml_text
from ._throughput import EcfrPacer, EcfrXmlPacer
from ._response_cache import DAY, HOUR, MINUTE, ResponseCache, cache_key, positive_int_from_env
from ._xml_cache import XmlCache
from .constants import (
    BASE_URL,
    COMMON_FAR_SECTIONS,
    DEFAULT_TIMEOUT_CONTENT,
    DEFAULT_TIMEOUT_JSON,
    DEFAULT_TIMEOUT_STRUCTURE,
    ECFR_EARLIEST_DATE,
    SEARCH_MAX_PER_PAGE,
    SEARCH_MAX_TOTAL,
    SEARCH_ORDERS,
    TITLE_48_CHAPTERS,
    USER_AGENT,
)

mcp = MCPServer("ecfr", version=__version__)


# ---------------------------------------------------------------------------
# Defensive helpers (response shape + input validation)
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


def _safe_int(value: Any, default: int | None = None) -> int | None:
    """Coerce value to int. Returns default for None/""/'null'/non-parseable.

    Round 6 fix: also catches OverflowError from inf/nan
    floats. Without it, _safe_int(float('inf')) crashed instead of returning
    the default.
    """
    if value in (None, "", "null", "None"):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _strip_or_none(value: Any) -> str | None:
    """Strip a string; return None for None/empty/whitespace-only."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if s else None


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(f"{field} exceeds maximum of {hi}. Got {value}. Paginate instead.")
    return value


def _clamp_str_len(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds maximum length of {maximum}. Got {len(value)}.")
    return value


_HTML_MARK_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: Any) -> str:
    """Strip HTML to extract just the useful error message. Safe for bytes/None."""
    if text is None:
        return "(empty body)"
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            text = repr(text)
    if not isinstance(text, str):
        text = str(text)
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


# Input validation


_YYYYMMDD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_ymd(value: str | None, *, field: str) -> str | None:
    """eCFR uses YYYY-MM-DD. Reject every other format."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string. Got {type(value).__name__}.")
    s = value.strip()
    if not s:
        raise ValueError(
            f"{field} cannot be empty or whitespace. Use YYYY-MM-DD (e.g. '2026-04-16'), "
            f"or omit to auto-resolve the latest available date."
        )
    if s.lower() == "current":
        raise ValueError(
            f"{field}='current' is not accepted. Use a specific YYYY-MM-DD date, "
            f"or omit {field} to auto-resolve to the latest available."
        )
    if not _YYYYMMDD_RE.match(s):
        raise ValueError(
            f"{field} must be YYYY-MM-DD (e.g. '2026-04-16'). Got {value!r}."
        )
    try:
        from datetime import date as _date
        parts = s.split("-")
        _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{field}={value!r} is not a valid calendar date: {exc}") from exc
    return s


def _validate_title_number(value: Any, *, field: str = "title_number") -> int:
    """CFR titles are 1-50."""
    if value is None:
        raise ValueError(f"{field} is required.")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an int 1-50, not bool.")
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        # OverflowError catches inf/nan float coercion. Round 6 fix.
        raise ValueError(f"{field} must be an int 1-50. Got {value!r}.") from exc
    if n < 1 or n > 50:
        raise ValueError(f"{field} must be between 1 and 50. Got {n}.")
    return n


# Section/part/subpart/chapter normalization. LLMs often pass ints or
# include human-friendly prefixes.

# Regulation names people put in front of a cite: the FAR and its supplements.
_REG_NAMES = (
    "FAR|DFARS|GSAR|VAAR|HSAR|NFS|DEAR|AGAR|AIDAR|CAR|DIAR|DOLAR|DOSAR|DTAR|EDAR|"
    "EPAAR|HHSAR|HUDAR|JAR|LIFAR|NRCAR|NSFAR|SSAAR|TAR|FEHBAR|AFARS|NMCARS|DLAD"
)
_SECTION_PREFIX_RE = re.compile(
    rf"^\s*(?:(?:{_REG_NAMES})(?![A-Za-z])\s*|\d+\s*C\.?\s*F\.?\s*R\.?\s*|C\.?F\.?R\.?\s+)",
    re.IGNORECASE,
)
# Labels copied from headings: "§ 9.104-1", "Part 22", "Subpart 15.3", "Section 15.305".
_LABEL_PREFIX_RE = re.compile(r"^\s*(?:§+|sections?\b\.?|sec\.|subpart\b|part\b)\s*", re.IGNORECASE)
_CITED_TITLE_RE = re.compile(r"^\s*(\d+)\s*C\.?\s*F\.?\s*R\b", re.IGNORECASE)
_DASHES = str.maketrans({"\u2013": "-", "\u2014": "-", "\u2011": "-", "\u2212": "-"})

# Trailing paragraph cites like '15.305(a)' or '52.212-4(c)(2)(xviii)'. The
# cited paragraph is not a separate eCFR document; the base section is.
_PAREN_CITE_RE = re.compile(r"(?:\s*\([A-Za-z0-9]{1,6}\))+\s*$")


def _cited_title(value: Any) -> int | None:
    """The title named in a cite like '2 CFR 200.320', if any."""
    m = _CITED_TITLE_RE.match(value) if isinstance(value, str) else None
    return int(m.group(1)) if m else None


def _check_cited_title(value: Any, title_number: int, field: str) -> None:
    cited = _cited_title(value)
    if cited is not None and cited != title_number:
        raise ValueError(
            f"{field}={value!r} is in title {cited}, but title_number is {title_number}. "
            f"Pass title_number={cited}."
        )


def _coerce_cfr_str(
    value: Any,
    *,
    field: str,
    strip_prefixes: bool = False,
    strip_cites: bool = False,
    maxlen: int = 120,
) -> str | None:
    """Accept int or str for CFR identifiers (part/subpart/section/chapter).

    LLMs often pass ints (part=15). We coerce to str, strip whitespace, and
    optionally strip common user-added prefixes like 'FAR ' or '48 CFR '.
    strip_cites additionally drops trailing paragraph cites, so
    '15.305(a)(2)' resolves to section '15.305' instead of a guaranteed 404.
    Returns None for None/empty/whitespace-only. Raises on other types.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a string or integer, not bool.")
    if not isinstance(value, (str, int)):
        raise ValueError(
            f"{field} must be a string or integer. Got {type(value).__name__}."
        )
    raw = str(value)
    if "\x00" in raw:
        raise ValueError(f"{field}={value!r} contains a null byte.")
    if any(c in raw for c in ("\n", "\r", "\t")):
        raise ValueError(f"{field}={value!r} must not contain newline/tab characters.")
    s = raw.strip()
    if not s:
        return None
    if strip_prefixes:
        s = s.translate(_DASHES)
        previous = None
        while s != previous:
            previous = s
            s = _SECTION_PREFIX_RE.sub("", s)
            s = _LABEL_PREFIX_RE.sub("", s).strip()
        if not s:
            return None
    if strip_cites:
        s = _PAREN_CITE_RE.sub("", s).strip()
        if not s:
            return None
    if len(s) > maxlen:
        raise ValueError(
            f"{field} exceeds maximum length of {maxlen} chars. Got {len(s)}."
        )
    return s


def _validate_chapter(value: Any, *, title_number: int | None = None) -> str | None:
    """Chapter is a string or int. If title=48, validate against TITLE_48_CHAPTERS."""
    s = _coerce_cfr_str(value, field="chapter", maxlen=8)
    if s is None:
        return None
    # For title 48 we know every legitimate chapter.
    if title_number == 48 and s not in TITLE_48_CHAPTERS:
        listing = "; ".join(f"{k} = {v.split(' (')[0]}" for k, v in TITLE_48_CHAPTERS.items())
        raise ValueError(
            f"chapter={value!r} is not a valid Title 48 chapter. Title 48 chapters: {listing}. "
            f"For a section or part number, leave chapter out."
        )
    return s


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _validate_agency_slugs(value: list[str] | str | None) -> list[str] | None:
    """Normalize agency_slugs to a list of validated slug strings.

    Accepts a single slug or a list. Slugs are lowercase letters, digits,
    and hyphens (e.g. 'defense-acquisition-regulations-system').
    """
    if value is None:
        return None
    items = [value] if isinstance(value, str) else list(value)
    slugs: list[str] = []
    for item in items:
        s = _strip_or_none(item)
        if s is None:
            raise ValueError("agency_slugs entries cannot be empty or whitespace.")
        s = s.lower()
        if len(s) > 100 or not _SLUG_RE.match(s):
            raise ValueError(
                f"agency_slugs entry {item!r} is not a valid agency slug "
                f"(lowercase letters, digits, hyphens). Use list_agencies() to find slugs."
            )
        slugs.append(s)
    return slugs or None


# Free-text guard for search queries
_INJECT_PATTERNS = [
    (re.compile(r"\x00"), "null byte"),
]


def _validate_query_safe(value: str, *, field: str) -> str:
    """Pre-reject strings that break our URL construction."""
    for pattern, desc in _INJECT_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{field} contains {desc}.")
    return value


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
_pacer = EcfrPacer()
_xml_pacer = EcfrXmlPacer()
# Hosted only (MCP_RESPONSE_CACHE=1): JSON answers in _cache, and the XML cache
# keeps answers longer and holds more (see _cache_seconds). By default they stay
# within 64 MiB together; the hosting machine can give them more room with
# MCP_RESPONSE_CACHE_MB, MCP_XML_CACHE_MB and MCP_RESPONSE_CACHE_ENTRIES.
# Locally the XML cache keeps its 5-minute default.
_cache = ResponseCache(max_bytes=24 * 1024 * 1024, max_entry_bytes=4 * 1024 * 1024)
_xml_cache = XmlCache(
    max_entries=positive_int_from_env("MCP_RESPONSE_CACHE_ENTRIES") or 4096,
    max_bytes=(positive_int_from_env("MCP_XML_CACHE_MB") or 40) * 1024 * 1024,
    max_entry_bytes=4 * 1024 * 1024,
) if _cache.enabled else XmlCache()
_DATED_PATH = re.compile(r"^/api/versioner/v1/(?:full|structure|ancestry)/(\d{4}-\d{2}-\d{2})/")
_TITLES = "/api/versioner/v1/titles.json"
# eCFR's update state (a fingerprint of every title's dates) and when it was read.
_version: tuple[str | None, float] = (None, float("-inf"))
_version_lock: asyncio.Lock | None = None


def _cache_seconds(path: str, versioned: bool = False) -> float:
    """How long a hosted answer is kept, by endpoint.

    An answer filed under eCFR's current update state (``versioned``) is kept a
    full day: eCFR's next daily update changes the state, which retires it.
    Without the state, the shorter times apply.
    """
    dated = _DATED_PATH.match(path)
    if dated:
        try:
            day = _date.fromisoformat(dated.group(1))
        except ValueError:
            return HOUR
        # Text as of a past date doesn't change. The newest dates are what
        # "current" resolves to; give those a shorter life unless versioned.
        recent = day >= _date.today() - timedelta(days=7)
        return 6 * HOUR if recent and not versioned else DAY
    if path == _TITLES:
        return 15 * MINUTE  # latest date per title
    if path == "/api/admin/v1/agencies.json":
        return DAY
    if versioned:
        return DAY  # until eCFR's next daily update
    return HOUR  # search, recent changes, version history, corrections


async def _data_version() -> str | None:
    """eCFR's update state, read at most every 15 minutes (hosted only).

    A short fingerprint of every title's up-to-date, amended and issue dates.
    Hosted answers are filed under it, so eCFR's next daily update retires the
    answers kept from before it. It is read straight from eCFR, outside the
    cache, so it never counts as a hit or miss. If it can't be read, answers use
    the shorter times and it is read again after a minute.
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
            titles = _json.loads(await _fetch_json(_TITLES, None, DEFAULT_TIMEOUT_JSON)).get("titles") or []
            state = [[t.get("number"), t.get("up_to_date_as_of"), t.get("latest_amended_on"), t.get("latest_issue_date")]
                     for t in titles if isinstance(t, dict)]
            value = hashlib.sha256(_json.dumps(state, separators=(",", ":")).encode()).hexdigest()[:16] if state else None
            _version = (value, time.monotonic())
        except Exception:
            value = None
            _version = (None, time.monotonic() - 14 * MINUTE)
    return value


def _cache_stats() -> dict[str, int]:
    json_stats, xml_stats = _cache.stats(), _xml_cache.stats()
    return {name: json_stats[name] + xml_stats[name] for name in json_stats}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: Any) -> str:
    """Translate common eCFR errors into actionable messages."""
    cleaned = _clean_error_body(body)
    low = cleaned.lower() if isinstance(cleaned, str) else ""
    if status == 404:
        return (
            "HTTP 404: Resource not found. Common causes: (1) the date exceeds "
            "the title's up_to_date_as_of value -- use get_latest_date() first; "
            "(2) the section/part does not exist at the requested date; "
            "(3) 'current' is not a valid date keyword -- use a specific YYYY-MM-DD date; "
            "(4) paragraph cites like '15.305(a)(2)' are not separate documents -- "
            "request the base section and read the paragraph from its text; "
            f"(5) point-in-time history begins {ECFR_EARLIEST_DATE} -- earlier dates always 404; "
            "(6) a chapter that doesn't own the section (Title 48: 52.x is chapter 1, "
            "252.x chapter 2, 552.x chapter 5) -- leave chapter out. "
            f"API response: {cleaned}"
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. The eCFR content endpoint only returns XML. "
            "This server handles the XML parsing automatically -- if you see this "
            "error, the request path may be malformed."
        )
    if status == 400:
        if "section" in low and ("filter" in low or "not supported" in low):
            return (
                "HTTP 400: The structure endpoint does not support section-level "
                "filtering. Use part or subpart filters instead, then walk the "
                "children to find sections."
            )
        if "per_page" in low or "9999" in low:
            return (
                f"HTTP 400: per_page value too high (max {SEARCH_MAX_PER_PAGE}). "
                f"API response: {cleaned}"
            )
        return f"HTTP 400: {cleaned}"
    if status == 429:
        return (
            "HTTP 429: Rate limited by eCFR. Wait a few seconds and retry. "
            "eCFR throttles heavy automated use."
        )
    if 500 <= status < 600:
        return f"HTTP {status}: eCFR server error. {cleaned}. Retry after a short backoff."
    return f"HTTP {status}: {cleaned}"


def _what_was_asked(status: int, path: str, params: dict[str, Any] | None) -> str:
    """Echo a not-found request, so the reader sees how the input was read."""
    if status != 404:
        return ""
    asked = ", ".join(f"{k}={v}" for k, v in (params or {}).items())
    return f" Request sent: {path}" + (f" ({asked})" if asked else "")


async def _get_json(
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_JSON,
) -> dict[str, Any]:
    """GET helper for JSON endpoints. Always returns a dict (empty if API returned null)."""
    version = None if path == _TITLES else await _data_version()
    key = cache_key("GET", path, params)
    if version:
        key = f"{version}|{key}"
    return await _cache.get_or_fetch(
        key, _cache_seconds(path, versioned=version is not None),
        lambda: _fetch_json(path, params, timeout), _parse_json_body,
    )


async def _fetch_json(path: str, params: dict[str, Any] | None, timeout: float) -> bytes:
    """One paced eCFR JSON request; only cache misses get here."""
    try:
        async with _pacer.request_slot() as pacing:
            r = await _get_client().get(path, params=params or {}, timeout=timeout)
            pacing.observe_response(r)
            pacing.raise_if_rate_limited(
                r,
                service="eCFR",
                guidance=_format_error(r.status_code, r.text),
            )
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling eCFR: {e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_format_error(r.status_code, r.text) + _what_was_asked(r.status_code, path, params))
    try:
        r.json()
    except (ValueError, _json.JSONDecodeError) as e:
        preview = _clean_error_body(r.text or "(empty body)")[:200]
        ct = r.headers.get("content-type", "?")
        raise RuntimeError(
            f"eCFR returned a non-JSON response (status {r.status_code}, "
            f"content-type={ct!r}): {preview}"
        ) from e
    return r.content


def _parse_json_body(content: bytes) -> dict[str, Any]:
    data = _json.loads(content)
    if data is None:
        return {}
    if not isinstance(data, (dict, list)):
        raise RuntimeError(
            f"eCFR returned unexpected JSON type {type(data).__name__}: {str(data)[:200]}"
        )
    return data if isinstance(data, dict) else {"_list": data}


async def _get_xml(path: str, params: dict[str, Any] | None = None) -> str:
    version = await _data_version()
    key = _json.dumps([path, params or {}, version], sort_keys=True, separators=(",", ":"))
    ttl = _cache_seconds(path, versioned=version is not None) if _cache.enabled else None
    return await _xml_cache.get_or_fetch(key, lambda: _get_xml_uncached(path, params), ttl)


async def _get_xml_uncached(path: str, params: dict[str, Any] | None = None) -> str:
    """GET helper for XML content endpoints. Returns raw XML string."""
    try:
        async with _xml_pacer.request_slot() as xml_pacing, _pacer.request_slot() as pacing:
            r = await _get_client().get(
                path, params=params or {}, timeout=DEFAULT_TIMEOUT_CONTENT
            )
            xml_pacing.observe_response(r)
            pacing.observe_response(r)
            pacing.raise_if_rate_limited(
                r,
                service="eCFR",
                guidance=_format_error(r.status_code, r.text),
            )
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling eCFR: {e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_format_error(r.status_code, r.text) + _what_was_asked(r.status_code, path, params))
    text = r.text
    if not isinstance(text, str):
        text = str(text)
    return text


# ---------------------------------------------------------------------------
# XML parsing (server-side so Claude never sees raw XML; see _xml_text.py)
# ---------------------------------------------------------------------------

def _parse_xml_to_text(xml_content: Any, date: str | None = None) -> dict[str, Any]:
    """Clean text from an eCFR XML content response.

    One object per section (heading, paragraphs, citations, and tables,
    notes, examples, images, pending_amendments and editorial_notes when
    present). Multi-section responses list them under 'sections'. date fills
    the date into eCFR's hierarchy paths.
    """
    return _xml_text.parse(xml_content, date)


def _walk_structure(node: Any, target_type: str = "section") -> list[dict[str, Any]]:
    """Recursively walk a structure tree and collect nodes of a given type.

    Defensive against None, non-dict nodes, and None/non-list children.
    """
    if not isinstance(node, dict):
        return []
    collected: list[dict[str, Any]] = []
    if node.get("type") == target_type:
        collected.append({
            "identifier": node.get("identifier"),
            "label": node.get("label"),
            "label_description": node.get("label_description"),
            "size": node.get("size"),
            "received_on": node.get("received_on"),
        })
    children = node.get("children")
    for child in _as_list(children):
        collected.extend(_walk_structure(child, target_type))
    return collected


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _resolve_date(title_number: int) -> str:
    """Resolve the latest available date for a CFR title.

    Called before any versioner endpoint. Using today's date often returns
    404 because eCFR lags 1-2 business days.

    Raises ValueError with an actionable message for reserved titles
    (which have null up_to_date_as_of) rather than building a URL with
    'None' in it.
    """
    data = await _get_json("/api/versioner/v1/titles.json")
    titles = _as_list(_safe_dict(data).get("titles"))
    for title in titles:
        t = _safe_dict(title)
        if _safe_int(t.get("number")) == title_number:
            utd = t.get("up_to_date_as_of")
            if not isinstance(utd, str) or not utd.strip():
                reason = "this title is marked 'reserved'" if t.get("reserved") else (
                    "the API did not return up_to_date_as_of"
                )
                raise ValueError(
                    f"Cannot resolve a date for title {title_number}: {reason}. "
                    f"Reserved or un-issued titles have no published content."
                )
            return utd
    raise ValueError(f"Title {title_number} not found in eCFR titles list.")


# eCFR's version history comes 1,000 versions to a page.
_VERSION_PAGE = 1000
# Read at most this many pages per question (25,000 versions); past that the
# answer says it is incomplete and how to narrow it.
_MAX_VERSION_PAGES = 25


async def _all_versions(title_number: int, params: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    """Every version eCFR lists for these filters, reading all its pages.

    Returns the versions, eCFR's meta from the first page, and whether every
    page was read.
    """
    path = f"/api/versioner/v1/versions/title-{title_number}"
    first = _safe_dict(await _get_json(path, params))
    versions = [_safe_dict(v) for v in _as_list(first.get("content_versions"))]
    meta = _safe_dict(first.get("meta"))
    pages = _safe_int(meta.get("total_pages"), default=1) or 1
    for page in range(2, min(pages, _MAX_VERSION_PAGES) + 1):
        more = _safe_dict(await _get_json(path, {**params, "page": str(page)}))
        versions.extend(_safe_dict(v) for v in _as_list(more.get("content_versions")))
    return versions, meta, pages <= _MAX_VERSION_PAGES


def _latest_versions(versions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each identifier's newest version (removed wins a tie: it ends the section)."""
    latest: dict[str, dict[str, Any]] = {}
    for v in versions:
        ident = v.get("identifier")
        if not ident:
            continue
        kept = latest.get(ident)
        rank = (v.get("date") or "", bool(v.get("removed")), v.get("issue_date") or "")
        if kept is None or rank > (kept.get("date") or "", bool(kept.get("removed")), kept.get("issue_date") or ""):
            latest[ident] = v
    return latest


def _check_title48_chapter(chapter: str | None, identifier: str | None) -> str | None:
    """The chapter a Title 48 part or section belongs to; an error if chapter disagrees."""
    if not identifier:
        return chapter
    owner = _title48_chapter(identifier.split(".")[0])
    if owner is None or owner not in TITLE_48_CHAPTERS:
        return chapter
    if chapter and chapter != owner:
        raise ValueError(
            f"{identifier} is in Title 48 chapter {owner} ({TITLE_48_CHAPTERS[owner]}), not "
            f"chapter {chapter}. Leave chapter out; the number is enough."
        )
    return owner


def _title48_chapter(part: Any) -> str | None:
    """Title 48 chapter that owns a part: FAR parts 1-99, then part // 100."""
    number = _safe_int(str(part).split(".")[0]) if part is not None else None
    if number is None:
        return None
    return "1" if number < 100 else str(number // 100)


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Get Latest Date", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_latest_date(title_number: int = 48) -> dict[str, Any]:
    """Get the most recent available date for a CFR title.

    CRITICAL: eCFR lags 1-2 business days behind the Federal Register.
    Using today's date on versioner endpoints causes 404 errors. Call this
    first to get the safe date, then pass it to other tools.

    Default title 48 = Federal Acquisition Regulations System (FAR, DFARS,
    and all agency supplements). Other common titles: 2 (Grants/Agreements),
    5 (Administrative Personnel), 29 (Labor), 41 (Public Contracts).

    Raises ValueError for titles 1-50 that are reserved (no content).
    """
    title_number = _validate_title_number(title_number)
    data = await _get_json("/api/versioner/v1/titles.json")
    titles = _as_list(_safe_dict(data).get("titles"))
    for title in titles:
        t = _safe_dict(title)
        if _safe_int(t.get("number")) == title_number:
            utd = t.get("up_to_date_as_of")
            if not isinstance(utd, str) or not utd.strip():
                reserved = t.get("reserved")
                raise ValueError(
                    f"Title {title_number} has no available content "
                    f"(reserved={reserved}). Reserved titles are placeholders "
                    f"in the CFR numbering scheme without published regulations."
                )
            return {
                "title": title_number,
                "name": t.get("name"),
                "up_to_date_as_of": utd,
                "latest_amended_on": t.get("latest_amended_on"),
                "latest_issue_date": t.get("latest_issue_date"),
                "reserved": bool(t.get("reserved", False)),
            }
    raise ValueError(f"Title {title_number} not found.")


@mcp.tool(annotations={"title": "Get CFR Content", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_cfr_content(
    title_number: int = 48,
    date: str | None = None,
    part: str | int | None = None,
    subpart: str | int | None = None,
    section: str | int | None = None,
    chapter: str | int | None = None,
    appendix: str | int | None = None,
    raw_xml: bool = False,
    page: int = 1,
) -> dict[str, Any]:
    """Get the full text of a CFR section, subpart, part, or appendix.

    This is the primary workhorse for reading regulatory text. Returns
    parsed clean text by default: heading, paragraphs and citations, plus
    tables, notes, examples, images, pending_amendments and editorial_notes
    when present. Tables, notes and examples are numbered, and a marker like
    "[See table 1: ...]" sits in the paragraphs where each appears. [fn N]
    marks a footnote reference. pending_amendments means eCFR links a
    published amendment that may not be in effect yet. A subpart, part or
    appendix request returns one object per section under 'sections', each
    with its own section number and heading. Set raw_xml=True to get the
    original XML instead.

    Answers longer than about 60,000 characters come in pages: the reply
    says page and total_pages, and page=2 (and so on) returns the rest.

    Specify the narrowest scope possible to keep responses manageable:
    - section='15.305' for a single FAR section
    - subpart='15.3' for a subpart
    - part='15' for an entire part (can be large)
    - chapter='1' for an entire chapter (often >1 MB, avoid)
    - appendix='Appendix A to Chapter 2' (with chapter='2') for a DFARS appendix

    Date auto-resolves to the latest available if not provided. Do NOT use
    today's date directly -- eCFR lags 1-2 business days and today often 404s.

    Title 48 = FAR/DFARS. Chapter 1 = FAR (Parts 1-99), Chapter 2 = DFARS
    (Parts 200-299). Other chapters = agency FAR supplements (GSAR, VAAR,
    HSAR, etc.).

    For DFARS clauses, use chapter='2' (e.g., section='252.227-7014').

    part/subpart/section accept int or string. Common prefix mistakes like
    section='FAR 15.305' or '48 CFR 15.305' are stripped automatically, and
    trailing paragraph cites like section='15.305(a)(2)' resolve to the base
    section '15.305'.
    """
    title_number = _validate_title_number(title_number)
    date = _validate_date_ymd(date, field="date")
    for field, raw in (("section", section), ("part", part), ("subpart", subpart)):
        _check_cited_title(raw, title_number, field)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True, strip_cites=True)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    chapter = _validate_chapter(chapter, title_number=title_number)
    appendix = _coerce_cfr_str(appendix, field="appendix")
    page = _clamp(page, field="page", lo=1, hi=10_000)
    if title_number == 48 and chapter and not appendix:
        _check_title48_chapter(chapter, section or subpart or part)

    if not any((section, part, subpart, chapter, appendix)):
        raise ValueError(
            "get_cfr_content requires at least one of: section, subpart, part, "
            "chapter, appendix. "
            "Calling without any filter returns the entire title (often 20+ MB)."
        )

    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/full/{date}/title-{title_number}.xml"
    params: dict[str, str] = {}
    if chapter:
        params["chapter"] = chapter
    if part:
        params["part"] = part
    if subpart:
        params["subpart"] = subpart
    if section:
        params["section"] = section
    if appendix:
        params["appendix"] = appendix

    try:
        xml_content = await _get_xml(path, params)
    except RuntimeError as e:
        if appendix and str(e).startswith("HTTP 404"):
            raise RuntimeError(
                f"{e} Appendix names must be eCFR's full name, like 'Appendix II to Part 200' "
                f"(with part='200') or 'Appendix A to Chapter 2' (with chapter='2'); "
                f"list_sections_in_part lists a part's appendices."
            ) from e
        raise

    if raw_xml:
        return {"date": date, "title": title_number, "xml": xml_content}

    parsed = _parse_xml_to_text(xml_content, date)
    parsed["date"] = date
    parsed["title"] = title_number
    if section:
        parsed["section"] = section
    if part:
        parsed["part"] = part
    if subpart:
        parsed["subpart"] = subpart
    if chapter:
        parsed["chapter"] = chapter
    if appendix:
        parsed["appendix"] = appendix
    if "sections" in parsed:
        narrower = (
            "To read one section instead, call get_cfr_content with section= "
            "set to an identifier from 'sections' (list_sections_in_part lists them all)."
        )
    elif section == "2.101" and title_number == 48:
        narrower = "For one FAR definition, find_far_definition returns just that term."
    else:
        narrower = ""
    return _xml_text.paginate(parsed, page, narrower=narrower)


@mcp.tool(annotations={"title": "Get CFR Structure", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_cfr_structure(
    title_number: int = 48,
    date: str | None = None,
    chapter: str | int | None = None,
    subchapter: str | int | None = None,
    part: str | int | None = None,
    subpart: str | int | None = None,
    appendix: str | int | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Get the hierarchical table of contents for a CFR title or subset.

    Returns a nested tree of titles, chapters, parts, subparts, and sections
    with identifiers, descriptions, and byte sizes, plus the date it
    describes.

    IMPORTANT: Does NOT support section-level filtering (returns 400).
    Use part or subpart, then walk the children to find sections.

    Common patterns:
    - part='15' for FAR Part 15 structure
    - subpart='15.3' for just that subpart's sections
    - chapter='1', depth=2 for the FAR's subchapters and parts only
    - appendix='Appendix A to Part 200' with part='200' (title 2) for one appendix

    depth keeps that many levels below the node asked for (part='19',
    depth=1 gives Part 19's subparts); deeper levels are replaced by
    'children_omitted' (how many there were). For the sections of one part,
    list_sections_in_part is shorter. A tree too large
    to send at once (a whole chapter is about 1 MB) is cut to the deepest
    depth that fits, and 'note' says so.

    subchapter needs chapter in Title 48 (each chapter has its own
    subchapter A, B, ...). part/subpart/chapter/appendix accept int or string.
    """
    title_number = _validate_title_number(title_number)
    date = _validate_date_ymd(date, field="date")
    for field, raw in (("part", part), ("subpart", subpart)):
        _check_cited_title(raw, title_number, field)
    chapter = _validate_chapter(chapter, title_number=title_number)
    subchapter = _coerce_cfr_str(subchapter, field="subchapter", maxlen=8)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    appendix = _coerce_cfr_str(appendix, field="appendix")
    if depth is not None:
        depth = _clamp(depth, field="depth", lo=1, hi=10)
    if subchapter and not chapter and title_number == 48:
        raise ValueError(
            "subchapter needs chapter in Title 48: every chapter has its own subchapter "
            "A, B, ... (FAR subchapter A is chapter='1', DFARS subchapter A is chapter='2')."
        )

    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/structure/{date}/title-{title_number}.json"
    params: dict[str, str] = {}
    if chapter:
        params["chapter"] = chapter
    if subchapter:
        params["subchapter"] = subchapter
    if part:
        params["part"] = part
    if subpart:
        params["subpart"] = subpart

    tree = _safe_dict(await _get_json(path, params, timeout=DEFAULT_TIMEOUT_STRUCTURE))
    if appendix:
        # eCFR's structure endpoint has no appendix filter; find it in the tree.
        found: list[dict[str, Any]] = []
        names: list[str] = []

        def look(node: Any) -> None:
            node = _safe_dict(node)
            if node.get("type") == "appendix":
                names.append(str(node.get("identifier")))
                if str(node.get("identifier")).lower() == appendix.lower():
                    found.append(node)
            for child in _as_list(node.get("children")):
                look(child)

        look(tree)
        if not found:
            listed = f" Appendices here: {', '.join(names[:20])}." if names else (
                " Give the part or chapter the appendix belongs to.")
            raise ValueError(f"No appendix named {appendix!r} in this structure.{listed}")
        tree = dict(found[0])
    result = dict(tree)
    result["date"] = date
    # eCFR always answers from the title down; depth counts from the node
    # asked for (the subpart, part, subchapter or chapter), not the title.
    anchor = ("subpart" if subpart else "part" if part else "subchapter" if subchapter
              else "chapter" if chapter else None)
    if depth is not None:
        result = _trim_below(result, anchor, depth)
    elif _xml_text.size_of(result) > _xml_text.PAGE_CHARS:
        full = _xml_text.size_of(result)
        for level in range(6, 0, -1):
            trimmed = _trim_below(result, anchor, level)
            if _xml_text.size_of(trimmed) <= _xml_text.PAGE_CHARS or level == 1:
                break
        result = trimmed
        result["note"] = (
            f"The full tree is about {full:,} characters, too long to send at once, so "
            f"levels below depth {level} are left out (see children_omitted). Ask for a "
            f"part or subpart to see its sections."
        )
    return result


def _trim_below(node: dict[str, Any], anchor: str | None, depth: int) -> dict[str, Any]:
    """Trim depth levels below the first node of type anchor (or below node)."""
    if anchor is None or node.get("type") == anchor:
        return _trim_tree(node, depth)
    children = [_safe_dict(c) for c in _as_list(node.get("children"))]
    out = {k: v for k, v in node.items() if k != "children"}
    if children:
        out["children"] = [_trim_below(c, anchor, depth) for c in children]
    return out


def _trim_tree(node: dict[str, Any], depth: int) -> dict[str, Any]:
    """Keep depth levels of children; count what is cut."""
    out = {k: v for k, v in node.items() if k != "children"}
    children = [_safe_dict(c) for c in _as_list(node.get("children"))]
    if not children:
        return out
    if depth <= 0:
        out["children_omitted"] = len(children)
        return out
    out["children"] = [_trim_tree(c, depth - 1) for c in children]
    return out


@mcp.tool(annotations={"title": "Get Version History", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_version_history(
    title_number: int = 48,
    part: str | int | None = None,
    section: str | int | None = None,
    subpart: str | int | None = None,
    since_date: str | None = None,
    until_date: str | None = None,
    per_page: int = 200,
    page: int = 1,
) -> dict[str, Any]:
    """Get the version history of a CFR section, subpart, or part.

    Returns content_versions (each with date, amendment_date, issue_date,
    identifier, name, substantive and removed), every version eCFR lists:
    all of eCFR's pages are read, so Part 52's 2,264 versions are all
    there. Versions are grouped by section, oldest first.

    since_date/until_date (YYYY-MM-DD) keep versions dated in that range.
    per_page (default 200, max 1000) and page step through long histories;
    total_count and total_pages say how many there are.

    'substantive' is eCFR's flag: true when the version's text differs from
    the one before, including editorial edits such as citation fixes and
    the "Link to an amendment published at ..." notice eCFR adds when a
    rule is published; false when re-issued with no text change. To see
    what actually changed, use compare_versions on the dates.

    'removed' true means the section was removed on that date.

    History starts 2017-01-01 (eCFR's baseline: a 2017-01-01 version means
    unchanged since before 2017). Pre-2017 changes are not tracked.

    part/subpart/section accept int or string.
    """
    title_number = _validate_title_number(title_number)
    for field, raw in (("section", section), ("part", part), ("subpart", subpart)):
        _check_cited_title(raw, title_number, field)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True, strip_cites=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    since_date = _validate_date_ymd(since_date, field="since_date")
    until_date = _validate_date_ymd(until_date, field="until_date")
    per_page = _clamp(per_page, field="per_page", lo=1, hi=_VERSION_PAGE)
    page = _clamp(page, field="page", lo=1, hi=10_000)

    if not any((part, section, subpart)):
        raise ValueError(
            "get_version_history requires at least one of: part, subpart, section."
        )

    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if section:
        params["section"] = section
    if subpart:
        params["subpart"] = subpart

    versions, meta, complete = await _all_versions(title_number, params)
    if not versions:
        what = f"section {section}" if section else (f"subpart {subpart}" if subpart else f"part {part}")
        raise ValueError(
            f"eCFR has no version history for {what} in title {title_number}, so it is "
            f"not in this title (every section in eCFR has at least its 2017-01-01 "
            f"version). Check title_number: for example 200.318 is 2 CFR, not 48 CFR."
        )
    total_listed = len(versions)
    if since_date:
        versions = [v for v in versions if (v.get("date") or "") >= since_date]
    if until_date:
        versions = [v for v in versions if (v.get("date") or "") <= until_date]
    total = len(versions)
    total_pages = max(1, -(-total // per_page))
    if page > total_pages:
        raise ValueError(f"page={page} does not exist; there are {total_pages} page(s) of {per_page}.")
    shown = []
    for v in versions[(page - 1) * per_page: page * per_page]:
        v = {k: val for k, val in v.items() if k != "title"}
        v["name"] = _clean_heading(v.get("name"))
        shown.append(v)

    result: dict[str, Any] = {
        "title": title_number,
        "content_versions": shown,
        "total_count": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "latest_amendment_date": meta.get("latest_amendment_date"),
        "latest_issue_date": meta.get("latest_issue_date"),
    }
    for key, value in (("part", part), ("subpart", subpart), ("section", section),
                       ("since_date", since_date), ("until_date", until_date)):
        if value:
            result[key] = value
    if total != total_listed:
        result["total_before_date_filter"] = total_listed
    if not complete:
        result["truncated"] = True
        result["note"] = (
            f"eCFR lists more than {_MAX_VERSION_PAGES * _VERSION_PAGE:,} versions here; only "
            f"the first {_MAX_VERSION_PAGES * _VERSION_PAGE:,} were read. Ask for a subpart or section."
        )
    elif page < total_pages:
        result["note"] = f"Showing page {page} of {total_pages}; call again with page={page + 1} for more."
    elif total == 0:
        result["note"] = "No versions are dated in that range."
    return result


@mcp.tool(annotations={"title": "Get Ancestry", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_ancestry(
    title_number: int = 48,
    date: str | None = None,
    part: str | int | None = None,
    section: str | int | None = None,
    appendix: str | int | None = None,
    subpart: str | int | None = None,
) -> dict[str, Any]:
    """Get the breadcrumb hierarchy path for a section, part, or appendix.

    Returns ancestors from title down to the target node: title > chapter >
    subchapter > part > subpart > section. Useful for understanding where
    a section sits in the CFR hierarchy and what regulation it belongs to.

    part/subpart/section/appendix accept int or string. The answer says
    which date it describes.
    """
    title_number = _validate_title_number(title_number)
    date = _validate_date_ymd(date, field="date")
    for field, raw in (("section", section), ("part", part), ("subpart", subpart)):
        _check_cited_title(raw, title_number, field)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True, strip_cites=True)
    appendix = _coerce_cfr_str(appendix, field="appendix")
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)

    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/ancestry/{date}/title-{title_number}.json"
    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if section:
        params["section"] = section
    if appendix:
        params["appendix"] = appendix
    if subpart:
        params["subpart"] = subpart

    result = dict(await _get_json(path, params))
    result["date"] = date
    return result


@mcp.tool(annotations={"title": "Search CFR", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def search_cfr(
    query: str,
    title: int | None = None,
    chapter: str | int | None = None,
    part: str | int | None = None,
    subpart: str | int | None = None,
    section: str | int | None = None,
    current_only: bool = True,
    last_modified_after: str | None = None,
    last_modified_before: str | None = None,
    order: str | None = None,
    agency_slugs: list[str] | str | None = None,
    per_page: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """Full-text search across the Code of Federal Regulations.

    Returns matching sections with excerpts, headings, scores, and hierarchy.

    current_only=True (default) returns only text in effect now. eCFR's own
    "current" index still lists some superseded and removed versions, so
    each hit is checked against the section's version history: older
    copies of a section are dropped, and hits whose text has since been
    replaced or removed are dropped and listed under current_check
    ('superseded' with the current version's date, 'removed' with the
    removal date). Up to 10 parts per page are checked; any hit not
    checked is marked. current_only=False returns every historical
    version, so a section amended 5 times appears 5 times.

    Search caps at 10,000 total results. Use hierarchy filters (title,
    chapter, part) to narrow if you hit the cap. chapter/part/subpart/section
    filters need a title; without one, title 48 is assumed (title_assumed
    says so). Labels like 'FAR Part 15', 'Subpart 15.3' or '§ 52.212-5' are
    read as 15, 15.3 and 52.212-5. Most titles other than 48 number chapters
    in Roman numerals (2 CFR chapter 'II').

    order controls result ordering: 'relevance' (default), 'newest_first',
    'oldest_first', 'hierarchy', or 'citations'.

    agency_slugs filters to one or more agencies (single slug string or a
    list, e.g. 'defense-acquisition-regulations-system'). Use list_agencies()
    to find slugs.

    last_modified_after/before use YYYY-MM-DD format and filter by the
    date sections were last amended. Useful for finding recent regulatory changes.

    per_page accepts 1 to 5000 (default 20); paginate with page for more.
    """
    q = _strip_or_none(query)
    if q is None:
        raise ValueError("query is required and cannot be empty or whitespace-only.")
    q = _clamp_str_len(q, field="query", maximum=500)
    q = _validate_query_safe(q, field="query")

    per_page = _clamp(per_page, field="per_page", lo=1, hi=SEARCH_MAX_PER_PAGE)
    page = _clamp(page, field="page", lo=1, hi=SEARCH_MAX_TOTAL)
    if page * per_page > SEARCH_MAX_TOTAL:
        raise ValueError(
            f"page {page} of {per_page} reaches past result {SEARCH_MAX_TOTAL:,}, eCFR's limit. "
            f"Narrow the search with title, chapter or part filters instead."
        )
    if title is not None:
        title = _validate_title_number(title, field="title")
    for field, raw in (("section", section), ("part", part), ("subpart", subpart)):
        cited = _cited_title(raw)
        if cited is not None and title is None:
            title = cited
        _check_cited_title(raw, title if title is not None else 48, field)
    assumed_title = False
    if title is None and any(v is not None for v in (chapter, part, subpart, section)):
        # eCFR refuses hierarchy filters without a title; these are FAR questions.
        title, assumed_title = 48, True
    chapter = _validate_chapter(chapter, title_number=title)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True, strip_cites=True)
    if title == 48 and chapter:
        _check_title48_chapter(chapter, part or subpart or section)
    last_modified_after = _validate_date_ymd(last_modified_after, field="last_modified_after")
    last_modified_before = _validate_date_ymd(last_modified_before, field="last_modified_before")
    order_clean = _strip_or_none(order)
    if order_clean is not None:
        order_clean = order_clean.lower()
        if order_clean not in SEARCH_ORDERS:
            raise ValueError(
                f"order must be one of {sorted(SEARCH_ORDERS)}. Got {order!r}."
            )
    slugs = _validate_agency_slugs(agency_slugs)
    if slugs:
        await _check_agency_slugs(slugs)

    params: dict[str, Any] = {"query": q}
    if title is not None:
        params["hierarchy[title]"] = str(title)
    if chapter:
        params["hierarchy[chapter]"] = chapter
    if part:
        params["hierarchy[part]"] = part
    if subpart:
        params["hierarchy[subpart]"] = subpart
    if section:
        params["hierarchy[section]"] = section
    if current_only:
        params["date"] = "current"
    if last_modified_after:
        params["last_modified_on_or_after"] = last_modified_after
    if last_modified_before:
        params["last_modified_on_or_before"] = last_modified_before
    if order_clean:
        params["order"] = order_clean
    if slugs:
        # httpx expands a list value into repeated agency_slugs[] params.
        params["agency_slugs[]"] = slugs
    params["per_page"] = str(per_page)
    params["page"] = str(page)

    data = _plain_excerpts(await _get_json("/api/search/v1/results", params))
    if (not _as_list(data.get("results")) and title not in (None, 48) and chapter
            and chapter.isdigit() and 0 < int(chapter) < 40):
        # Most titles number chapters in Roman numerals: '2' finds nothing in 2 CFR.
        roman = _roman(int(chapter))
        probe = await _get_json("/api/search/v1/results",
                                {**params, "hierarchy[chapter]": roman, "per_page": "1", "page": "1"})
        if _as_list(_safe_dict(probe).get("results")):
            raise ValueError(
                f"Title {title} numbers its chapters in Roman numerals, so chapter='{chapter}' "
                f"finds nothing. Use chapter='{roman}'."
            )
    if assumed_title:
        data["title_assumed"] = "48 (no title was given; pass title= to search another title)"
    if not current_only:
        return data
    return await _only_current(data)


_EXCERPT_TAGS = re.compile(r"<[^>]+>")


def _plain_excerpts(data: dict[str, Any]) -> dict[str, Any]:
    """eCFR's excerpts carry HTML highlight tags; send plain text."""
    data = dict(data)
    rows = []
    for row in _as_list(data.get("results")):
        row = dict(_safe_dict(row))
        excerpt = row.get("full_text_excerpt")
        if isinstance(excerpt, str):
            row["full_text_excerpt"] = " ".join(html.unescape(_EXCERPT_TAGS.sub("", excerpt)).split())
        # Drop the empty levels (subtitle, subject_group...) eCFR lists on every hit.
        for key in ("hierarchy", "hierarchy_headings", "headings"):
            if isinstance(row.get(key), dict):
                row[key] = {k: v for k, v in row[key].items() if v is not None}
        rows.append(row)
    data["results"] = rows
    return data


_ROMAN = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _roman(number: int) -> str:
    out = ""
    for value, letters in _ROMAN:
        while number >= value:
            out += letters
            number -= value
    return out


# How many parts' version histories one search page may read.
_CURRENT_CHECK_PARTS = 10


async def _only_current(data: dict[str, Any]) -> dict[str, Any]:
    """Drop search hits that are not the section's current text, and say which.

    eCFR's search index leaves ends_on empty on many superseded and removed
    versions, so date=current still returns them. The version history is
    the authority: a hit is current only if it is the section's newest
    version and that version is not a removal.
    """
    rows = [_safe_dict(r) for r in _as_list(data.get("results"))]
    parts: list[tuple[str, str]] = []
    for row in rows:
        h = _safe_dict(row.get("hierarchy"))
        key = (str(h.get("title") or ""), str(h.get("part") or ""))
        if key[0] and key[1] and key not in parts:
            parts.append(key)
    latest: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for title_s, part_s in parts[:_CURRENT_CHECK_PARTS]:
        title_n = _safe_int(title_s)
        if title_n is None:
            continue
        versions, _, _ = await _all_versions(title_n, {"part": part_s})
        latest[(title_s, part_s)] = _latest_versions(versions)

    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    superseded: dict[str, dict[str, Any]] = {}
    removed: dict[str, dict[str, Any]] = {}
    unchecked = 0
    current_ids: set[str] = set()
    for row in rows:
        h = _safe_dict(row.get("hierarchy"))
        title_s, part_s = str(h.get("title") or ""), str(h.get("part") or "")
        ident = h.get("section") or h.get("appendix")
        history = latest.get((title_s, part_s))
        newest = history.get(ident) if (history is not None and ident) else None
        if newest is None:
            row["current_check"] = "not checked"
            unchecked += 1
            kept.append(row)
            continue
        starts = row.get("starts_on") or ""
        if newest.get("removed"):
            removed.setdefault(ident, {"section": ident, "removed_on": newest.get("date"),
                                       "matched_text_from": starts})
            continue
        if starts < (newest.get("date") or ""):
            superseded.setdefault(ident, {"section": ident, "matched_text_from": starts,
                                          "current_version_from": newest.get("date")})
            continue
        if (title_s, ident) in seen:
            duplicates += 1
            continue
        seen.add((title_s, ident))
        current_ids.add(ident)
        kept.append(row)
    # A section whose current version is also in the results was only a duplicate.
    replaced = [v for k, v in superseded.items() if k not in current_ids]
    duplicates += len(superseded) - len(replaced)

    result = dict(data)
    result["results"] = kept
    check: dict[str, Any] = {
        "hits_on_page": len(rows),
        "kept": len(kept),
        "older_copies_dropped": duplicates,
    }
    if replaced:
        check["superseded"] = replaced
    if removed:
        check["removed"] = list(removed.values())
    if unchecked:
        check["not_checked"] = unchecked
    notes = []
    if replaced:
        notes.append(
            f"{len(replaced)} hit(s) matched text that has since been replaced; the current "
            f"version (current_version_from) does not match this search. Read it with "
            f"get_cfr_content before relying on the old wording."
        )
    if removed:
        notes.append(f"{len(removed)} hit(s) are sections that have been removed (removed_on).")
    if unchecked:
        notes.append(
            f"{unchecked} hit(s) could not be checked against the version history "
            f"(marked current_check='not checked'); narrow the search to check them."
        )
    if notes:
        check["note"] = " ".join(notes)
    result["current_check"] = check
    return result


async def _check_agency_slugs(slugs: list[str]) -> None:
    """Refuse a slug eCFR doesn't know: its search answers 0 results instead of an error."""
    data = await _get_json("/api/admin/v1/agencies.json")
    known: dict[str, str] = {}   # slug -> name

    def walk(agency: dict[str, Any]) -> None:
        if agency.get("slug"):
            known[agency["slug"]] = agency.get("name") or agency["slug"]
            if agency.get("short_name"):
                aliases[str(agency["short_name"]).lower()] = agency["slug"]
        for child in _as_list(agency.get("children")):
            walk(_safe_dict(child))

    aliases: dict[str, str] = {}
    for agency in _as_list(_safe_dict(data).get("agencies")):
        walk(_safe_dict(agency))
    if not known:
        return  # agency list unavailable; let eCFR answer
    for slug in slugs:
        if slug in known:
            continue
        guesses: list[str] = []
        if slug in aliases:
            guesses.append(aliases[slug])
        words = [w for w in slug.split("-") if len(w) > 2]
        guesses += [k for k in known if words and all(w in k for w in words)]
        guesses += difflib.get_close_matches(slug, list(known), n=3, cutoff=0.6)
        guesses = list(dict.fromkeys(guesses))[:5]
        hint = f" Did you mean: {', '.join(guesses)}?" if guesses else ""
        raise ValueError(
            f"agency_slugs entry {slug!r} is not an eCFR agency, so the search would "
            f"silently find nothing.{hint} list_agencies() lists every slug."
        )


# A reference can point at a subtitle, chapter, subchapter or part: the
# Federal Travel Regulation is 41 CFR subtitle F, with no chapter at all.
_REF_KEYS = ("title", "subtitle", "chapter", "subchapter", "part")


def _agency_refs_with_children(agency: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect cfr_references from an agency and all of its descendants.

    Title 48 chapter mappings often live on child agencies only: DFARS
    chapter 2 sits on the Defense Acquisition Regulations System child of
    DoD, HSAR chapter 30 on a child of DHS. A summary built from top-level
    references alone loses exactly the biggest FAR supplements (round 6).
    """
    refs: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def _walk(a: dict[str, Any]) -> None:
        for r in _as_list(a.get("cfr_references")):
            r = _safe_dict(r)
            key = tuple(r.get(k) for k in _REF_KEYS)
            if key in seen:
                continue
            seen.add(key)
            refs.append(r)
        for child in _as_list(a.get("children")):
            _walk(_safe_dict(child))

    _walk(_safe_dict(agency))
    return refs


@mcp.tool(annotations={"title": "List Agencies", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def list_agencies(summary_only: bool = True) -> dict[str, Any]:
    """List all agencies with their CFR title and chapter references.

    Returns agency names, slugs, and which CFR titles/chapters they own.
    Useful for finding which chapter corresponds to an agency's FAR supplement.

    summary_only (default True) strips the `children` and most of
    `cfr_references` to keep the response compact (~20 KB vs ~100 KB).
    References owned by child agencies are merged into the parent row, so
    chapter lookups like DFARS (chapter 2, on a DoD child agency) still work
    in summary mode. Set False for the full raw payload including children.
    """
    data = await _get_json("/api/admin/v1/agencies.json")
    agencies = _as_list(_safe_dict(data).get("agencies"))
    if not summary_only:
        return {"agencies": agencies, "count": len(agencies)}
    summarized: list[dict[str, Any]] = []
    for a in agencies:
        a = _safe_dict(a)
        refs = _agency_refs_with_children(a)
        summarized.append({
            "name": a.get("name"),
            "short_name": a.get("short_name"),
            "slug": a.get("slug"),
            "cfr_references": [
                {k: r.get(k) for k in _REF_KEYS if r.get(k) is not None or k in ("title", "chapter")}
                for r in refs
            ],
            "child_count": len(_as_list(a.get("children"))),
        })
    return {
        "agencies": summarized,
        "count": len(summarized),
        "summary_only": True,
    }


@mcp.tool(annotations={"title": "Get Corrections", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_corrections(
    title_number: int = 48,
    limit: int = 50,
    since_year: int | None = None,
    section: str | int | None = None,
    part: str | int | None = None,
    chapter: str | int | None = None,
) -> dict[str, Any]:
    """Get editorial corrections for a CFR title, newest first.

    Returns corrections with CFR references, corrective actions, error
    dates, and FR citations, sorted by the date the error was corrected,
    newest first. Useful for checking whether a section's current text has
    been corrected since its last amendment.

    section (e.g. '52.204-21'), part (e.g. '52') or chapter (e.g. '2' for
    the DFARS) keeps only corrections that touch it. since_year keeps corrections with year >= since_year.
    limit caps how many are returned (default 50, max 1000); truncated
    says whether older ones were left out. Title 48 has ~280 corrections
    since 2005.
    """
    title_number = _validate_title_number(title_number)
    limit = _clamp(limit, field="limit", lo=1, hi=1000)
    if since_year is not None:
        since_year = _clamp(since_year, field="since_year", lo=1995, hi=2100)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True, strip_cites=True)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    chapter = _validate_chapter(chapter, title_number=title_number)

    data = await _get_json(
        "/api/admin/v1/corrections.json",
        {"title": str(title_number)},
    )
    corrections = [_safe_dict(c) for c in _as_list(_safe_dict(data).get("ecfr_corrections"))]
    total = len(corrections)

    if since_year is not None:
        corrections = [
            c for c in corrections
            if _safe_int(c.get("year"), default=0) >= since_year
        ]
    if section or part or chapter:
        def touches(c: dict[str, Any]) -> bool:
            for ref in _as_list(c.get("cfr_references")):
                h = _safe_dict(_safe_dict(ref).get("hierarchy"))
                if section and str(h.get("section")) == section:
                    return True
                if part and str(h.get("part")) == part:
                    return True
                if chapter and str(h.get("chapter")) == chapter:
                    return True
            return False
        corrections = [c for c in corrections if touches(c)]
    # eCFR lists them oldest first; the recent ones are what people need.
    corrections.sort(key=lambda c: (c.get("error_corrected") or "", c.get("position") or 0), reverse=True)

    filtered_count = len(corrections)
    truncated = filtered_count > limit
    corrections = corrections[:limit]

    result: dict[str, Any] = {
        "title": title_number,
        "order": "newest first (by error_corrected)",
        "corrections": corrections,
        "count_returned": len(corrections),
        "count_filtered": filtered_count,
        "count_total": total,
        "truncated": truncated,
        "since_year": since_year,
        "limit": limit,
    }
    if section:
        result["section"] = section
    if part:
        result["part"] = part
    if chapter:
        result["chapter"] = chapter
    if truncated:
        result["note"] = f"Showing the newest {limit} of {filtered_count}; raise limit for older ones."
    return result


# ---------------------------------------------------------------------------
# Workflow / convenience tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Lookup FAR Clause", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def lookup_far_clause(
    section_id: str | int,
    chapter: str | int | None = None,
    date: str | None = None,
    page: int = 1,
) -> dict[str, Any]:
    """Convenience tool: look up the current text of a FAR, DFARS or FAR supplement section or clause.

    Pass a section identifier like '15.305', '52.212-4', '2.101',
    'DFARS 252.204-7012' or '552.238-81'. The chapter comes from the number
    (52.x = FAR, 252.x = DFARS, 552.x = GSAR, 852.x = VAAR, 1852.x = NFS,
    3052.x = HSAR), so chapter is optional. Prefixes like 'FAR', 'DFARS',
    '§' and '48 CFR', en dashes, and trailing paragraph cites such as
    '(d)(11)(xviii)' are handled.

    Auto-resolves the latest available date. Returns parsed clean text
    with heading, paragraphs and citations, plus tables, notes (such as
    drafting notes, which are not clause text), examples, images and
    pending_amendments when present; see get_cfr_content. A clause longer
    than about 60,000 characters comes in pages: use page=2 and so on.

    Common FAR sections: 2.101 (Definitions), 9.104-1 (Responsibility),
    15.305 (Proposal Evaluation), 19.502-2 (Small Business Set-Asides),
    52.212-4 (Commercial Terms), 52.212-5 (Required Commercial Terms).
    """
    section_id = _coerce_cfr_str(section_id, field="section_id", strip_prefixes=True, strip_cites=True)
    if not section_id:
        raise ValueError(
            "section_id is required. Pass a section like '15.305', '52.212-4' or '252.204-7012'. "
            f"Common sections: {', '.join(list(COMMON_FAR_SECTIONS.keys())[:5])}."
        )
    chapter = _validate_chapter(chapter, title_number=48)
    chapter = _check_title48_chapter(chapter, section_id)
    date = _validate_date_ymd(date, field="date")
    if date is None:
        date = await _resolve_date(48)
    return await get_cfr_content(
        title_number=48,
        date=date,
        chapter=chapter,
        section=section_id,
        page=page,
    )


@mcp.tool(annotations={"title": "Compare Versions", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def compare_versions(
    section_id: str | int,
    date_before: str,
    date_after: str,
    title_number: int = 48,
    chapter: str | int | None = None,
    changes_only: bool = False,
) -> dict[str, Any]:
    """Compare the text of a CFR section at two different dates.

    Useful for understanding what changed in a regulatory amendment. Returns
    'changes' (each paragraph that was added, removed or changed, with its
    before and after text; also heading, table and pending-amendment-link
    changes), 'identical' when nothing differs, and the parsed text at both
    dates side by side. When both texts together are too long to send, the
    full texts are left out (texts_omitted) and 'changes' is kept.
    changes_only=True leaves the full texts out every time: the short answer
    to "what changed".

    Dates must be in YYYY-MM-DD format and within the eCFR's tracking range
    (January 2017 to present). Both dates must not exceed the title's
    up_to_date_as_of value.

    This tool always returns the section-level XML parsed -- pass a small
    section_id like '15.305', not a whole part. Whole-part comparisons can
    exceed 100 KB per side.
    """
    title_number = _validate_title_number(title_number)
    _check_cited_title(section_id, title_number, "section_id")
    section_id = _coerce_cfr_str(section_id, field="section_id", strip_prefixes=True, strip_cites=True)
    if not section_id:
        raise ValueError(
            "section_id is required. Pass a section like '15.305', not a whole part."
        )
    date_before = _validate_date_ymd(date_before, field="date_before")
    date_after = _validate_date_ymd(date_after, field="date_after")
    if date_before is None or date_after is None:
        raise ValueError("Both date_before and date_after are required YYYY-MM-DD dates.")
    if date_before == date_after:
        raise ValueError(
            f"date_before and date_after are identical ({date_before}); "
            f"there is nothing to compare. Pick two distinct dates."
        )
    if date_before > date_after:
        raise ValueError(
            f"date_before ({date_before}) must be earlier than date_after ({date_after})."
        )
    if date_before < ECFR_EARLIEST_DATE:
        raise ValueError(
            f"date_before ({date_before}) precedes {ECFR_EARLIEST_DATE}. eCFR "
            f"point-in-time history begins {ECFR_EARLIEST_DATE}; earlier "
            f"snapshots do not exist and always return 404."
        )
    chapter = _validate_chapter(chapter, title_number=title_number)
    if title_number == 48:
        chapter = _check_title48_chapter(chapter, section_id)

    latest = await _resolve_date(title_number)
    if date_after > latest:
        raise ValueError(
            f"date_after ({date_after}) exceeds the latest available eCFR snapshot "
            f"({latest}) for title {title_number}. Choose a date on or before {latest}; "
            "an unavailable snapshot does not mean the section was removed."
        )

    params: dict[str, str] = {}
    if chapter:
        params["chapter"] = chapter

    async def text_on(day: str) -> dict[str, Any]:
        try:
            xml = await _get_xml(
                f"/api/versioner/v1/full/{day}/title-{title_number}.xml",
                {**params, "section": section_id},
            )
        except RuntimeError as e:
            if not str(e).startswith("HTTP 404"):
                raise
            return {"date": day, "present": False}
        return {"date": day, **_parse_xml_to_text(xml, day)}

    before = await text_on(date_before)
    after = await text_on(date_after)
    if before.get("present") is False and after.get("present") is False:
        raise ValueError(
            f"Section {section_id} is not in the eCFR text of title {title_number} on "
            f"{date_before} or on {date_after}. Check the section number and title; "
            f"get_version_history(section='{section_id}') lists the dates it existed."
        )
    if before.get("present") is False or after.get("present") is False:
        added = before.get("present") is False
        missing, there = (date_before, after) if added else (date_after, before)
        result = {
            "section": section_id,
            "title": title_number,
            "identical": False,
            "change_count": 1,
            "changes": [{
                "change": "section added" if added else "section removed",
                "detail": f"{section_id} is not in the eCFR text on {missing}; it is on {there['date']}.",
            }],
            "before": before,
            "after": after,
            "note": (
                f"{section_id} was {'added' if added else 'removed'} between {date_before} and "
                f"{date_after}. get_version_history(section='{section_id}') gives the exact date."
            ),
        }
        if changes_only or _xml_text.size_of(result) > _xml_text.PAGE_CHARS:
            result["before"] = {"date": date_before, "present": not added}
            result["after"] = {"date": date_after, "present": added}
            result["texts_omitted"] = True
        return result
    changes = _text_changes(before, after)
    result: dict[str, Any] = {
        "section": section_id,
        "title": title_number,
        "identical": not changes,
        "change_count": len(changes),
        "changes": changes,
        "before": before,
        "after": after,
    }
    if not changes:
        result["note"] = (
            f"The parsed text is the same on {date_before} and {date_after}. A version "
            f"history entry between these dates may be a re-issue or a link notice only."
        )
    if not changes_only and _xml_text.size_of(result) <= _xml_text.PAGE_CHARS:
        return result
    # Too long to send (or not wanted): keep the changes, drop the full texts.
    for side in (before, after):
        for key in ("paragraphs", "tables", "notes", "examples", "citations", "editorial_notes",
                    "images", "table_note", "hierarchy_metadata", "sections"):
            side.pop(key, None)
    result["texts_omitted"] = True
    result["note"] = (
        ("Only the changes are shown (changes_only)." if changes_only else
         "Both full texts together are too long to send, so only the changes are shown.")
        + f" Read either full text with get_cfr_content(section='{section_id}', "
        f"date=...), which comes in pages."
    )
    if not changes:
        result["note"] = f"The parsed text is the same on {date_before} and {date_after}. " + result["note"]
    budget = _xml_text.PAGE_CHARS - _xml_text.size_of({**result, "changes": []})
    kept: list[dict[str, Any]] = []
    for change in changes:
        budget -= _xml_text.size_of(change) + 1
        if budget < 0:
            break
        kept.append(change)
    if len(kept) < len(changes):
        result["changes"] = kept
        result["changes_truncated"] = True
        result["note"] += (
            f" Only the first {len(kept)} of {len(changes)} changes fit; compare two "
            f"dates closer together (get_version_history lists the amendment dates)."
        )
    return result


def _text_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """What differs between two parsed texts of one section, paragraph by paragraph."""
    changes: list[dict[str, Any]] = []
    if before.get("heading") != after.get("heading"):
        changes.append({"change": "heading", "before": before.get("heading"), "after": after.get("heading")})
    old, new = before.get("paragraphs", []), after.get("paragraphs", [])
    names = {"replace": "changed", "delete": "removed", "insert": "added"}
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        change: dict[str, Any] = {"change": names[op], "before_paragraph": i1 + 1, "after_paragraph": j1 + 1}
        if i2 > i1:
            change["before"] = old[i1:i2]
        if j2 > j1:
            change["after"] = new[j1:j2]
        changes.append(change)
    for key in ("tables", "notes", "examples"):
        if before.get(key, []) != after.get(key, []):
            changes.append({"change": key, "detail": f"{key} differ; compare 'before' and 'after'"})
    if before.get("pending_amendments", []) != after.get("pending_amendments", []):
        changes.append({
            "change": "pending amendment link",
            "before": before.get("pending_amendments", []),
            "after": after.get("pending_amendments", []),
        })
    return changes


@mcp.tool(annotations={"title": "List Sections in Part", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def list_sections_in_part(
    part_number: str | int,
    chapter: str | int | None = None,
    title_number: int = 48,
    date: str | None = None,
    subpart: str | int | None = None,
    detail: bool = False,
    page: int = 1,
) -> dict[str, Any]:
    """List all sections and appendices in a CFR part with their headings.

    Returns 'sections' in order, each {identifier, heading}, with
    type='appendix' on appendices (2 CFR 200's Appendix I-XII, for example)
    and reserved=true on reserved sections, plus 'subparts' (each with its
    heading, section_count and first and last section). Useful for seeing
    the scope of a part before reading specific sections.

    The part number alone is enough: chapter is optional (Title 48 parts
    are unique: 52 = FAR, 252 = DFARS, 552 = GSAR) and the answer reports
    the chapter the part is in. subpart (e.g. '52.2') lists one subpart.
    A list too long to send at once (FAR Part 52 has 680 entries) comes in
    pages: page and total_pages say where you are; page=2 gets the rest.
    detail=True adds eCFR's label, size and received_on for each entry
    (received_on is when eCFR processed the text, not when it was amended;
    get_version_history has amendment dates).

    part_number accepts int or string.
    """
    title_number = _validate_title_number(title_number)
    for field, raw in (("part_number", part_number), ("subpart", subpart)):
        _check_cited_title(raw, title_number, field)
    part_number = _coerce_cfr_str(part_number, field="part_number", strip_prefixes=True)
    if not part_number:
        raise ValueError("part_number is required. Pass something like '15' or '252'.")
    chapter = _validate_chapter(chapter, title_number=title_number)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    date = _validate_date_ymd(date, field="date")
    page = _clamp(page, field="page", lo=1, hi=1000)

    if date is None:
        date = await _resolve_date(title_number)

    params: dict[str, str] = {"part": part_number}
    if chapter:
        params["chapter"] = chapter
    if subpart:
        params["subpart"] = subpart

    structure = await _get_json(
        f"/api/versioner/v1/structure/{date}/title-{title_number}.json",
        params,
        timeout=DEFAULT_TIMEOUT_STRUCTURE,
    )

    entries: list[dict[str, Any]] = []
    subparts: list[dict[str, Any]] = []
    found_chapter: list[Any] = []

    def walk(node: Any, current_subpart: dict[str, Any] | None) -> None:
        node = _safe_dict(node)
        kind = node.get("type")
        if kind == "chapter" and not found_chapter:
            found_chapter.append(node.get("identifier"))
        if kind == "subpart":
            current_subpart = {"identifier": node.get("identifier"),
                               "heading": node.get("label_description"), "section_count": 0}
            subparts.append(current_subpart)
        if kind in ("section", "appendix"):
            entry: dict[str, Any] = {"identifier": node.get("identifier"),
                                     "heading": node.get("label_description")}
            if kind == "appendix":
                entry["type"] = "appendix"
            if node.get("reserved"):
                entry["reserved"] = True
            if detail:
                for k in ("label", "size", "received_on"):
                    entry[k] = node.get(k)
            entries.append(entry)
            if current_subpart is not None:
                current_subpart["section_count"] += 1
                current_subpart.setdefault("first_section", entry["identifier"])
                current_subpart["last_section"] = entry["identifier"]
            return
        for child in _as_list(node.get("children")):
            walk(child, current_subpart)

    walk(structure, None)
    if chapter and found_chapter and str(found_chapter[0]) != chapter:
        raise ValueError(
            f"Part {part_number} is in chapter {found_chapter[0]}, not chapter {chapter}. "
            f"Leave chapter out; the part number is enough."
        )
    result: dict[str, Any] = {
        "title": title_number,
        "chapter": found_chapter[0] if found_chapter else chapter,
        "part": part_number,
        "date": date,
        "section_count": sum(1 for e in entries if e.get("type") != "appendix"),
        "appendix_count": sum(1 for e in entries if e.get("type") == "appendix"),
    }
    if subpart:
        result["subpart"] = subpart
    if subparts:
        result["subparts"] = subparts
    result["sections"] = entries
    if _xml_text.size_of(result) <= _xml_text.PAGE_CHARS:
        if page != 1:
            raise ValueError(f"This list fits on one page; page={page} does not exist.")
        return result
    # Too long to send at once: split the entries into pages.
    budget = _xml_text.PAGE_CHARS - _xml_text.size_of({**result, "sections": []}) - 600
    pages: list[list[dict[str, Any]]] = [[]]
    used = 0
    for entry in entries:
        cost = _xml_text.size_of(entry, 2) + 2
        if pages[-1] and used + cost > budget:
            pages.append([])
            used = 0
        pages[-1].append(entry)
        used += cost
    if page > len(pages):
        raise ValueError(f"page={page} does not exist; this list has {len(pages)} pages.")
    result["sections"] = pages[page - 1]
    result["page"] = page
    result["total_pages"] = len(pages)
    first, last = pages[page - 1][0]["identifier"], pages[page - 1][-1]["identifier"]
    result["page_note"] = (
        f"This list is too long to send at once, so it comes in {len(pages)} pages. "
        f"This is page {page} of {len(pages)} ({first} to {last})."
        + (f" Call again with page={page + 1} for the rest." if page < len(pages) else "")
        + " subpart= lists one subpart."
    )
    return result


@mcp.tool(annotations={"title": "Find FAR Definition", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def find_far_definition(
    term: str,
    date: str | None = None,
    max_matches: int = 20,
) -> dict[str, Any]:
    """Find a term's definition in FAR 2.101, the FAR's main definitions section.

    Returns each matching definition whole (the defining paragraph and every
    sub-paragraph under it), first, marked kind='definition'. Matching
    ignores case, hyphens, spacing, plurals, a trailing "means", and the
    acronym 2.101 puts in a name, so 'service-disabled veteran-owned small
    business concern', 'SDVOSB concern', 'COTS', 'commercial services' and
    'contract means' all find their definitions. Other 2.101 paragraphs that
    use the term (whole words only) follow as kind='mention', each naming
    the definition it sits in.

    When 2.101 doesn't define the term, the tool searches the rest of the
    FAR (chapter 1), then the DFARS (chapter 2), for "<term>" means and
    returns where it is defined, with the definition text, under
    defined_elsewhere (for example 19.001 and 52.219-14 for 'similarly
    situated entity'; 204.7301 for 'covered defense information'), plus
    did_you_mean suggestions from 2.101.

    term must be at least 3 characters. max_matches caps the number of
    matches returned (default 20, max 100); definitions are never cut, and
    truncated says whether mentions were left out.
    """
    term_clean = _strip_or_none(term)
    if term_clean is None:
        raise ValueError("term is required and cannot be empty or whitespace-only.")
    if len(term_clean) < 3:
        raise ValueError(
            f"term must be at least 3 characters (got {len(term_clean)}). "
            f"Short terms match too broadly and return junk."
        )
    term_clean = _clamp_str_len(term_clean, field="term", maximum=100)
    max_matches = _clamp(max_matches, field="max_matches", lo=1, hi=100)
    date = _validate_date_ymd(date, field="date")
    if not _definitions.clean_query(term_clean):
        raise ValueError(f"term={term!r} has no words left to look up.")

    if date is None:
        date = await _resolve_date(48)

    xml = await _get_xml(
        f"/api/versioner/v1/full/{date}/title-48.xml",
        {"section": "2.101"},
    )
    paragraphs = _parse_xml_to_text(xml, date).get("paragraphs", [])
    found = _definitions.find(paragraphs, term_clean)
    definitions, mentions = found["definitions"], found["mentions"]
    room = max(0, max_matches - len(definitions))
    matches = definitions + mentions[:room]

    result: dict[str, Any] = {
        "section": "2.101",
        "date": date,
        "search_term": term_clean,
        "definition_count": len(definitions),
        "match_count": len(matches),
        "total_matches": len(definitions) + len(mentions),
        "truncated": len(mentions) > room,
        "max_matches": max_matches,
        "matches": matches,
        "total_paragraphs": len(paragraphs),
    }
    if definitions:
        result["note"] = (
            "Matches with kind='definition' come first and are complete: the defining "
            "paragraph and every paragraph under it. kind='mention' entries are other "
            "definitions that use the term."
        )
        return result

    result["did_you_mean"] = found["did_you_mean"]
    elsewhere = await _defined_elsewhere(found["query"], date, "1")
    if not any(e.get("definition") for e in elsewhere):
        # Not in the FAR at all: it may be a DFARS term ("covered defense information").
        dfars = await _defined_elsewhere(found["query"], date, "2")
        if any(e.get("definition") for e in dfars):
            elsewhere = dfars + elsewhere
    result["defined_elsewhere"] = elsewhere
    if any(e.get("definition") and e.get("chapter") == "2" for e in elsewhere):
        result["note"] = (
            f"The FAR does not define '{found['query']}'; the DFARS (Title 48 chapter 2) "
            f"does: see defined_elsewhere (section, heading and the definition text)."
        )
    elif any(e.get("definition") for e in elsewhere):
        result["note"] = (
            f"FAR 2.101 does not define '{found['query']}'. It is defined elsewhere in the "
            f"FAR: see defined_elsewhere (section, heading and the definition text)."
        )
    elif elsewhere:
        result["note"] = (
            f"FAR 2.101 does not define '{found['query']}'. These FAR sections use the "
            f"phrase near 'means' but no definition paragraph was confirmed; read them "
            f"with lookup_far_clause."
        )
    else:
        result["note"] = (
            f"FAR 2.101 does not define '{found['query']}', and no other FAR (chapter 1) "
            f"or DFARS (chapter 2) section defines it with 'means'. For another agency "
            f"supplement, try search_cfr with query='\"{found['query']}\" means', title=48 "
            f"and that chapter." + (
                f" Close 2.101 terms: {', '.join(found['did_you_mean'])}."
                if found["did_you_mean"] else ""
            )
        )
    return result


async def _defined_elsewhere(query: str, date: str, chapter: str = "1") -> list[dict[str, Any]]:
    """Title 48 sections outside 2.101 that define query, with the definition text.

    Searches the chapter (1 = FAR, 2 = DFARS) for '"query" means', keeps the
    newest version of each section, and reads up to three of them to find
    the defining paragraphs.
    """
    params = {
        "query": f'"{query}" means',
        "hierarchy[title]": "48",
        "hierarchy[chapter]": chapter,
        "date": date,
        "per_page": "20",
    }
    data = await _get_json("/api/search/v1/results", params)
    newest: dict[str, dict[str, Any]] = {}
    for row in _as_list(_safe_dict(data).get("results")):
        row = _safe_dict(row)
        section = _safe_dict(row.get("hierarchy")).get("section")
        if not section or section == "2.101":
            continue
        kept = newest.get(section)
        if kept is None or (row.get("starts_on") or "") > (kept.get("starts_on") or ""):
            newest[section] = row
    out: list[dict[str, Any]] = []
    read = 0
    # Definitions sections (19.001, 4.2101) first, then search order.
    ordered = sorted(newest.items(), key=lambda item: "definition" not in str(
        _safe_dict(item[1].get("headings")).get("section") or "").lower())
    for section, row in ordered:
        entry: dict[str, Any] = {
            "section": section,
            "heading": _safe_dict(row.get("headings")).get("section"),
        }
        if chapter != "1":
            entry["chapter"] = chapter
        if read < 3:
            read += 1
            try:
                xml = await _get_xml(
                    f"/api/versioner/v1/full/{date}/title-48.xml", {"section": section},
                )
            except RuntimeError:
                xml = None  # not in force on this date; leave it as a pointer
            if xml is not None:
                block = _definitions.defining_block(_parse_xml_to_text(xml, date).get("paragraphs", []), query)
                if block:
                    entry["definition"] = block
                else:
                    entry["note"] = "uses the phrase, but no defining paragraph was found"
        else:
            entry["note"] = "not read; only the first three matches are checked"
        out.append(entry)
        if len(out) >= 8:
            break
    # Confirmed definitions first.
    out.sort(key=lambda e: "definition" not in e)
    return out


@mcp.tool(annotations={"title": "Find Recent Changes", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def find_recent_changes(
    since_date: str,
    title: int = 48,
    chapter: str | int | None = None,
    part: str | int | None = None,
    per_page: int = 100,
    page: int = 1,
) -> dict[str, Any]:
    """Find CFR sections changed since a given date, removals included.

    Built on eCFR's version history: every version issued on or after
    since_date, newest first. Each change says whether the section was
    amended, removed (change='removed'), or re-issued with no text change
    (substantive=false). 'summary' counts each kind. A section changed
    twice appears twice.

    since_date must be in YYYY-MM-DD format. Filter with title (default 48),
    chapter (Title 48: 1 = FAR, 2 = DFARS, 99 = CAS) or part. per_page
    (default 100, max 5000) and page step through long lists; total_pages
    says how many pages there are.

    Common pattern: find FAR changes since a specific date to check for
    regulatory updates that might affect ongoing acquisitions.
    """
    since_date = _validate_date_ymd(since_date, field="since_date")
    if since_date is None:
        raise ValueError("since_date is required (YYYY-MM-DD).")
    title = _validate_title_number(title, field="title")
    _check_cited_title(part, title, "part")
    chapter = _validate_chapter(chapter, title_number=title)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    per_page = _clamp(per_page, field="per_page", lo=1, hi=SEARCH_MAX_PER_PAGE)
    page = _clamp(page, field="page", lo=1, hi=10_000)

    params: dict[str, str] = {"issue_date[gte]": since_date}
    if part:
        params["part"] = part
    versions, _, complete = await _all_versions(title, params)

    if chapter:
        # eCFR's version history ignores a chapter filter, so apply it here.
        if title == 48:
            versions = [v for v in versions if _title48_chapter(v.get("part")) == chapter]
        else:
            date = await _resolve_date(title)
            tree = await _get_json(
                f"/api/versioner/v1/structure/{date}/title-{title}.json",
                {"chapter": chapter}, timeout=DEFAULT_TIMEOUT_STRUCTURE,
            )
            owned = {n["identifier"] for n in _walk_structure(tree, "part")}
            versions = [v for v in versions if str(v.get("part")) in owned]

    changes = []
    for v in versions:
        if v.get("removed"):
            change = "removed"
        elif v.get("substantive"):
            change = "amended"
        else:
            change = "re-issued, no text change"
        changes.append({
            "identifier": v.get("identifier"),
            "name": _clean_heading(v.get("name")),
            "type": v.get("type"),
            "part": v.get("part"),
            "subpart": v.get("subpart"),
            "change": change,
            "amendment_date": v.get("amendment_date") or v.get("date"),
            "issue_date": v.get("issue_date"),
            "substantive": v.get("substantive"),
            "removed": bool(v.get("removed")),
        })
    changes.sort(key=lambda c: (c["issue_date"] or "", c["amendment_date"] or ""), reverse=True)

    total = len(changes)
    total_pages = max(1, -(-total // per_page))
    if page > total_pages:
        raise ValueError(f"page={page} does not exist; there are {total_pages} page(s) of {per_page}.")
    shown = changes[(page - 1) * per_page: page * per_page]
    summary = {kind: sum(c["change"] == kind for c in changes)
               for kind in ("amended", "removed", "re-issued, no text change")}
    result: dict[str, Any] = {
        "title": title,
        "since_date": since_date,
        "total_count": total,
        "summary": summary,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "changes": shown,
    }
    if chapter:
        result["chapter"] = chapter
    if part:
        result["part"] = part
    if not complete:
        result["truncated"] = True
        result["note"] = (
            f"eCFR lists more than {_MAX_VERSION_PAGES * _VERSION_PAGE:,} versions for this "
            f"filter; only the first {_MAX_VERSION_PAGES * _VERSION_PAGE:,} were read. Use a "
            f"later since_date or a part filter."
        )
    elif page < total_pages:
        result["note"] = f"Showing page {page} of {total_pages}; call again with page={page + 1} for more."
    return result


def _clean_heading(name: Any) -> Any:
    """eCFR pads version names: '9904.409-62   Exemption.'."""
    return " ".join(name.split()) if isinstance(name, str) else name


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_cfr(keyword='audit') (the real
    parameter is `query`) would succeed with the typo silently discarded,
    leaving the tool to hit the API with no query at all.
    extra='forbid' raises "Extra inputs are not permitted" on typos
    before any HTTP call.
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
