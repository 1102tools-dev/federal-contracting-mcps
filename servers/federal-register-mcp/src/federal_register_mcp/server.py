# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Federal Register MCP server.

Free, no-auth access to all Federal Register content since 1994: proposed
rules, final rules, notices, presidential documents, and corrections.

Complements eCFR (what the regulation currently says) by showing what is
changing, what has changed, and what comment periods are open.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date
from typing import Any, Literal

import httpx
from mcp.server import MCPServer

from .constants import (
    BASE_URL,
    DEFAULT_FIELDS,
    DEFAULT_TIMEOUT,
    FACET_NAMES,
    USER_AGENT,
)

mcp = MCPServer("federal-register")


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EARLIEST_FR_DATE = "1994-01-01"


def _validate_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not _DATE_RE.match(value):
        raise ValueError(
            f"{field_name} must be in YYYY-MM-DD format (e.g. '2026-01-15'). "
            f"Got {value!r}. ISO 8601 datetimes and 'YYYY/MM/DD' are rejected."
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}={value!r} is not a valid calendar date: {exc}") from exc
    return value


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(
            f"{field} exceeds maximum of {hi}. Got {value}. Paginate with 'page' instead."
        )
    return value


def _reject_empty_list(value: list[Any] | None, field: str) -> list[Any] | None:
    if value is None:
        return None
    if len(value) == 0:
        raise ValueError(
            f"{field}=[] is silently ignored by the API (matches everything). "
            f"Omit {field} entirely to search without it."
        )
    return value


def _check_date_range(gte: str | None, lte: str | None, field_pair: str) -> None:
    if gte and lte and gte > lte:
        raise ValueError(
            f"{field_pair}: gte ({gte}) is after lte ({lte}). "
            f"Check parameter order (gte = start / lte = end)."
        )


def _strip_or_none(value: str | None) -> str | None:
    """Normalize whitespace-only strings to None. Trim leading/trailing space."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _require_min_length(value: str, *, field: str, minimum: int) -> str:
    stripped = value.strip()
    if len(stripped) < minimum:
        raise ValueError(
            f"{field} must be at least {minimum} characters after trimming whitespace. "
            f"Got {value!r} ({len(stripped)} chars). Short queries match too broadly "
            f"and return unrelated results."
        )
    return stripped


def _clamp_str_len(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if len(value) > maximum:
        raise ValueError(
            f"{field} exceeds maximum length of {maximum} chars. "
            f"Got {len(value)}. Very long query strings cause HTTP 414 errors."
        )
    return value


# Document numbers span several era-specific families, all verified against
# the live archive (round 6):
#   2026-07731     modern (2011+): 4-digit year, 5-digit sequence
#   94-16174       1994 through 2000s: 2-digit year, variable-length sequence
#   E9-12940       2005-2011 electronic-submission era (E prefix)
#   X94-70302      legacy special series (X and Z prefixes)
#   C1-2026-01234  corrections (C prefix wrapping any of the above)
# The pattern is a loose URL-safe shape check (optional correction prefix,
# up to two letters, 1-4 digit year part, 1-6 digit sequence). Genuinely
# unknown numbers are left for the API's own 404 to decide.
_DOC_NUMBER_RE = re.compile(r"^(?:C\d{1,2}-)?[A-Za-z]{0,2}\d{1,4}-\d{1,6}$")


def _validate_doc_number(value: str, *, field: str = "document_number") -> str:
    # Round 5 fix: handle None and non-string inputs cleanly
    # instead of crashing with AttributeError.
    if value is None:
        raise ValueError(f"{field} cannot be empty.")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string. Got {type(value).__name__}.")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} cannot be empty.")
    if not _DOC_NUMBER_RE.match(stripped):
        raise ValueError(
            f"{field}={value!r} has invalid format. Accepted shapes: modern "
            f"'YYYY-NNNNN' (e.g. '2026-07731'), legacy pre-2011 forms such as "
            f"'E9-12940', 'X94-70302', or '94-16174', and correction numbers "
            f"like 'C1-2026-01234'."
        )
    return stripped


def _warn_pre_fr_date(value: str | None, field: str) -> str | None:
    """Dates before 1994 return nothing useful; reject with actionable message."""
    if value is None:
        return None
    if value < _EARLIEST_FR_DATE:
        raise ValueError(
            f"{field}={value!r} predates the Federal Register API (earliest date: "
            f"{_EARLIEST_FR_DATE}). The API will return empty results for pre-1994 dates."
        )
    return value


_CFR_PART_RE = re.compile(r"^\d{1,4}(-\d{1,4})?$")


def _validate_cfr(
    cfr_title: int | None, cfr_part: str | int | None
) -> tuple[str | None, str | None]:
    """Validate the CFR title/part filter pair.

    The API requires the title whenever a part is given (a part filter
    without its title is silently ignored upstream). Part accepts a single
    part ('52') or a range ('1-50'). Returns wire-ready strings.
    """
    if cfr_title is None and cfr_part is None:
        return None, None
    if cfr_part is not None and cfr_title is None:
        raise ValueError(
            "cfr_part requires cfr_title (the API silently ignores a part "
            "filter without its CFR title). Pass both, e.g. cfr_title=48, "
            "cfr_part='52'."
        )
    title_str: str | None = None
    if cfr_title is not None:
        if not 1 <= cfr_title <= 50:
            raise ValueError(f"cfr_title must be between 1 and 50. Got {cfr_title}.")
        title_str = str(cfr_title)
    part_str: str | None = None
    if cfr_part is not None:
        part_str = str(cfr_part).strip()
        if not _CFR_PART_RE.match(part_str):
            raise ValueError(
                f"cfr_part={cfr_part!r} must be a part number ('52') or a "
                f"part range ('1-50'). Section syntax like '52.212-4' is not "
                f"accepted; pass the part ('52')."
            )
    return title_str, part_str


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML from upstream error bodies so error messages stay readable.

    Round 5 fix: coerce non-string inputs to string instead
    of crashing with TypeError when the API returns a None/dict/list body.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not _HTML_ERROR_RE.search(text):
        return text[:400]
    pieces: list[str] = []
    title = _TITLE_RE.search(text)
    if title:
        pieces.append(title.group(1).strip())
    h1 = _H1_RE.search(text)
    if h1 and (not title or h1.group(1).strip() != title.group(1).strip()):
        pieces.append(h1.group(1).strip())
    return " - ".join(pieces) if pieces else "upstream returned HTML error page"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


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
    if status == 404:
        return (
            f"HTTP 404: Resource not found. For get_document/get_documents_batch, "
            f"verify the document_number. For other endpoints the path may be invalid. "
            f"API response: {cleaned}"
        )
    if status == 414:
        return (
            f"HTTP 414: Request URI too long. "
            f"Shorten long query strings (term, docket_id, regulation_id_number)."
        )
    if status == 422:
        return (
            f"HTTP 422: Invalid parameters. Check agency slugs, document type codes "
            f"(PRORULE, RULE, NOTICE, PRESDOCU), date formats (YYYY-MM-DD), "
            f"and field names. API response: {cleaned}"
        )
    if status == 429:
        return "HTTP 429: Rate limited. Add delays between requests."
    return f"HTTP {status}: {cleaned}"


def _ensure_json_container(data: Any, *, url: str) -> dict[str, Any] | list[Any]:
    """Guarantee a JSON container (dict OR list) return from the Federal
    Register API. Document/facet/pi endpoints return dicts; /agencies.json
    returns a list. Anything else (None, int, string) indicates a
    CDN/proxy issue rather than a real empty result, and used to leak
    into tool output as a type confusion. Surface it clearly.
    """
    if isinstance(data, (dict, list)):
        return data
    if data is None:
        raise RuntimeError(
            f"Federal Register returned an empty body at {url!r}. This "
            f"usually indicates a transient CDN / proxy issue; retry "
            f"in a few seconds."
        )
    raise RuntimeError(
        f"Federal Register returned an unexpected {type(data).__name__} "
        f"at {url!r} (expected JSON object or list). First 200 chars: "
        f"{str(data)[:200]!r}"
    )


async def _get(url: str) -> Any:
    try:
        r = await _get_client().get(url)
        r.raise_for_status()
        return _ensure_json_container(r.json(), url=url)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling Federal Register: {e}") from e


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")


def _validate_no_control_chars(value: Any, *, field: str) -> Any:
    """Reject control characters (null byte, newline, tab, CR) in free-text
    values. The Federal Register API silently accepts them, leaving users
    with confusing 'no filter applied' results."""
    if value is None:
        return None
    if isinstance(value, str) and _CONTROL_CHARS_RE.search(value):
        raise ValueError(
            f"{field}={value!r} contains control characters "
            f"(null byte / newline / tab / CR). Remove them and retry."
        )
    return value


def _reject_empty_strings_in_list(
    value: list[str] | None, *, field: str
) -> list[str] | None:
    """Reject an all-empty-strings list. Federal Register silently
    treats `[""]` as 'no filter', the same way `[]` would be. Our
    `_reject_empty_list` only catches the empty-list case."""
    if value is None:
        return None
    cleaned = [v for v in value if v is not None and str(v).strip()]
    if not cleaned:
        raise ValueError(
            f"{field}={value!r} contains only empty / whitespace strings. "
            f"Pass real values or omit the parameter."
        )
    # Also reject control chars per-entry
    for i, v in enumerate(cleaned):
        _validate_no_control_chars(v, field=f"{field}[{i}]")
    return cleaned


def _build_search_params(
    *,
    agencies: list[str] | None = None,
    doc_types: list[str] | None = None,
    term: str | None = None,
    docket_id: str | None = None,
    regulation_id_number: str | None = None,
    pub_date_gte: str | None = None,
    pub_date_lte: str | None = None,
    comment_date_gte: str | None = None,
    comment_date_lte: str | None = None,
    effective_date_gte: str | None = None,
    effective_date_lte: str | None = None,
    correction: bool | None = None,
    significant: bool | None = None,
    cfr_title: str | None = None,
    cfr_part: str | None = None,
    fields: list[str] | None = None,
    per_page: int = 20,
    page: int = 1,
    order: str = "newest",
) -> str:
    params: list[tuple[str, str]] = []

    if agencies:
        for a in agencies:
            params.append(("conditions[agencies][]", a))
    if doc_types:
        for t in doc_types:
            params.append(("conditions[type][]", t))
    if term:
        params.append(("conditions[term]", term))
    if docket_id:
        params.append(("conditions[docket_id]", docket_id))
    if regulation_id_number:
        params.append(("conditions[regulation_id_number]", regulation_id_number))
    if pub_date_gte:
        params.append(("conditions[publication_date][gte]", pub_date_gte))
    if pub_date_lte:
        params.append(("conditions[publication_date][lte]", pub_date_lte))
    if comment_date_gte:
        params.append(("conditions[comment_date][gte]", comment_date_gte))
    if comment_date_lte:
        params.append(("conditions[comment_date][lte]", comment_date_lte))
    if effective_date_gte:
        params.append(("conditions[effective_date][gte]", effective_date_gte))
    if effective_date_lte:
        params.append(("conditions[effective_date][lte]", effective_date_lte))
    if correction is not None:
        params.append(("conditions[correction]", "1" if correction else "0"))
    if significant is not None:
        params.append(("conditions[significant]", "1" if significant else "0"))
    if cfr_title:
        params.append(("conditions[cfr][title]", cfr_title))
    if cfr_part:
        params.append(("conditions[cfr][part]", cfr_part))

    for f in (fields or DEFAULT_FIELDS):
        params.append(("fields[]", f))

    params.append(("per_page", str(per_page)))
    params.append(("page", str(page)))
    params.append(("order", order))

    return urllib.parse.urlencode(params)


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Documents", "readOnlyHint": True, "destructiveHint": False})
async def search_documents(
    agencies: list[str] | None = None,
    doc_types: list[Literal["PRORULE", "RULE", "NOTICE", "PRESDOCU"]] | None = None,
    term: str | None = None,
    docket_id: str | None = None,
    regulation_id_number: str | None = None,
    pub_date_gte: str | None = None,
    pub_date_lte: str | None = None,
    comment_date_gte: str | None = None,
    comment_date_lte: str | None = None,
    effective_date_gte: str | None = None,
    effective_date_lte: str | None = None,
    correction: bool | None = None,
    significant: bool | None = None,
    cfr_title: int | None = None,
    cfr_part: str | int | None = None,
    per_page: int = 20,
    page: int = 1,
    order: Literal["newest", "oldest", "relevance", "executive_order_number"] = "newest",
) -> dict[str, Any]:
    """Search Federal Register documents.

    The primary tool for finding proposed rules, final rules, notices,
    and presidential documents published in the Federal Register since 1994.

    Key parameters:
    - agencies: list of agency URL slugs (OR logic). Use list_agencies() to find slugs.
      Common: 'defense-department', 'general-services-administration',
      'federal-procurement-policy-office', 'small-business-administration'
    - doc_types: PRORULE (proposed rule), RULE (final rule), NOTICE, PRESDOCU
    - term: full-text keyword search (strips stop words)
    - docket_id: docket identifier (token match). 'FAR Case 2023-008' = exact,
      'FAR Case 2023' = all 2023 cases; partial tokens like 'FAR Case 20'
      match nothing
    - regulation_id_number: RIN (precise match, e.g., '9000-AO56')
    - pub_date_gte/lte: publication date range (YYYY-MM-DD)
    - comment_date_gte/lte: comment close date range
    - effective_date_gte/lte: effective date range
    - correction: True for modern corrections (C1- prefix documents)
    - significant: True for EO 12866 significant rules only
    - cfr_title + cfr_part: documents affecting a CFR location, e.g.
      cfr_title=48, cfr_part='52' for FAR part 52 (part accepts ranges
      like '1-99'; cfr_part requires cfr_title)

    Count caps at 10,000 for broad queries. Use date ranges for accurate counts.
    per_page capped at 100 to stay within MCP response size limits.
    """
    agencies = _reject_empty_list(agencies, "agencies")
    agencies = _reject_empty_strings_in_list(agencies, field="agencies")
    doc_types = _reject_empty_list(doc_types, "doc_types")
    per_page = _clamp(per_page, field="per_page", lo=1, hi=100)
    page = _clamp(page, field="page", lo=1, hi=10_000)
    _validate_no_control_chars(term, field="term")
    _validate_no_control_chars(docket_id, field="docket_id")
    _validate_no_control_chars(regulation_id_number, field="regulation_id_number")
    term = _clamp_str_len(_strip_or_none(term), field="term", maximum=500)
    docket_id = _clamp_str_len(_strip_or_none(docket_id), field="docket_id", maximum=200)
    regulation_id_number = _clamp_str_len(
        _strip_or_none(regulation_id_number), field="regulation_id_number", maximum=50
    )
    pub_date_gte = _warn_pre_fr_date(_validate_date(pub_date_gte, "pub_date_gte"), "pub_date_gte")
    pub_date_lte = _warn_pre_fr_date(_validate_date(pub_date_lte, "pub_date_lte"), "pub_date_lte")
    comment_date_gte = _validate_date(comment_date_gte, "comment_date_gte")
    comment_date_lte = _validate_date(comment_date_lte, "comment_date_lte")
    effective_date_gte = _validate_date(effective_date_gte, "effective_date_gte")
    effective_date_lte = _validate_date(effective_date_lte, "effective_date_lte")
    _check_date_range(pub_date_gte, pub_date_lte, "publication_date")
    _check_date_range(comment_date_gte, comment_date_lte, "comment_date")
    _check_date_range(effective_date_gte, effective_date_lte, "effective_date")
    cfr_title_str, cfr_part_str = _validate_cfr(cfr_title, cfr_part)

    # Require at least one real filter. An unfiltered search_documents() call
    # silently returned the Federal Register's 10,000-doc "most recent"
    # default as if those were search hits, which is very confusing UX.
    if not any([
        agencies, doc_types, term, docket_id, regulation_id_number,
        pub_date_gte, pub_date_lte,
        comment_date_gte, comment_date_lte,
        effective_date_gte, effective_date_lte,
        correction is not None, significant is not None,
        cfr_title_str,
    ]):
        raise ValueError(
            "search_documents requires at least one filter. Typical: "
            "term=<keywords>, agencies=[<slug>], doc_types=['RULE'], or a "
            "publication_date range. Calling without filters silently "
            "returns the Federal Register's 10,000-doc unfiltered default."
        )

    qs = _build_search_params(
        agencies=agencies, doc_types=doc_types, term=term,
        docket_id=docket_id, regulation_id_number=regulation_id_number,
        pub_date_gte=pub_date_gte, pub_date_lte=pub_date_lte,
        comment_date_gte=comment_date_gte, comment_date_lte=comment_date_lte,
        effective_date_gte=effective_date_gte, effective_date_lte=effective_date_lte,
        correction=correction, significant=significant,
        cfr_title=cfr_title_str, cfr_part=cfr_part_str,
        per_page=per_page, page=page, order=order,
    )
    return await _get(f"{BASE_URL}/documents.json?{qs}")


@mcp.tool(annotations={"title": "Get Document", "readOnlyHint": True, "destructiveHint": False})
async def get_document(
    document_number: str,
) -> dict[str, Any]:
    """Get full details for a single Federal Register document by number.

    Returns all available fields including full text URLs, docket info,
    RIN details, page views, topics, corrections, and CFR references.

    Document numbers look like '2026-03065' (modern), 'E9-12940' or
    'X94-70302' (legacy pre-2011 archive), or 'C1-2026-01234' (corrections).
    """
    dn = _validate_doc_number(document_number)
    return await _get(f"{BASE_URL}/documents/{dn}.json")


@mcp.tool(annotations={"title": "Get Documents Batch", "readOnlyHint": True, "destructiveHint": False})
async def get_documents_batch(
    document_numbers: list[str],
) -> dict[str, Any]:
    """Fetch multiple documents in one call (up to ~20).

    Pass a list of document numbers. More efficient than individual calls.
    Always returns {count, results, [errors]}; errors.not_found lists any
    requested numbers the API could not locate.
    """
    if not document_numbers:
        raise ValueError("document_numbers list cannot be empty.")
    if len(document_numbers) > 20:
        raise ValueError(f"Max 20 documents per batch. Got {len(document_numbers)}.")

    validated = [_validate_doc_number(d, field=f"document_numbers[{i}]")
                 for i, d in enumerate(document_numbers)]
    nums = ",".join(validated)
    data = await _get(f"{BASE_URL}/documents/{nums}.json")
    # Round 6 fix: a 1-document request (or a multi-request deduped to one
    # by the API) can come back as the bare document object with no
    # count/results wrapper. Normalize so callers can always iterate
    # data["results"].
    if isinstance(data, dict) and "results" not in data:
        return {"count": 1, "results": [data]}
    return data


@mcp.tool(annotations={"title": "Get Facet Counts", "readOnlyHint": True, "destructiveHint": False})
async def get_facet_counts(
    facet: Literal[
        "type", "agency", "topic",
        "daily", "weekly", "monthly", "quarterly", "yearly",
    ],
    agencies: list[str] | None = None,
    doc_types: list[Literal["PRORULE", "RULE", "NOTICE", "PRESDOCU"]] | None = None,
    term: str | None = None,
    pub_date_gte: str | None = None,
    pub_date_lte: str | None = None,
    cfr_title: int | None = None,
    cfr_part: str | int | None = None,
) -> dict[str, Any]:
    """Get document counts grouped by type, agency, topic, or time period.

    Accepts the same filter conditions as search_documents. Returns
    aggregated counts without individual document results.

    Facets: type, agency, topic (categorical) plus daily, weekly, monthly,
    quarterly, yearly (publication-date buckets, useful for trend lines).

    Useful for understanding the volume of rulemaking by agency, type, or
    over time within a date range before drilling into specific documents.

    At least one filter (agencies, doc_types, term, pub_date_gte/lte, or
    cfr_title) is required. An unfiltered facet query returns the entire
    all-time aggregate.
    """
    agencies = _reject_empty_list(agencies, "agencies")
    agencies = _reject_empty_strings_in_list(agencies, field="agencies")
    doc_types = _reject_empty_list(doc_types, "doc_types")
    _validate_no_control_chars(term, field="term")
    term = _clamp_str_len(_strip_or_none(term), field="term", maximum=500)
    pub_date_gte = _warn_pre_fr_date(
        _validate_date(pub_date_gte, "pub_date_gte"), "pub_date_gte"
    )
    pub_date_lte = _warn_pre_fr_date(
        _validate_date(pub_date_lte, "pub_date_lte"), "pub_date_lte"
    )
    _check_date_range(pub_date_gte, pub_date_lte, "publication_date")
    cfr_title_str, cfr_part_str = _validate_cfr(cfr_title, cfr_part)

    if not any([agencies, doc_types, term, pub_date_gte, pub_date_lte, cfr_title_str]):
        raise ValueError(
            "get_facet_counts requires at least one filter "
            "(agencies, doc_types, term, pub_date_gte/lte, or cfr_title). "
            "An unfiltered query returns all-time aggregates and is rarely useful."
        )

    params: list[tuple[str, str]] = []
    if agencies:
        for a in agencies:
            params.append(("conditions[agencies][]", a))
    if doc_types:
        for t in doc_types:
            params.append(("conditions[type][]", t))
    if term:
        params.append(("conditions[term]", term))
    if pub_date_gte:
        params.append(("conditions[publication_date][gte]", pub_date_gte))
    if pub_date_lte:
        params.append(("conditions[publication_date][lte]", pub_date_lte))
    if cfr_title_str:
        params.append(("conditions[cfr][title]", cfr_title_str))
    if cfr_part_str:
        params.append(("conditions[cfr][part]", cfr_part_str))

    qs = urllib.parse.urlencode(params) if params else ""
    url = f"{BASE_URL}/documents/facets/{facet}"
    if qs:
        url += f"?{qs}"
    return await _get(url)


@mcp.tool(annotations={"title": "Get Public Inspection", "readOnlyHint": True, "destructiveHint": False})
async def get_public_inspection(
    agency_filter: str | None = None,
    keyword_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Get current public inspection documents (pre-publication).

    Public inspection documents are FR documents filed for publication but
    not yet published. Updated business days only.

    The current-PI endpoint does NOT support server-side filtering. This
    tool fetches all current PI documents and filters client-side by
    agency and/or keyword in the title.

    Useful for getting early notice of upcoming regulatory actions.

    Parameters:
    - agency_filter: case-insensitive substring match against each
      document's agency slugs, names, and raw names. CAUTION: PI documents
      list only the FILING sub-agency, so a parent slug like
      'defense-department' will not match a Defense Logistics Agency
      filing. Prefer a short distinctive fragment ('defense', 'acquisition
      regulations') over a full parent slug.
    - keyword_filter: substring match against document titles
    - limit: max documents returned after filtering (default 50, max 500).
      Unfiltered dumps can exceed 170KB; narrow with filters or raise the cap.
    """
    limit = _clamp(limit, field="limit", lo=1, hi=500)
    _validate_no_control_chars(agency_filter, field="agency_filter")
    _validate_no_control_chars(keyword_filter, field="keyword_filter")
    agency_filter = _strip_or_none(agency_filter)
    keyword_filter = _strip_or_none(keyword_filter)

    data = await _get(f"{BASE_URL}/public-inspection-documents/current.json")

    results = data.get("results", [])

    if agency_filter:
        # Round 6 fix: PI documents carry only the filing sub-agency, and
        # slug-only matching made parent-agency filters silently return
        # nothing. Match against slug, name, and raw_name, and also try
        # the filter with hyphens as spaces so slug-style input can hit
        # the human-readable names.
        agency_lower = agency_filter.lower()
        agency_spaced = agency_lower.replace("-", " ")

        def _agency_match(doc: dict[str, Any]) -> bool:
            for a in doc.get("agencies", []):
                blob = " ".join(
                    str(a.get(k) or "") for k in ("slug", "name", "raw_name")
                ).lower()
                if agency_lower in blob or agency_spaced in blob:
                    return True
            return False

        results = [d for d in results if _agency_match(d)]

    if keyword_filter:
        kw_lower = keyword_filter.lower()
        results = [
            d for d in results
            if kw_lower in (d.get("title") or "").lower()
        ]

    total_matched = len(results)
    truncated = total_matched > limit
    results = results[:limit]

    return {
        "total_pi_documents": data.get("count", 0),
        "filtered_count": total_matched,
        "returned": len(results),
        "truncated": truncated,
        "filters_applied": {
            "agency": agency_filter,
            "keyword": keyword_filter,
            "limit": limit,
        },
        "documents": results,
    }


@mcp.tool(annotations={"title": "List Agencies", "readOnlyHint": True, "destructiveHint": False})
async def list_agencies(
    query: str | None = None,
    include_detail: bool = False,
) -> dict[str, Any]:
    """List agencies with their IDs, names, slugs, and parent agencies.

    Use the 'slug' values with search_documents() and other tools.
    Common procurement slugs:
    - federal-procurement-policy-office (OFPP)
    - defense-department (DoD)
    - general-services-administration (GSA)
    - defense-acquisition-regulations-system (DARS/DFARS)
    - small-business-administration (SBA)
    - national-aeronautics-and-space-administration (NASA)
    - veterans-affairs-department (VA)

    Parameters:
    - query: optional case-insensitive substring match against name, short_name,
      and slug. Recommended: narrow results before pulling full detail.
    - include_detail: if False (default), returns only id/name/short_name/slug/parent_id.
      If True, returns all fields (description, urls, etc.). The full dump is ~700KB.
    """
    query = _strip_or_none(query)
    data = await _get(f"{BASE_URL}/agencies.json")

    if not isinstance(data, list):
        raise RuntimeError(
            f"Unexpected response shape from /agencies.json: {type(data).__name__}"
        )

    results = data
    if query:
        q = query.lower()
        results = [
            a for a in results
            if q in (a.get("name") or "").lower()
            or q in (a.get("short_name") or "").lower()
            or q in (a.get("slug") or "").lower()
        ]

    if not include_detail:
        slim_fields = ("id", "name", "short_name", "slug", "parent_id")
        results = [{k: a.get(k) for k in slim_fields} for a in results]

    return {
        "total_agencies": len(data),
        "returned": len(results),
        "query": query,
        "include_detail": include_detail,
        "agencies": results,
    }


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

_OPEN_COMMENT_SCAN_CAP = 500
_OPEN_COMMENT_PAGE_SIZE = 100


@mcp.tool(annotations={"title": "Open Comment Periods", "readOnlyHint": True, "destructiveHint": False})
async def open_comment_periods(
    agencies: list[str] | None = None,
    term: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find documents with currently open comment periods, soonest deadline first.

    Covers proposed rules, notices, AND final/interim rules that accept
    comments (dozens of RULE-type documents have open periods at any time).
    Queries for comment close date >= today, scans up to 500 matching
    documents oldest-published first (where the soonest deadlines live),
    sorts by close date, and returns the first `limit`.

    Honest bound: total_open is the API's true government-wide count;
    scanned is how many this call examined. When total_open exceeds
    scanned, narrow with agencies/term for exhaustive coverage. A very
    recently published document with an unusually short comment window
    can fall outside the scan in that oversubscribed case.

    Default: searches all agencies. Pass agency slugs to narrow scope.
    Common for procurement: ['federal-procurement-policy-office',
    'defense-department', 'general-services-administration']

    Parameters:
    - limit: max documents returned after sorting (default 50, max 100).
      Unfiltered dumps across all agencies can approach 200KB.
    """
    agencies = _reject_empty_list(agencies, "agencies")
    limit = _clamp(limit, field="limit", lo=1, hi=100)

    today = date.today().isoformat()

    results: list[dict[str, Any]] = []
    total_open = 0
    max_pages = _OPEN_COMMENT_SCAN_CAP // _OPEN_COMMENT_PAGE_SIZE
    for page_num in range(1, max_pages + 1):
        data = await search_documents(
            agencies=agencies,
            doc_types=["PRORULE", "RULE", "NOTICE"],
            term=term,
            comment_date_gte=today,
            per_page=_OPEN_COMMENT_PAGE_SIZE,
            page=page_num,
            order="oldest",
        )
        total_open = data.get("count", 0)
        page_results = data.get("results", [])
        results.extend(page_results)
        if len(page_results) < _OPEN_COMMENT_PAGE_SIZE or len(results) >= total_open:
            break

    results.sort(key=lambda x: x.get("comments_close_on") or "9999-99-99")
    returned = results[:limit]

    return {
        "as_of": today,
        "total_open": total_open,
        "scanned": len(results),
        "scan_cap": _OPEN_COMMENT_SCAN_CAP,
        "returned": len(returned),
        "limit": limit,
        "documents": returned,
    }


@mcp.tool(annotations={"title": "FAR Case History", "readOnlyHint": True, "destructiveHint": False})
async def far_case_history(docket_id: str) -> dict[str, Any]:
    """Get all Federal Register documents for a FAR/DFARS case or FAC.

    Pass a docket ID like 'FAR Case 2023-008' (or a FAC number like
    'FAC 2025-06'). Runs BOTH a docket-id search and a quoted full-text
    search, then merges the two result sets (deduped by document number)
    in chronological order to show the full rulemaking progression:
    ANPRM -> proposed rule -> final rule -> corrections. The dual query
    matters: FAC introduction and companion documents often carry only
    internal docket numbers, so a docket-only search returns a partial set.

    Docket matching is token-based, not substring: 'FAR Case 2023' matches
    all 2023 cases (token '2023' matches '2023-008'), but a partial token
    like 'FAR Case 20' matches nothing. Be specific to avoid false positives.

    Each underlying search returns at most 100 documents. truncated=True
    flags that one of the searches hit that cap (docket_matches and
    term_matches carry the API's full counts); narrow the docket_id if so.

    Minimum docket_id length is 3 characters to prevent token matches that
    return unrelated documents (e.g. 'x' matched 65 random dockets in 0.1.x).
    """
    docket_id = _require_min_length(docket_id, field="docket_id", minimum=3)
    docket_id = _clamp_str_len(docket_id, field="docket_id", maximum=200)

    docket_data = await search_documents(
        docket_id=docket_id,
        per_page=100,
        order="oldest",
    )
    term_data = await search_documents(
        term=f'"{docket_id}"',
        per_page=100,
        order="oldest",
    )

    docket_results = docket_data.get("results", []) or []
    term_results = term_data.get("results", []) or []

    merged: dict[str, dict[str, Any]] = {}
    for i, doc in enumerate(docket_results + term_results):
        key = doc.get("document_number") or f"_missing_number_{i}"
        if key not in merged:
            merged[key] = doc
    documents = sorted(
        merged.values(), key=lambda d: d.get("publication_date") or "9999-99-99"
    )

    docket_count = docket_data.get("count", 0)
    term_count = term_data.get("count", 0)
    truncated = (
        docket_count > len(docket_results) or term_count > len(term_results)
    )

    return {
        "docket_id": docket_id,
        "total_documents": len(documents),
        "docket_matches": docket_count,
        "term_matches": term_count,
        "truncated": truncated,
        "documents": documents,
    }


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    MCPServer's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_documents(keyword='acquisition')
    (real param is `term`) would succeed with the typo silently discarded,
    leaving the tool to hit the API with no filter. extra='forbid' raises
    "Extra inputs are not permitted" on typos before any HTTP call.
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
