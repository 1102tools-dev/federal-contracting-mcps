"""Pure, bounded HTML parsing helpers shared with the isolated worker."""
from __future__ import annotations
import hashlib
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup, Tag, NavigableString, CData
from ._pdf import _labeled_date
from .constants import ALLOWED_HOSTS, MAX_HTML_BYTES, MAX_OUTPUT_CHARACTERS, RFO_INDEX_URL, DEFAULT_MAX_CHARACTERS
_PART_RE = re.compile(r"(?:FAR\s*)?Part\s*[-:]?\s*(\d{1,2})", re.I)

def _source_id(kind: str, url: str) -> str:
    return f"{kind}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]}"

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

def _validate_html_body(html: bytes) -> None:
    if len(html) > MAX_HTML_BYTES:
        raise RuntimeError("HTML source exceeds the size limit.")
    count = 0
    for tag in re.finditer(rb"<[^>]*>", html):
        count += 1
        if count > 75_000 or len(tag.group()) > 16_384:
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
    content = (soup.find("main") or soup.find("article")
               or soup.find(class_="region-content") or soup)
    # A CSS selector list tests every element repeatedly. One bounded tree walk
    # preserves exactly the same prune rules without that multiplicative cost.
    unwanted_tags = {"script", "style", "nav", "header", "footer", "form"}
    unwanted_nodes = [tag for tag in content.descendants if isinstance(tag, Tag)
                      and (tag.name in unwanted_tags
                           or "block-agov-favorites" in tag.get("class", [])
                           or tag.get("id") == "system-breadcrumb")]
    for unwanted in unwanted_nodes:
        # A source may wrap its main content in a form. Only prune descendants,
        # never the selected content root or an ancestor containing it.
        if unwanted.parent is not None:
            unwanted.decompose()
    return content

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
    exact = [h for h in headings if " ".join(h.get_text(" ", strip=True).split()).casefold() == needle]
    candidates = exact or [h for h in headings if matches(h)]
    if not candidates:
        raise ValueError(f"section {section!r} was not found in the official source.")
    if len(candidates) > 1:
        raise ValueError(f"section {section!r} matches multiple headings; use a more specific heading.")
    heading = candidates[0]
    level = int(heading.name[1])
    lines: list[str] = []
    # Walk text nodes in document order rather than consuming whole containers.
    # This retains div/bare/definition text, avoids nested-heading duplication,
    # and cannot pull text across the next section through an enclosing table/list.
    for element in heading.next_elements:
        if not any(parent is node for parent in element.parents):
            break
        if isinstance(element, Tag) and re.fullmatch(r"h[1-6]", element.name or ""):
            if int(element.name[1]) <= level:
                break
        elif type(element) in (NavigableString, CData):
            text = " ".join(str(element).split())
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
    title = " ".join(str(link.get("title") or "").split())
    visible = link.get_text(" ", strip=True)
    generic = re.fullmatch(r"(?:download|view|open)?\s*(?:pdf|document|file)?", title, re.I)
    raw = visible if generic and visible.strip() else title or visible
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
        index_warnings: list[str] = []
        details = card.select_one("details.agency-deviations") or card.select_one(".agency-deviations")
        for occurrence, link in enumerate(details.find_all("a") if details else [], start=1):
            href = link.get("href")
            if not href:
                continue
            try:
                url = _validated_url(urljoin(source_url, href))
            except ValueError:
                index_warnings.append("An agency-deviation link was skipped because it is outside permitted HTTPS Acquisition.gov sources; the deviation count excludes that link.")
                continue
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
                "warnings": index_warnings,
            }
        )
    return results

def _parse_html_document(body, *, part=None, heading=None, cursor=None, maximum=DEFAULT_MAX_CHARACTERS):
    node = _main_content(body)
    if part is not None:
        hidden_classes = {"visual-hidden", "hidden", "usa-sr-only"}
        visible_titles = [h for h in node.find_all("h1") if not hidden_classes.intersection(h.get("class", []))]
        if any((match := _PART_RE.search(h.get_text(" ", strip=True))) and int(match.group(1)) == part for h in visible_titles):
            for h in [tag for tag in node.descendants if isinstance(tag, Tag)
                      and ((tag.name == "h1" and "visual-hidden" in tag.get("class", []))
                           or (tag.name == "h2" and "hidden" in tag.get("class", [])))]:
                match = _PART_RE.search(h.get_text(" ", strip=True))
                if match and int(match.group(1)) == part:
                    h.decompose()
        title = node.find("h1") or node.find("h2")
        title_part = _PART_RE.search(title.get_text(" ", strip=True)) if title else None
        if title_part is None or int(title_part.group(1)) != part:
            raise RuntimeError(f"The returned HTML could not be verified as FAR Overhaul Part {part}.")
    text = _extract_section(node, heading)
    full_text = text if heading is None else "\n".join(_text_lines(node))
    return {
        **_chunk(text, cursor, maximum),
        "issuance_date": (_labeled_date(full_text, "Issuance") or _labeled_date(full_text, "Issued") or _labeled_date(full_text, "Published")),
        "updated_date": _labeled_date(full_text, "Update") or _labeled_date(full_text, "Updated"),
    }
