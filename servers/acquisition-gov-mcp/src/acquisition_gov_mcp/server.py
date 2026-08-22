# SPDX-License-Identifier: MIT
"""Read-only MCP server for official FAR Overhaul resources on Acquisition.gov."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag
from mcp.server import MCPServer
from pypdf import PdfReader

from . import __version__
from ._pacing import FederalApiPacer
from .constants import (
    ALLOWED_HOSTS,
    BASE_URL,
    DEFAULT_MAX_CHARACTERS,
    DEFAULT_TIMEOUT,
    GUIDANCE_URLS,
    MAX_HTML_BYTES,
    MAX_OUTPUT_CHARACTERS,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    MAX_REDIRECTS,
    RFO_INDEX_URL,
    USER_AGENT,
)

mcp = MCPServer("acquisition-gov", version=__version__)
_client: httpx.AsyncClient | None = None
_prefer_system_curl = False
_pacer = FederalApiPacer(bucket="www.acquisition.gov", default_interval=3.0)
_PART_RE = re.compile(r"(?:FAR\s*)?Part\s*[-:]?\s*(\d{1,2})", re.I)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REDIRECTS = {301, 302, 303, 307, 308}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_id(kind: str, url: str) -> str:
    return f"{kind}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]}"


def _validate_part(part: int | str) -> int:
    try:
        value = int(str(part).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"part must be an integer from 1 through 53. Got {part!r}.") from exc
    if not 1 <= value <= 53:
        raise ValueError(f"part must be from 1 through 53. Got {value}.")
    return value


def _validate_date(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not _ISO_DATE_RE.fullmatch(value.strip()):
        raise ValueError(f"{field} must use YYYY-MM-DD format. Got {value!r}.")
    try:
        date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid calendar date: {value!r}.") from exc
    return value.strip()


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    text = " ".join(raw.replace("\xa0", " ").split()).strip(" .")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _labeled_date(text: str, label: str) -> str | None:
    pattern = re.compile(
        rf"\b{re.escape(label)}(?:\s+date)?\s*[:\-]\s*"
        r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        re.I,
    )
    match = pattern.search(text)
    return _normalize_date(match.group(1)) if match else None


def _validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("Only HTTPS Acquisition.gov URLs are permitted.")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("Credentials and explicit ports are not permitted in source URLs.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Host {host!r} is not on the Acquisition.gov allowlist.")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"},
        )
    return _client


async def _fetch_bytes(
    url: str,
    *,
    allowed_types: tuple[str, ...],
    max_bytes: int,
) -> tuple[bytes, str, str]:
    global _prefer_system_curl
    current = _validated_url(url)
    for redirect_count in range(MAX_REDIRECTS + 1):
        try:
            async with _pacer.request_slot() as pacing:
                if _prefer_system_curl and shutil.which("curl"):
                    response, response_body = await _curl_once(current, max_bytes=max_bytes)
                else:
                    try:
                        async with _get_client().stream("GET", current) as streamed:
                            response_body = await _bounded_httpx_body(
                                streamed, max_bytes=max_bytes
                            )
                            response = streamed
                    except httpx.RequestError:
                        if not shutil.which("curl"):
                            raise
                        # Acquisition.gov's CDN has intermittently stalled Python/OpenSSL
                        # clients while serving the same allowlisted URL to system curl.
                        # Cache the fallback choice for the process after the first failure.
                        _prefer_system_curl = True
                        response, response_body = await _curl_once(
                            current, max_bytes=max_bytes
                        )
                    pacing.observe_response(response)
                    pacing.raise_if_rate_limited(response, service="Acquisition.gov")
                    if response.status_code in _REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            raise RuntimeError("Acquisition.gov returned a redirect without Location.")
                        if redirect_count >= MAX_REDIRECTS:
                            raise RuntimeError("Acquisition.gov exceeded the redirect limit.")
                        current = _validated_url(urljoin(current, location))
                        continue
                    if response.status_code >= 400:
                        body = response_body[:500].decode("utf-8", "replace")
                        raise RuntimeError(
                            f"Acquisition.gov returned HTTP {response.status_code}: {body}"
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if not any(content_type == item or content_type.startswith(item) for item in allowed_types):
                        raise RuntimeError(
                            f"Unexpected Content-Type {content_type!r} from Acquisition.gov."
                        )
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) > max_bytes:
                        raise RuntimeError(
                            f"Acquisition.gov content exceeds the {max_bytes}-byte limit."
                        )
                    return response_body, content_type, current
        except httpx.RequestError as exc:
            raise RuntimeError(f"Network error calling Acquisition.gov: {exc}") from exc
    raise RuntimeError("Acquisition.gov exceeded the redirect limit.")


async def _bounded_httpx_body(
    response: httpx.Response, *, max_bytes: int
) -> bytes:
    length = response.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_bytes:
        raise RuntimeError(f"Acquisition.gov content exceeds the {max_bytes}-byte limit.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise RuntimeError(f"Acquisition.gov content exceeds the {max_bytes}-byte limit.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _curl_once(url: str, *, max_bytes: int) -> tuple[httpx.Response, bytes]:
    """Fetch one validated URL with system curl, without following redirects.

    This is a compatibility fallback for TLS/CDN combinations that stall the
    Python transport. The caller still owns host validation and redirect policy.
    """
    executable = shutil.which("curl")
    if not executable:
        raise RuntimeError("System curl fallback is unavailable.")

    def run() -> tuple[httpx.Response, bytes]:
        with tempfile.TemporaryDirectory(prefix="acquisition-gov-mcp-") as temporary:
            root = Path(temporary)
            headers_path = root / "headers"
            body_path = root / "body"
            completed = subprocess.run(
                [
                    executable,
                    "--silent",
                    "--show-error",
                    "--proto",
                    "=https",
                    "--max-time",
                    str(int(DEFAULT_TIMEOUT)),
                    "--max-filesize",
                    str(max_bytes),
                    "--max-redirs",
                    "0",
                    "--header",
                    f"User-Agent: {USER_AGENT}",
                    "--header",
                    "Accept: text/html,application/pdf",
                    "--dump-header",
                    str(headers_path),
                    "--output",
                    str(body_path),
                    "--write-out",
                    "STATUS:%{http_code}\nTYPE:%{content_type}\nREDIRECT:%{redirect_url}\n",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT + 2,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "System curl could not retrieve Acquisition.gov: "
                    f"exit {completed.returncode}; {completed.stderr.strip()[:300]}"
                )
            metadata = {
                key: value
                for line in completed.stdout.splitlines()
                if ":" in line
                for key, value in [line.split(":", 1)]
            }
            if not {"STATUS", "TYPE", "REDIRECT"}.issubset(metadata):
                raise RuntimeError("System curl returned incomplete response metadata.")
            status = int(metadata["STATUS"])
            content_type = metadata["TYPE"]
            redirect_url = metadata["REDIRECT"]
            raw_headers = headers_path.read_text(encoding="iso-8859-1")
            header_blocks = [block for block in re.split(r"\r?\n\r?\n", raw_headers) if block.strip()]
            header_lines = header_blocks[-1].splitlines() if header_blocks else []
            headers: dict[str, str] = {}
            for line in header_lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip()] = value.strip()
            if content_type and "Content-Type" not in headers:
                headers["Content-Type"] = content_type
            if redirect_url and "Location" not in headers:
                headers["Location"] = redirect_url
            body = body_path.read_bytes() if body_path.exists() else b""
            if len(body) > max_bytes:
                raise RuntimeError(
                    f"Acquisition.gov content exceeds the {max_bytes}-byte limit."
                )
            return httpx.Response(status, headers=headers, content=body), body

    try:
        return await asyncio.to_thread(run)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("System curl timed out calling Acquisition.gov.") from exc


def _main_content(html: bytes) -> Tag | BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, nav, header, footer, form"):
        node.decompose()
    return (
        soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one(".region-content")
        or soup
    )


def _text_lines(node: Tag | BeautifulSoup) -> list[str]:
    return [" ".join(line.split()) for line in node.get_text("\n").splitlines() if line.strip()]


def _extract_section(node: Tag | BeautifulSoup, section: str | None) -> str:
    if section is None:
        return "\n".join(_text_lines(node))
    needle = " ".join(section.split()).casefold()
    heading = next(
        (
            h
            for h in node.find_all(re.compile(r"^h[1-6]$"))
            if needle in " ".join(h.get_text(" ", strip=True).split()).casefold()
        ),
        None,
    )
    if heading is None:
        raise ValueError(f"section {section!r} was not found in the official source.")
    level = int(heading.name[1])
    lines = [" ".join(heading.get_text(" ", strip=True).split())]
    for sibling in heading.find_all_next():
        if sibling is heading:
            continue
        if re.fullmatch(r"h[1-6]", sibling.name or "") and int(sibling.name[1]) <= level:
            break
        if sibling.name in {"p", "li", "table"}:
            text = " ".join(sibling.get_text(" ", strip=True).split())
            if text:
                lines.append(text)
    return "\n".join(lines)


def _chunk(text: str, cursor: str | None, maximum: int) -> dict[str, Any]:
    if not 1_000 <= maximum <= MAX_OUTPUT_CHARACTERS:
        raise ValueError(
            f"max_characters must be between 1000 and {MAX_OUTPUT_CHARACTERS}."
        )
    if cursor is None:
        start = 0
    elif not cursor.isdigit():
        raise ValueError("cursor must be the numeric cursor returned by a prior call.")
    else:
        start = int(cursor)
    if start < 0 or start > len(text):
        raise ValueError(f"cursor is outside the source text (length {len(text)}).")
    end = min(len(text), start + maximum)
    return {
        "content": text[start:end],
        "cursor": str(start),
        "next_cursor": str(end) if end < len(text) else None,
        "truncated": end < len(text),
        "total_characters": len(text),
    }


def _part_from_card(card: Tag) -> int | None:
    title = card.select_one(".far-title") or card.find(re.compile(r"^h[1-6]$"))
    match = _PART_RE.search(title.get_text(" ", strip=True) if title else card.get_text(" ", strip=True))
    return int(match.group(1)) if match else None


def _agency_name(link: Tag) -> str:
    raw = link.get("title") or link.get_text(" ", strip=True)
    text = " ".join(str(raw).split())
    text = re.sub(r"\s+(?:class\s+)?deviation.*$", "", text, flags=re.I)
    return text.strip(" :-") or "Unspecified agency"


def _parse_index(html: bytes, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".content-card.far-card") or soup.select(".far-card")
    results: list[dict[str, Any]] = []
    for ordinal, card in enumerate(cards, start=1):
        part = _part_from_card(card)
        if part is None:
            continue
        title_node = card.select_one(".far-title a") or card.find("a")
        part_url = _validated_url(urljoin(source_url, title_node.get("href"))) if title_node and title_node.get("href") else f"{RFO_INDEX_URL}/far-overhaul-part-{part}"
        title = (
            " ".join(title_node.get_text(" ", strip=True).split())
            if title_node
            else f"FAR Part {part}"
        )
        card_text = " ".join(card.get_text(" ", strip=True).split())
        issuance = (
            _labeled_date(card_text, "Issuance")
            or _labeled_date(card_text, "Issued")
            or _labeled_date(card_text, "Published")
        )
        updated = _labeled_date(card_text, "Update") or _labeled_date(card_text, "Updated")
        deviations: list[dict[str, Any]] = []
        details = card.select_one("details.agency-deviations") or card.select_one(".agency-deviations")
        for occurrence, link in enumerate(details.find_all("a") if details else [], start=1):
            href = link.get("href")
            if not href:
                continue
            url = _validated_url(urljoin(source_url, href))
            deviations.append(
                {
                    "source_id": _source_id("agency-deviation", url),
                    "source_kind": "agency_class_deviation",
                    "agency": _agency_name(link),
                    "far_parts": [part],
                    "source_url": url,
                    "index_occurrence": occurrence,
                    "issuance_date": None,
                    "updated_date": None,
                    "effective_date": None,
                    "expiration_date": None,
                    "applicability_text": None,
                    "retrieved_at": None,
                    "content_sha256": None,
                    "text_extraction_status": "not_retrieved",
                    "warnings": ["Dates and applicability require retrieval of the official document."],
                }
            )
        results.append(
            {
                "source_id": _source_id("model-part", part_url),
                "source_kind": "model_deviation",
                "part": part,
                "title": title,
                "source_url": part_url,
                "issuance_date": issuance,
                "updated_date": updated,
                "agency_deviations": deviations,
                "index_ordinal": ordinal,
            }
        )
    return results


async def _index() -> tuple[list[dict[str, Any]], str, str, str]:
    body, _, final_url = await _fetch_bytes(
        RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=MAX_HTML_BYTES
    )
    return _parse_index(body, final_url), final_url, _sha(body), _now()


def _extract_document_fields(page_texts: list[tuple[int, str]]) -> dict[str, Any]:
    joined = "\n".join(text for _, text in page_texts)
    applicability: list[str] = []
    for page, text in page_texts:
        for line in text.splitlines():
            cleaned = " ".join(line.split())
            if re.search(r"\b(applicability|applies to|applicable to)\b", cleaned, re.I):
                applicability.append(f"Page {page}: {cleaned}")
    return {
        "issuance_date": _labeled_date(joined, "Issued") or _labeled_date(joined, "Date"),
        "effective_date": _labeled_date(joined, "Effective"),
        "expiration_date": _labeled_date(joined, "Expiration") or _labeled_date(joined, "Expires"),
        "applicability_text": "\n".join(applicability[:12]) or None,
    }


def _read_pdf(
    body: bytes, *, page_start: int, page_end: int | None
) -> tuple[str, str, list[str], dict[str, Any], int, int]:
    warnings: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception as exc:
        return "", "error", [f"PDF parsing failed: {type(exc).__name__}: {exc}"], {}, 0, 0
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            return "", "encrypted", ["The official PDF is encrypted and could not be extracted."], {}, len(reader.pages), 0
    total = len(reader.pages)
    if total == 0:
        return "", "unextractable", ["The PDF contains no pages."], {}, 0, 0
    if page_start < 1 or page_start > total:
        raise ValueError(f"page_start must be between 1 and {total}.")
    end = min(total, page_end if page_end is not None else min(total, page_start + 9))
    if end < page_start:
        raise ValueError("page_end must be greater than or equal to page_start.")
    if end - page_start + 1 > MAX_PDF_PAGES:
        raise ValueError(f"A single call may retrieve at most {MAX_PDF_PAGES} pages.")
    pages: list[tuple[int, str]] = []
    empty = 0
    for number in range(page_start, end + 1):
        try:
            text = reader.pages[number - 1].extract_text() or ""
        except Exception as exc:
            warnings.append(f"Page {number} extraction failed: {type(exc).__name__}.")
            text = ""
        cleaned = text.strip()
        if not cleaned:
            empty += 1
        pages.append((number, cleaned))
    if empty == len(pages):
        status = "unextractable"
        warnings.append("Selected pages contain no extractable text and may be scanned images.")
    elif empty:
        status = "partial"
        warnings.append(f"{empty} selected page(s) contained no extractable text.")
    else:
        status = "complete"
    numbered = "\n\n".join(f"[Page {page}]\n{text}" for page, text in pages)
    return numbered, status, warnings, _extract_document_fields(pages), total, end


@mcp.tool(annotations={"title": "List FAR Overhaul parts", "readOnlyHint": True, "destructiveHint": False})
async def list_rfo_parts(
    part: int | None = None,
    agency: str | None = None,
    updated_since: str | None = None,
) -> dict[str, Any]:
    """List official RFO model parts and counts of posted agency deviations."""
    wanted_part = _validate_part(part) if part is not None else None
    since = _validate_date(updated_since, "updated_since")
    agency_filter = " ".join(agency.split()).casefold() if agency and agency.strip() else None
    parts, source_url, digest, retrieved = await _index()
    results: list[dict[str, Any]] = []
    for item in parts:
        if wanted_part is not None and item["part"] != wanted_part:
            continue
        if since and item["updated_date"] and item["updated_date"] < since:
            continue
        matches = [
            deviation
            for deviation in item["agency_deviations"]
            if not agency_filter or agency_filter in deviation["agency"].casefold()
        ]
        if agency_filter and not matches:
            continue
        results.append(
            {
                key: value
                for key, value in item.items()
                if key != "agency_deviations"
            }
            | {"agency_deviation_count": len(matches)}
        )
    return {
        "source_url": source_url,
        "retrieved_at": retrieved,
        "content_sha256": digest,
        "count": len(results),
        "results": results,
        "warnings": [
            "This index documents posted sources; it does not decide which text governs a procurement."
        ],
    }


@mcp.tool(annotations={"title": "Get FAR Overhaul model part", "readOnlyHint": True, "destructiveHint": False})
async def get_rfo_part(
    part: int,
    section: str | None = None,
    cursor: str | None = None,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> dict[str, Any]:
    """Return parsed, paginated model-deviation text for one FAR part."""
    wanted = _validate_part(part)
    body, _, final_url = await _fetch_bytes(
        f"{RFO_INDEX_URL}/far-overhaul-part-{wanted}",
        allowed_types=("text/html",),
        max_bytes=MAX_HTML_BYTES,
    )
    node = _main_content(body)
    text = _extract_section(node, section)
    page = _chunk(text, cursor, max_characters)
    full_text = "\n".join(_text_lines(node))
    return {
        "source_id": _source_id("model-part", final_url),
        "source_kind": "model_deviation",
        "agency": None,
        "far_parts": [wanted],
        "source_url": final_url,
        "issuance_date": (
            _labeled_date(full_text, "Issuance")
            or _labeled_date(full_text, "Issued")
            or _labeled_date(full_text, "Published")
        ),
        "updated_date": _labeled_date(full_text, "Update") or _labeled_date(full_text, "Updated"),
        "effective_date": None,
        "expiration_date": None,
        "applicability_text": None,
        "retrieved_at": _now(),
        "content_sha256": _sha(body),
        "text_extraction_status": "complete",
        "warnings": [
            "RFO model text is not operative for an agency unless that agency adopts it through a deviation."
        ],
        "section": section,
        **page,
    }


@mcp.tool(annotations={"title": "List posted agency RFO deviations", "readOnlyHint": True, "destructiveHint": False})
async def list_rfo_agency_deviations(
    agency: str | None = None,
    part: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List official agency-deviation links discovered through the RFO index."""
    if not (agency and agency.strip()) and part is None:
        raise ValueError("At least one filter is required: agency or part.")
    if not 1 <= limit <= 250:
        raise ValueError("limit must be between 1 and 250.")
    wanted_part = _validate_part(part) if part is not None else None
    agency_filter = " ".join(agency.split()).casefold() if agency and agency.strip() else None
    parts, source_url, digest, retrieved = await _index()
    matches: list[dict[str, Any]] = []
    for item in parts:
        if wanted_part is not None and item["part"] != wanted_part:
            continue
        for deviation in item["agency_deviations"]:
            if agency_filter and agency_filter not in deviation["agency"].casefold():
                continue
            matches.append(deviation | {"retrieved_at": retrieved})
    selected = matches[:limit]
    names = sorted({item["agency"] for item in matches})
    warnings = [
        "Documents are listed as posted; retrieve the PDF before relying on dates or applicability."
    ]
    if agency_filter and len(names) > 1:
        warnings.append(f"The agency filter matched multiple normalized names: {names}.")
    if len(matches) > limit:
        warnings.append(f"Results were truncated from {len(matches)} to {limit}.")
    duplicate_count = len(matches) - len({(m["source_id"], tuple(m["far_parts"])) for m in matches})
    if duplicate_count:
        warnings.append(f"The official index contains {duplicate_count} duplicate entry or entries; they were preserved.")
    return {
        "source_url": source_url,
        "retrieved_at": retrieved,
        "content_sha256": digest,
        "count": len(selected),
        "total_matches": len(matches),
        "results": selected,
        "warnings": warnings,
    }


@mcp.tool(annotations={"title": "Get posted agency RFO deviation", "readOnlyHint": True, "destructiveHint": False})
async def get_rfo_agency_deviation(
    source_id: str,
    page_start: int = 1,
    page_end: int | None = None,
) -> dict[str, Any]:
    """Resolve an indexed source ID and return page-numbered official PDF text."""
    if not source_id.startswith("agency-deviation-"):
        raise ValueError("source_id must come from list_rfo_agency_deviations.")
    parts, _, _, index_retrieved = await _index()
    discovered = [
        deviation
        for item in parts
        for deviation in item["agency_deviations"]
        if deviation["source_id"] == source_id
    ]
    if not discovered:
        raise ValueError("source_id is not present in the current official RFO index.")
    target = discovered[0] | {
        "far_parts": sorted({part for item in discovered for part in item["far_parts"]})
    }
    body, _, final_url = await _fetch_bytes(
        target["source_url"], allowed_types=("application/pdf",), max_bytes=MAX_PDF_BYTES
    )
    text, status, warnings, fields, total_pages, selected_end = _read_pdf(
        body, page_start=page_start, page_end=page_end
    )
    total_extracted_characters = len(text)
    text_truncated = total_extracted_characters > MAX_OUTPUT_CHARACTERS
    if text_truncated:
        text = text[:MAX_OUTPUT_CHARACTERS]
        warnings.append(
            f"Page-numbered text was truncated at {MAX_OUTPUT_CHARACTERS} characters; "
            "request a smaller page range to retrieve the omitted text."
        )
    if len(discovered) > 1:
        warnings.append(
            f"The same source appears {len(discovered)} times in the official index; duplicate metadata was preserved."
        )
    return {
        **target,
        **fields,
        "source_url": final_url,
        "retrieved_at": _now(),
        "index_retrieved_at": index_retrieved,
        "content_sha256": _sha(body),
        "text_extraction_status": status,
        "warnings": warnings,
        "total_pages": total_pages,
        "page_start": page_start,
        "page_end": selected_end,
        "page_numbered_text": text,
        "returned_characters": len(text),
        "total_extracted_characters": total_extracted_characters,
        "text_truncated": text_truncated,
        "duplicate_index_entries": [item for item in discovered[1:]],
    }


@mcp.tool(annotations={"title": "Get approved RFO guidance", "readOnlyHint": True, "destructiveHint": False})
async def get_rfo_guidance(
    resource: Literal["faq", "policy_and_guidance", "deviation_guidance"],
    heading: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return an allowlisted Acquisition.gov RFO FAQ or guidance resource."""
    url = GUIDANCE_URLS[resource]
    if resource == "deviation_guidance":
        body, _, final_url = await _fetch_bytes(
            url, allowed_types=("application/pdf",), max_bytes=MAX_PDF_BYTES
        )
        text, status, warnings, fields, total_pages, _ = _read_pdf(
            body, page_start=1, page_end=MAX_PDF_PAGES
        )
        if heading:
            lines = text.splitlines()
            indices = [i for i, line in enumerate(lines) if heading.casefold() in line.casefold()]
            if not indices:
                raise ValueError(f"heading {heading!r} was not found in the guidance PDF.")
            text = "\n".join(lines[indices[0]:])
        page = _chunk(text, cursor, DEFAULT_MAX_CHARACTERS)
        return {
            "source_id": _source_id("guidance", final_url),
            "source_kind": "nonregulatory_guidance",
            "agency": "FAR Council",
            "far_parts": [],
            "source_url": final_url,
            "updated_date": None,
            **fields,
            "retrieved_at": _now(),
            "content_sha256": _sha(body),
            "text_extraction_status": status,
            "warnings": warnings + ["Guidance is not codified regulatory text."],
            "total_pages": total_pages,
            "heading": heading,
            **page,
        }
    body, _, final_url = await _fetch_bytes(
        url, allowed_types=("text/html",), max_bytes=MAX_HTML_BYTES
    )
    node = _main_content(body)
    text = _extract_section(node, heading)
    page = _chunk(text, cursor, DEFAULT_MAX_CHARACTERS)
    full_text = "\n".join(_text_lines(node))
    return {
        "source_id": _source_id("guidance", final_url),
        "source_kind": "nonregulatory_guidance",
        "agency": "Acquisition.gov",
        "far_parts": [],
        "source_url": final_url,
        "issuance_date": (
            _labeled_date(full_text, "Issuance")
            or _labeled_date(full_text, "Issued")
            or _labeled_date(full_text, "Published")
        ),
        "updated_date": _labeled_date(full_text, "Update") or _labeled_date(full_text, "Updated"),
        "effective_date": None,
        "expiration_date": None,
        "applicability_text": None,
        "retrieved_at": _now(),
        "content_sha256": _sha(body),
        "text_extraction_status": "complete",
        "warnings": ["Guidance is not codified regulatory text."],
        "heading": heading,
        **page,
    }


def _forbid_extra_params_on_all_tools() -> None:
    for tool in mcp._tool_manager.list_tools():
        model = tool.fn_metadata.arg_model
        model.model_config = {**model.model_config, "extra": "forbid"}
        model.model_rebuild(force=True)


_forbid_extra_params_on_all_tools()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
