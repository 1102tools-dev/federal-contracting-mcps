# SPDX-License-Identifier: MIT
"""Read-only MCP server for official FAR Overhaul resources on Acquisition.gov."""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import json
import sys
import tempfile
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag
from mcp.server import MCPServer

from ._pdf import _normalize_date, _labeled_date, _extract_document_fields, _read_pdf
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
    MAX_PDF_PARSE_SECONDS,
    MAX_PDF_WORKER_BYTES,
    MAX_REDIRECTS,
    RFO_INDEX_URL,
    USER_AGENT,
)

mcp = MCPServer("acquisition-gov", version=__version__)
_client: httpx.AsyncClient | None = None
_prefer_system_curl = False
_pdf_slots = asyncio.Semaphore(1)
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




def _validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("Only HTTPS Acquisition.gov URLs are permitted.")
    if parsed.username is not None or parsed.password is not None or ":" in parsed.netloc:
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
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf", "Accept-Encoding": "identity"},
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
                if not 200 <= response.status_code < 300:
                    body = response_body[:500].decode("utf-8", "replace")
                    raise RuntimeError(
                        f"Acquisition.gov returned HTTP {response.status_code}: {body}"
                    )
                if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                    raise RuntimeError("Unexpected compressed Acquisition.gov response; identity encoding is required.")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in allowed_types:
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
    if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
        raise RuntimeError("Unexpected compressed Acquisition.gov response; identity encoding is required.")
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
    """One HTTPS fetch, with a streaming body bound independent of curl version."""
    url = _validated_url(url)
    executable = shutil.which("curl")
    if not executable:
        raise RuntimeError("System curl fallback is unavailable.")
    with tempfile.TemporaryDirectory(prefix="acquisition-gov-mcp-") as temporary:
        headers_path = Path(temporary) / "headers"
        process = await asyncio.create_subprocess_exec(
            executable, "--disable", "--silent", "--show-error", "--proto", "=https",
            "--max-time", str(int(DEFAULT_TIMEOUT)), "--max-filesize", str(max_bytes),
            "--max-redirs", "0", "--header", f"User-Agent: {USER_AGENT}",
            "--header", "Accept: text/html,application/pdf", "--header", "Accept-Encoding: identity",
            "--dump-header", str(headers_path), "--output", "-",
            "--write-out", "%{stderr}\nSTATUS:%{http_code}\nTYPE:%{content_type}\nREDIRECT:%{redirect_url}\n", url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        async def bounded_read(stream, limit):
            chunks = []
            size = 0
            while chunk := await stream.read(65536):
                size += len(chunk)
                if size > limit:
                    raise RuntimeError(f"Acquisition.gov curl response exceeds the {limit}-byte limit.")
                chunks.append(chunk)
            return b"".join(chunks)
        tasks = [asyncio.create_task(bounded_read(process.stdout, max_bytes)),
                 asyncio.create_task(bounded_read(process.stderr, 8192)),
                 asyncio.create_task(process.wait())]
        try:
            try:
                body, errors, _ = await asyncio.wait_for(asyncio.gather(*tasks), DEFAULT_TIMEOUT + 2)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("System curl timed out calling Acquisition.gov.") from exc
            if process.returncode:
                raise RuntimeError(f"System curl could not retrieve Acquisition.gov: exit {process.returncode}; {errors.decode('utf-8', 'replace').strip()[:300]}")
            metadata = dict(line.split(":", 1) for line in errors.decode().splitlines() if ":" in line)
            if not {"STATUS", "TYPE", "REDIRECT"}.issubset(metadata):
                raise RuntimeError("System curl returned incomplete response metadata.")
            status = int(metadata["STATUS"])
            raw_headers = headers_path.read_text(encoding="iso-8859-1")
            blocks = [block for block in re.split(r"\r?\n\r?\n", raw_headers) if block.strip()]
            lines = blocks[-1].splitlines() if blocks else []
            headers = dict((k.strip(), v.strip()) for line in lines[1:] if ":" in line for k, v in [line.split(":", 1)])
            normalized = httpx.Headers(headers)
            if metadata["TYPE"] and "content-type" not in normalized:
                normalized["content-type"] = metadata["TYPE"]
            if metadata["REDIRECT"] and "location" not in normalized:
                normalized["location"] = metadata["REDIRECT"]
            return httpx.Response(status, headers=normalized, content=body), body
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def _validate_html_body(html: bytes) -> None:
    if len(html) > MAX_HTML_BYTES:
        raise RuntimeError("HTML source exceeds the size limit.")
    count = 0
    for tag in re.finditer(rb"<[^>]*>", html):
        count += 1
        if count > 20_000 or len(tag.group()) > 16_384:
            raise RuntimeError("HTML source exceeds the parser complexity limit.")

    class DepthGuard(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.stack = []
        def handle_starttag(self, tag, attrs):
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self.stack.append(tag)
                if len(self.stack) > 128:
                    raise RuntimeError("HTML source exceeds the nesting limit.")
        def handle_startendtag(self, tag, attrs):
            pass
        def handle_endtag(self, tag):
            if tag in self.stack:
                index = len(self.stack) - 1 - self.stack[::-1].index(tag)
                del self.stack[index:]
    DepthGuard().feed(html.decode("utf-8", "replace"))


def _main_content(html: bytes) -> Tag | BeautifulSoup:
    _validate_html_body(html)
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


def _validate_heading(section: str | None) -> str | None:
    if section is None:
        return None
    if not section.strip() or len(section) > 500:
        raise ValueError("section/heading must contain 1 through 500 nonblank characters.")
    return " ".join(section.split())


def _validate_chunk_inputs(cursor: str | None, maximum: int) -> None:
    if not 1_000 <= maximum <= MAX_OUTPUT_CHARACTERS:
        raise ValueError(f"max_characters must be between 1000 and {MAX_OUTPUT_CHARACTERS}.")
    if cursor is not None and (not re.fullmatch(r"[0-9]{1,9}", cursor)):
        raise ValueError("cursor must be the numeric cursor returned by a prior call.")


def _extract_section(node: Tag | BeautifulSoup, section: str | None) -> str:
    section = _validate_heading(section)
    if section is None:
        text = "\n".join(_text_lines(node))
        if not text:
            raise RuntimeError("The official HTML source contains no extractable content.")
        return text
    needle = section.casefold()
    headings = list(node.find_all(re.compile(r"^h[1-6]$")))
    def matches(h):
        text = " ".join(h.get_text(" ", strip=True).split()).casefold()
        return re.search(r"(?<![\w.])" + re.escape(needle) + r"(?![\w.])", text) is not None
    exact = [h for h in headings if h.get_text(" ", strip=True).casefold() == needle]
    candidates = exact or [h for h in headings if matches(h)]
    if not candidates:
        raise ValueError(f"section {section!r} was not found in the official source.")
    if len(candidates) > 1:
        raise ValueError(f"section {section!r} matches multiple headings; use a more specific heading.")
    heading = candidates[0]
    level = int(heading.name[1])
    lines = [" ".join(heading.get_text(" ", strip=True).split())]
    for sibling in heading.find_all_next():
        if node not in sibling.parents:
            break
        if re.fullmatch(r"h[1-6]", sibling.name or ""):
            if int(sibling.name[1]) <= level:
                break
            lines.append(" ".join(sibling.get_text(" ", strip=True).split()))
        elif sibling.name in {"p", "li", "table"}:
            # Parent list/table text already includes descendants.
            if any(parent.name in {"p", "li", "table"} for parent in sibling.parents if parent is not node):
                continue
            text = " ".join(sibling.get_text(" ", strip=True).split())
            if text:
                lines.append(text)
    return "\n".join(lines)


def _chunk(text: str, cursor: str | None, maximum: int) -> dict[str, Any]:
    _validate_chunk_inputs(cursor, maximum)
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
    _validate_html_body(html)
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".content-card.far-card") or soup.select(".far-card")
    results: list[dict[str, Any]] = []
    for ordinal, card in enumerate(cards, start=1):
        part = _part_from_card(card)
        if part is None or not 1 <= part <= 53:
            raise RuntimeError("The Acquisition.gov index contains an unrecognized FAR part card.")
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
    parts = _parse_index(body, final_url)
    if not parts:
        raise RuntimeError("The Acquisition.gov index structure was not recognized; no results can be confirmed.")
    return parts, final_url, _sha(body), _now()




async def _read_pdf_safely(body: bytes, *, page_start: int, page_end: int | None):
    """Keep PDF CPU/memory faults and cancellation outside the main event loop."""
    if len(body) > MAX_PDF_BYTES:
        raise ValueError("PDF input exceeds the download limit.")
    async with _pdf_slots:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "acquisition_gov_mcp._pdf_worker",
            str(page_start), "none" if page_end is None else str(page_end),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            try:
                output, _ = await asyncio.wait_for(process.communicate(body), MAX_PDF_PARSE_SECONDS)
            except asyncio.TimeoutError:
                return "", "error", ["PDF parsing exceeded its time budget; request fewer pages or inspect the source document."], {}, 0, 0
            if process.returncode or len(output) > MAX_PDF_WORKER_BYTES:
                return "", "error", ["PDF parsing failed or exceeded its resource budget; inspect the source document."], {}, 0, 0
            try:
                return tuple(json.loads(output))
            except (ValueError, TypeError):
                return "", "error", ["PDF parser returned an invalid result."], {}, 0, 0
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


@mcp.tool(annotations={"title": "List FAR Overhaul parts", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
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
    warnings = ["This index documents posted sources; it does not decide which text governs a procurement."]
    if since and any(item["updated_date"] is None for item in results):
        warnings.append("Entries without an update date were retained; they cannot be confirmed as updated since the requested date.")
    return {
        "source_url": source_url,
        "retrieved_at": retrieved,
        "content_sha256": digest,
        "count": len(results),
        "results": results,
        "warnings": warnings,
    }


@mcp.tool(annotations={"title": "Get FAR Overhaul model part", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_rfo_part(
    part: int,
    section: str | None = None,
    cursor: str | None = None,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> dict[str, Any]:
    """Return parsed, paginated model-deviation text for one FAR part."""
    wanted = _validate_part(part)
    _validate_chunk_inputs(cursor, max_characters)
    _validate_heading(section)
    body, _, final_url = await _fetch_bytes(
        f"{RFO_INDEX_URL}/far-overhaul-part-{wanted}",
        allowed_types=("text/html",),
        max_bytes=MAX_HTML_BYTES,
    )
    node = _main_content(body)
    title = node.find(re.compile(r"^h[1-2]$"))
    title_part = _PART_RE.search(title.get_text(" ", strip=True)) if title else None
    if title_part is None or int(title_part.group(1)) != wanted:
        raise RuntimeError(f"The returned HTML could not be verified as FAR Overhaul Part {wanted}.")
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


@mcp.tool(annotations={"title": "List posted agency RFO deviations", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
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


@mcp.tool(annotations={"title": "Get posted agency RFO deviation", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_rfo_agency_deviation(
    source_id: str,
    page_start: int = 1,
    page_end: int | None = None,
) -> dict[str, Any]:
    """Resolve an indexed source ID and return page-numbered official PDF text."""
    if not re.fullmatch(r"agency-deviation-[a-f0-9]{20}", source_id):
        raise ValueError("source_id must come from list_rfo_agency_deviations.")
    if page_start < 1 or (page_end is not None and (page_end < page_start or page_end - page_start + 1 > MAX_PDF_PAGES)):
        raise ValueError(f"page_start/page_end must select 1 through {MAX_PDF_PAGES} pages in increasing order.")
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
    text, status, warnings, fields, total_pages, selected_end = await _read_pdf_safely(
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


@mcp.tool(annotations={"title": "Get approved RFO guidance", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_rfo_guidance(
    resource: Literal["faq", "policy_and_guidance", "deviation_guidance"],
    heading: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return an allowlisted Acquisition.gov RFO FAQ or guidance resource."""
    _validate_chunk_inputs(cursor, DEFAULT_MAX_CHARACTERS)
    _validate_heading(heading)
    if resource not in GUIDANCE_URLS:
        raise ValueError("resource must be faq, policy_and_guidance, or deviation_guidance.")
    url = GUIDANCE_URLS[resource]
    if resource == "deviation_guidance":
        body, _, final_url = await _fetch_bytes(
            url, allowed_types=("application/pdf",), max_bytes=MAX_PDF_BYTES
        )
        text, status, warnings, fields, total_pages, _ = await _read_pdf_safely(
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
