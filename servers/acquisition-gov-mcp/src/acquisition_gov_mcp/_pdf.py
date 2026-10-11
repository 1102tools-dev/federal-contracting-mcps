"""Bounded PDF text extraction; invoked in an isolated process by HTTP tools."""
from __future__ import annotations
import io
import re
from datetime import datetime
from typing import Any
from pypdf import PdfReader
from pypdf.generic import ContentStream
from ._errors import UserInputError
from .constants import MAX_PDF_PAGES, MAX_PDF_TEXT_CHARACTERS, MAX_PDF_PAGE_STREAM_BYTES

class UnreadableFontEncoding(ValueError):
    """PDF text consists of unresolved font glyph identifiers."""


class PdfPageRangeError(ValueError):
    """A valid PDF whose requested range is outside its actual page count."""
    def __init__(self, message: str, total_pages: int):
        super().__init__(message)
        self.total_pages = total_pages


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    text = " ".join(raw.replace("\xa0", " ").split()).strip(" .")
    text = re.sub(r"\bSept\b", "Sep", text, flags=re.I).replace(".", "") if text else text
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# Labels that only count at the start of a line. "Issued" mid-sentence is
# usually about another document ("OMB memorandum M-25-26 issued on May 2,
# 2025"), not this one.
_LINE_START_LABELS = {"date", "issued"}
_DATE_TEXT = (r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4}"
              r"|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})")
# A letterhead date, optionally followed by an explicit signing timestamp.
# GSA supplements use "2/20/2026 | 11:48:46 GMT" before the older attached memo.
# Keep this anchored: narrative references and arbitrary suffixes are not dates.
_STANDALONE_DATE = re.compile(
    r"^[ \t]*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})"
    r"(?:[ \t]*\|[ \t]*(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d[ \t]+(?:GMT|UTC))?[ \t]*$",
    re.M,
)


def _standalone_date_matches(text: str) -> list[re.Match]:
    """Return the current date of each adjacent date cluster on this page."""
    selected = []
    for match in _STANDALONE_DATE.finditer(text):
        if selected and not text[selected[-1].end():match.start()].strip():
            selected[-1] = match
        else:
            selected.append(match)
    return selected


def _standalone_date(text: str) -> str | None:
    matches = _standalone_date_matches(text)
    return _normalize_date(matches[0].group(1)) if matches else None


def _labeled_date(text: str, label: str) -> str | None:
    prefix = ((r"^\s*" if label.casefold() in _LINE_START_LABELS else r"\b")
              + rf"{re.escape(label)}(?:\s+date)?(?:\s*[:\-]\s*|\s+on\s+)")
    if label.casefold() == "effective":
        # DoD states the document's operative date as a direct sentence,
        # "Effective February 1, 2026, contracting officers shall use...".
        # A bare label must begin its line; a quoted or historical mid-sentence
        # "was effective ..." must not become this document's metadata.
        prefix = rf"^[ \t]*(?:\d+[.)]\s*)?{re.escape(label)}(?:\s+date)?(?:\s*[:\-]\s*|\s+on\s+|\s+)"
    pattern = re.compile(
        prefix + _DATE_TEXT,
        re.I | re.M,
    )
    match = pattern.search(text)
    return _normalize_date(match.group(1)) if match else None


# Relative dates require an explicit operative label, never a historical sentence.
_EFFECTIVE_RELATIVE = re.compile(
    r"^[ \t]*(?:\d+[.)]\s*)?effective(?:\s+date)?\s*:\s*"
    r"(?:immediately\b|(?:this\s+(?:PCD|deviation|CD)\s+is\s+)?effective\s+as\s+dated\b|as\s+dated\b)",
    re.I | re.M,
)


def _applicability_spans(text: str) -> list[tuple[int, int]]:
    """Matching lines, plus the scope paragraph after a standalone heading."""
    lines = text.splitlines(keepends=True)
    spans, offset = [], 0
    for i, line in enumerate(lines):
        content = line.rstrip("\r\n")
        cleaned = " ".join(content.split())
        if re.search(r"\b(applicability|applies to|applicable to)\b", cleaned, re.I):
            end = offset + len(content)
            if re.fullmatch(r"(?:\d+[.)]\s*)?APPLICABILITY\s*:?", cleaned, re.I):
                tail = end + len(line) - len(content)
                # Bounded to one paragraph; stop at the next numbered heading.
                for following in lines[i + 1:i + 13]:
                    if not following.strip() or re.match(r"\s*\d+[.)]\s+[A-Z][A-Z /&-]+:", following):
                        break
                    end = tail + len(following.rstrip("\r\n"))
                    tail += len(following)
            spans.append((offset, end))
        offset += len(line)
    return spans


def _extract_document_fields(page_texts: list[tuple[int, str]]) -> dict[str, Any]:
    joined = "\n".join(text for _, text in page_texts)
    applicability = [f"Page {page}: {' '.join(text[start:end].split())}"
                     for page, text in page_texts for start, end in _applicability_spans(text)]
    applicability_text = "\n".join(applicability[:12])
    if len(applicability_text) > 8192:
        applicability_text = applicability_text[:8160] + " [truncated]"
    issuance = (_labeled_date(joined, "Issued") or _labeled_date(joined, "Date")
                or next((date for _, text in page_texts if (date := _standalone_date(text))), None))
    effective = _labeled_date(joined, "Effective")
    if _EFFECTIVE_RELATIVE.search(joined):
        effective = issuance
    return {
        "issuance_date": issuance,
        "effective_date": effective,
        "expiration_date": _labeled_date(joined, "Expiration") or _labeled_date(joined, "Expires"),
        "applicability_text": applicability_text or None,
    }


def _has_outlined_text(page, reader) -> bool:
    """Recognize dense runs of small curved filled shapes used as letter outlines.

    Dense glyph-sized curves can contain rule-changing words omitted from plain
    extraction. Warn and withhold fragments instead of presenting them as rules.
    """
    contours, curved, coordinates = 0, False, []
    for operands, operator in ContentStream(page.get_contents(), reader).operations:
        if operator in (b'm', b'l', b'c', b'v', b'y'):
            coordinates.extend(float(value) for value in operands)
        if operator in (b'c', b'v', b'y'):
            curved = True
        if operator in (b'f', b'f*', b'B', b'B*'):
            if curved and coordinates and 2 < max(max(coordinates[::2]) - min(coordinates[::2]),
                                                     max(coordinates[1::2]) - min(coordinates[1::2])) < 30:
                contours += 1
                if contours >= 50:
                    return True
            curved, coordinates = False, []
        elif operator in (b'n', b'S', b's'):
            curved, coordinates = False, []
    return False


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
            return "", "encrypted", ["The official PDF is encrypted and could not be extracted."], {}, 0, 0
    total = len(reader.pages)
    if total == 0:
        return "", "unextractable", ["The PDF contains no pages."], {}, 0, 0
    if page_start < 1 or page_start > total:
        raise PdfPageRangeError(f"page_start must be between 1 and {total}; this PDF has {total} page(s).", total)
    end = min(total, page_end if page_end is not None else min(total, page_start + 9))
    if end < page_start:
        raise UserInputError("page_end must be greater than or equal to page_start.")
    if end - page_start + 1 > MAX_PDF_PAGES:
        raise UserInputError(f"A single call may retrieve at most {MAX_PDF_PAGES} pages.")
    pages: list[tuple[int, str]] = []
    empty = 0
    extracted = 0
    outlined_missing = False
    for number in range(page_start, end + 1):
        try:
            page = reader.pages[number - 1]
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_PDF_PAGE_STREAM_BYTES:
                raise RuntimeError("decoded page content exceeds the parser limit")
            text = page.extract_text() or ""
            if _has_outlined_text(page, reader):
                outlined_missing = True
                # Extractable fragments can retain deleted wording while the
                # replacement rule is drawn as outlines. Do not expose those
                # fragments as a usable account of this page's requirements.
                text = "[Parser notice: This page contains text drawn as outlines. Important words could not be extracted. Read the official PDF before deciding which rule applies.]"
                warnings.append(f"Page {number} contains outlined text that could not be recovered; important words may be missing. Consult the official PDF.")
            glyphs = re.findall(r"/(?:i?\d+)(?=/|\s|$)", text)
            if len(glyphs) >= 20 and text.count("/i255") >= 10 and sum(map(len, glyphs)) > len(text) * 0.5:
                raise UnreadableFontEncoding("unresolved glyph identifiers")
        except Exception as exc:
            warnings.append(f"Page {number} extraction failed: {type(exc).__name__}.")
            text = ""
            if isinstance(exc, UnreadableFontEncoding):
                warnings.append(f"Page {number} has unreadable font encoding; consult the official PDF for its text.")
        cleaned = text.strip()
        remaining = MAX_PDF_TEXT_CHARACTERS - extracted
        if len(cleaned) > remaining:
            cleaned = cleaned[:remaining]
            warnings.append(f"Extracted text reached the {MAX_PDF_TEXT_CHARACTERS}-character parser limit; request a smaller page range.")
        extracted += len(cleaned)
        if not cleaned:
            empty += 1
        pages.append((number, cleaned))
        if extracted >= MAX_PDF_TEXT_CHARACTERS:
            end = number
            break
    if page_start > 1 or end < total:
        warnings.append(f"Only pages {page_start} through {end} of {total} were examined; dates and applicability may appear elsewhere.")
    if empty == len(pages):
        status = "unextractable"
        warnings.append("Selected pages contain no extractable text and may be scanned images.")
    elif empty or outlined_missing or any("parser limit" in warning for warning in warnings):
        status = "partial"
        warnings.append(f"{empty} selected page(s) contained no extractable text.")
    else:
        status = "complete"
    numbered = "\n\n".join(f"[Page {page}]\n{text}" for page, text in pages)
    return numbered, status, warnings, _extract_document_fields(pages), total, end
