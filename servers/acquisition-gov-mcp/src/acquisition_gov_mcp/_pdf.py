"""Bounded PDF text extraction; invoked in an isolated process by HTTP tools."""
from __future__ import annotations
import io
import re
from datetime import datetime
from typing import Any
from pypdf import PdfReader
from .constants import MAX_PDF_PAGES, MAX_PDF_TEXT_CHARACTERS, MAX_PDF_PAGE_STREAM_BYTES

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
        (r"^\s*" if label.casefold() == "date" else r"\b")
        + rf"{re.escape(label)}(?:\s+date)?\s*[:\-]\s*"
        r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        re.I | re.M,
    )
    match = pattern.search(text)
    return _normalize_date(match.group(1)) if match else None


def _extract_document_fields(page_texts: list[tuple[int, str]]) -> dict[str, Any]:
    joined = "\n".join(text for _, text in page_texts)
    applicability: list[str] = []
    for page, text in page_texts:
        for line in text.splitlines():
            cleaned = " ".join(line.split())
            if re.search(r"\b(applicability|applies to|applicable to)\b", cleaned, re.I):
                applicability.append(f"Page {page}: {cleaned}")
    applicability_text = "\n".join(applicability[:12])
    if len(applicability_text) > 8192:
        applicability_text = applicability_text[:8160] + " [truncated]"
    return {
        "issuance_date": _labeled_date(joined, "Issued") or _labeled_date(joined, "Date"),
        "effective_date": _labeled_date(joined, "Effective"),
        "expiration_date": _labeled_date(joined, "Expiration") or _labeled_date(joined, "Expires"),
        "applicability_text": applicability_text or None,
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
            return "", "encrypted", ["The official PDF is encrypted and could not be extracted."], {}, 0, 0
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
    extracted = 0
    for number in range(page_start, end + 1):
        try:
            page = reader.pages[number - 1]
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_PDF_PAGE_STREAM_BYTES:
                raise RuntimeError("decoded page content exceeds the parser limit")
            text = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"Page {number} extraction failed: {type(exc).__name__}.")
            text = ""
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
    elif empty or any("parser limit" in warning for warning in warnings):
        status = "partial"
        warnings.append(f"{empty} selected page(s) contained no extractable text.")
    else:
        status = "complete"
    numbered = "\n\n".join(f"[Page {page}]\n{text}" for page, text in pages)
    return numbered, status, warnings, _extract_document_fields(pages), total, end
