# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Turn eCFR's XML into clean text, one object per section.

eCFR's versioner sends well-formed XML that uses about 60 element names:
paragraphs (P, FP, FP-1, FP-DASH, P-2, LI, ...), clause bodies (EXTRACT),
notes, worked examples, HTML-style tables with captions, footnote marks,
images, editorial notes and pending-amendment links. This walks the real
element tree. An element it doesn't know is read as text, so nothing is
dropped silently: every text node in the XML lands in the output once, in
document order (tests/test_real_xml_fixtures.py checks that on saved eCFR
responses).

Output for a single section or appendix: heading, paragraphs and
citations, plus tables, notes, examples, images, pending_amendments,
editorial_notes and hierarchy_metadata when present. Tables, notes and
examples are numbered, and a marker such as "[See table 1: ...]" sits in
the paragraph list where each one appears. A subpart, part or larger
request returns the same object per section under 'sections'.

paginate() splits an answer too large for one tool reply into pages at
paragraph, row and section boundaries.
"""

from __future__ import annotations

from ._errors import UserInputError

import html
import json
import re
import xml.etree.ElementTree as ET
from html.entities import name2codepoint
from typing import Any

ECFR_SITE = "https://www.ecfr.gov"

# Structure levels. DIV8 is a section and DIV9 an appendix; the rest group them.
_SECTION_DIVS = {"DIV8", "DIV9"}
_GROUP_DIVS = {"DIV1", "DIV2", "DIV3", "DIV4", "DIV5", "DIV6", "DIV7"}
# eCFR's TYPE attribute for a grouping level -> the key it is listed under.
_GROUP_KEYS = {
    "TITLE": "title", "SUBTITLE": "subtitle", "CHAPTER": "chapter",
    "SUBCHAP": "subchapter", "PART": "part", "SUBPART": "subpart",
    "SUBJGRP": "subject_group",
}
# Wrappers that hold blocks but no text of their own.
_CONTAINERS = {"EXTRACT", "SCOL2", "SCOL3", "DIV", "FTNT", "MATH", "GPH", "ECFR"}
_TABLES = {"TABLE", "GPOTABLE"}
_PLURALS = {
    "title": "titles", "subtitle": "subtitles", "chapter": "chapters",
    "subchapter": "subchapters", "part": "parts", "subpart": "subparts",
    "subject_group": "subject_groups", "division": "divisions",
}
_ITALIC = {"I", "E", "EM"}
# A superscript that is a footnote mark: digits or asterisks. Anything else
# ("1<SU>st</SU>") is ordinary text.
_FOOTNOTE_MARK = re.compile(r"^\s*(\d{1,3}|\*{1,3})\s*$")
_WS = re.compile(r"\s+")
_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)

TABLE_NOTE = (
    "Tables are in 'tables'. Each has 'table' (its number, matching the "
    "[See table N] marker in the paragraphs), an optional 'caption', and "
    "'rows' (lists of cell strings). [fn N] marks a footnote reference."
)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _tag(e: ET.Element) -> str:
    return e.tag.upper() if isinstance(e.tag, str) else ""


def _image_url(e: ET.Element) -> str:
    src = (e.get("src") or e.get("SRC") or "").strip()
    if src.startswith("/"):
        return ECFR_SITE + src
    return src or "(no source given)"


class _Unit:
    """Text of one section, appendix or grouping level, in document order."""

    def __init__(self, element: ET.Element):
        self.element = element
        self.heading = ""
        self.paragraphs: list[str] = []
        self.tables: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.examples: list[dict[str, Any]] = []
        self.images: list[str] = []
        self.citations: list[str] = []
        self.editorial_notes: list[str] = []
        self.pending_amendments: list[str] = []
        self.authority: list[str] = []
        self.source: list[str] = []
        self.unparsed_tables = 0
        self.first_head = next((c for c in element if _tag(c) == "HEAD"), None)

    # -- inline text ---------------------------------------------------------

    def inline(self, e: ET.Element) -> str:
        parts: list[str] = []
        self._inline_children(e, parts)
        return _clean("".join(parts))

    def _inline_children(self, e: ET.Element, parts: list[str]) -> None:
        if e.text:
            parts.append(e.text)
        children = list(e)
        index = 0
        while index < len(children):
            child = children[index]
            # Scientific notation can split the sign and digits into two
            # superscripts. Keep that exponent numeric rather than treating
            # its digits as a footnote (40 CFR 141.61's dioxin MCL).
            if (
                _tag(child) in ("SUP", "SU")
                and (child.text or "").strip() in ("−", "-", "+")
                and not list(child)
                and not (child.tail or "").strip()
                and re.search(r"[×x*]\s*10\s*$", "".join(parts))
                and index + 1 < len(children)
            ):
                digits = children[index + 1]
                if (
                    _tag(digits) in ("SUP", "SU")
                    and not list(digits)
                    and re.fullmatch(r"\d+", (digits.text or "").strip())
                ):
                    parts.append("^" + (child.text or "").strip() + (digits.text or "").strip())
                    if digits.tail:
                        parts.append(digits.tail)
                    index += 2
                    continue
            self._inline_element(child, parts)
            if child.tail:
                parts.append(child.tail)
            index += 1

    def _inline_element(self, e: ET.Element, parts: list[str]) -> None:
        tag = _tag(e)
        if tag in _ITALIC:
            inner: list[str] = []
            self._inline_children(e, inner)
            text = "".join(inner)
            core = text.strip()
            if core:
                lead = text[: len(text) - len(text.lstrip())]
                trail = text[len(text.rstrip()):]
                parts.append(f"{lead}*{core}*{trail}")
            else:
                parts.append(text)
        elif tag in ("SUP", "SU"):
            inner = []
            self._inline_children(e, inner)
            text = "".join(inner)
            mark = _FOOTNOTE_MARK.match(text)
            parts.append(f" [fn {mark.group(1)}] " if mark else text)
        elif tag == "FTREF":
            parts.append(" [fn] ")
        elif tag == "BR":
            parts.append(" ")
        elif tag == "IMG":
            url = _image_url(e)
            self.images.append(url)
            parts.append(f" [Image: {url}] ")
        elif tag == "FR":
            # A fraction after a whole number: "1<FR>1/2</FR>" reads "1 1/2".
            inner = []
            self._inline_children(e, inner)
            if parts and parts[-1][-1:].isdigit():
                parts.append(" ")
            parts.append("".join(inner))
        else:
            self._inline_children(e, parts)

    # -- blocks --------------------------------------------------------------

    def blocks(self, e: ET.Element, out: list[str], on_div=None) -> None:
        """Render e's children as blocks into out, in document order."""
        if e.text and e.text.strip():
            out.append(_clean(e.text))
        for child in e:
            self.block(child, out, on_div)
            if child.tail and child.tail.strip():
                out.append(_clean(child.tail))

    def block(self, e: ET.Element, out: list[str], on_div=None) -> None:
        tag = _tag(e)
        if not tag:
            return
        if tag in _SECTION_DIVS or tag in _GROUP_DIVS:
            if on_div is not None:
                on_div(e)
            else:
                self.blocks(e, out, on_div)
        elif tag == "HEAD" and e is self.first_head:
            self.heading = self.inline(e)
        elif tag == "CITA":
            self._add(self.citations, self.inline(e))
        elif tag == "XREF":
            self._add(self.pending_amendments, self.inline(e))
        elif tag == "EDNOTE":
            self._add(self.editorial_notes, self._joined(e))
        elif tag == "AUTH":
            self._add(self.authority, self._joined(e))
        elif tag == "SOURCE":
            self._add(self.source, self._joined(e))
        elif tag == "NOTE":
            self._labeled(e, out, self.notes, "note")
        elif tag == "EXAMPLE":
            self._labeled(e, out, self.examples, "example")
        elif tag in _TABLES:
            self._table(e, out)
        elif tag == "IMG":
            url = _image_url(e)
            self.images.append(url)
            out.append(f"[Image: {url}]")
        elif tag == "STARS":
            out.append("* * * * *")
        elif tag in _CONTAINERS:
            self.blocks(e, out, on_div)
        else:
            # P, FP, FP-1, FP-DASH, P-2, HD1-HD3, LI, PSPACE, FRP, SECHD,
            # PARTHD, APPRO, SECAUTH, HED and anything new: one paragraph.
            self._add(out, self.inline(e))

    @staticmethod
    def _add(target: list[str], text: str) -> None:
        if text:
            target.append(text)

    def _joined(self, e: ET.Element) -> str:
        """A label and its text as one line: 'Editorial Note: For ...'."""
        pieces: list[str] = []
        self.blocks(e, pieces)
        return _clean(" ".join(pieces))

    def _labeled(self, e: ET.Element, out: list[str], target: list[dict[str, Any]], kind: str) -> None:
        number = len(target) + 1
        entry: dict[str, Any] = {kind: number}
        target.append(entry)
        label = ""
        body: list[str] = []
        if e.text and e.text.strip():
            body.append(_clean(e.text))
        for child in e:
            if not label and not body and _tag(child) == "HED":
                label = self.inline(child)
            else:
                self.block(child, body)
            if child.tail and child.tail.strip():
                body.append(_clean(child.tail))
        if label:
            entry["label"] = label
        entry["paragraphs"] = body
        out.append(f"[See {kind} {number}: {label}]" if label else f"[See {kind} {number}]")

    def _table(self, e: ET.Element, out: list[str]) -> None:
        caption: list[str] = []
        headnotes: list[str] = []
        rows: list[list[str]] = []
        notes: list[str] = []
        for node in e.iter():
            tag = _tag(node)
            if tag == "CAPTION":
                for p in node:
                    text = self.inline(p)
                    if not text:
                        continue
                    (headnotes if (p.get("class") or "").lower() == "headnote" else caption).append(text)
                if node.text and node.text.strip():
                    caption.insert(0, _clean(node.text))
            elif tag == "TTITLE":
                self._add(caption, self.inline(node))
            elif tag in ("TR", "ROW", "BOXHD"):
                cell_tags = ("CHED",) if tag == "BOXHD" else ("TD", "TH", "ENT")
                cells = [self.inline(c) for c in node if _tag(c) in cell_tags]
                if any(cells):
                    rows.append(cells)
            elif tag in ("TNOTE", "TDESC"):
                self._add(notes, self.inline(node))
        if not rows:
            if self.inline(e):
                self.unparsed_tables += 1
            return
        number = len(self.tables) + 1
        table: dict[str, Any] = {"table": number}
        if caption:
            table["caption"] = " ".join(caption)
        if headnotes:
            table["headnote"] = " ".join(headnotes)
        table["rows"] = rows
        if notes:
            table["notes"] = notes
        self.tables.append(table)
        out.append(f"[See table {number}: {table['caption']}]" if caption else f"[See table {number}]")

    # -- output --------------------------------------------------------------

    def render(self) -> None:
        self.blocks(self.element, self.paragraphs)

    def as_dict(self, *, always: tuple[str, ...] = ()) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in ("heading", "paragraphs", "citations", "tables", "notes", "examples",
                    "images", "pending_amendments", "editorial_notes"):
            value = getattr(self, key)
            if value or key in always:
                result[key] = value
        if self.authority:
            result["authority"] = " ".join(self.authority)
        if self.source:
            result["source"] = " ".join(self.source)
        return result


def _metadata(e: ET.Element, date: str | None) -> dict[str, Any] | None:
    raw = e.get("hierarchy_metadata")
    if not raw:
        return None
    for candidate in (raw, html.unescape(raw)):
        try:
            meta = json.loads(candidate)
            break
        except (ValueError, json.JSONDecodeError):
            continue
    else:
        return None
    if not isinstance(meta, dict):
        return None
    path = meta.get("path")
    if isinstance(path, str) and "_SUBSTITUTE_DATE_" in path:
        # eCFR leaves a placeholder where the date belongs.
        meta["path"] = path.replace("/on/_SUBSTITUTE_DATE_/", f"/on/{date}/" if date else "/current/")
    if isinstance(meta.get("path"), str) and meta["path"].startswith("/"):
        meta["url"] = ECFR_SITE + meta["path"]
    return meta


def _fix_entities(text: str) -> str:
    """Spell HTML named entities as numbers so the XML parser accepts them."""
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _XML_ENTITIES or name not in name2codepoint:
            return m.group(0)
        return f"&#{name2codepoint[name]};"
    return _ENTITY.sub(repl, text)


def _parse_root(text: str) -> ET.Element | None:
    attempts = [text, _fix_entities(text)]
    body = _DECL.sub("", text)
    # Test snippets and odd responses can be fragments with no single root.
    attempts.append(f"<ECFR>{_fix_entities(body)}</ECFR>")
    for attempt in attempts:
        try:
            root = ET.fromstring(attempt)
        except ET.ParseError:
            continue
        tag = _tag(root)
        if tag in _SECTION_DIVS or tag in _GROUP_DIVS or tag == "ECFR":
            return root
        # A lone element (<HEAD>, <CITA>, <TABLE>...) is content, not a container.
        wrapper = ET.Element("ECFR")
        wrapper.append(root)
        return wrapper
    return None


_FALLBACK_SPLIT = re.compile(r"<[^>]+>")


def _fallback(text: str) -> dict[str, Any]:
    """Malformed XML: keep every piece of text, and say the layout is lost."""
    pieces = [_clean(html.unescape(p)) for p in _FALLBACK_SPLIT.split(_DECL.sub("", text))]
    return {
        "heading": "",
        "paragraphs": [p for p in pieces if p],
        "citations": [],
        "warning": (
            "eCFR sent text this server could not read as XML, so paragraphs, "
            "headings and tables may be run together or split oddly. Use "
            "raw_xml=True to see exactly what eCFR sent."
        ),
    }


def parse(xml_content: Any, date: str | None = None) -> dict[str, Any]:
    """Parse eCFR XML into clean text. See the module docstring for the shape."""
    if xml_content is None:
        return {"heading": "", "paragraphs": [], "citations": []}
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8", errors="replace")
    if not isinstance(xml_content, str):
        xml_content = str(xml_content)
    if not xml_content.strip():
        return {"heading": "", "paragraphs": [], "citations": []}

    root = _parse_root(xml_content)
    if root is None:
        return _fallback(xml_content)

    sections = [d for d in root.iter() if _tag(d) in _SECTION_DIVS and d is not root]
    meta = _metadata(root, date)
    if not sections:
        unit = _Unit(root)
        unit.render()
        result = unit.as_dict(always=("heading", "paragraphs", "citations"))
        warnings = _warnings([unit])
    else:
        result, units = _parse_container(root)
        warnings = _warnings(units)
    if meta:
        result["hierarchy_metadata"] = [meta]
    if _has_tables(result):
        result["table_note"] = TABLE_NOTE
    if warnings:
        result["warning"] = " ".join(warnings)
    return result


def _parse_container(root: ET.Element) -> tuple[dict[str, Any], list[_Unit]]:
    """A subpart, part, chapter or title: one object per section."""
    units: list[_Unit] = []
    sections: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}

    def visit(div: ET.Element, context: dict[str, str], unit: _Unit) -> None:
        def on_div(child: ET.Element) -> None:
            if _tag(child) in _SECTION_DIVS:
                section = _Unit(child)
                section.render()
                units.append(section)
                key = "appendix" if _tag(child) == "DIV9" else "section"
                entry: dict[str, Any] = {key: child.get("N") or ""}
                entry.update(context)
                entry.update(section.as_dict(always=("heading", "paragraphs")))
                sections.append(entry)
                return
            # A grouping level: its sections are told which part/subpart
            # (or subject group heading) they sit in.
            group = _Unit(child)
            units.append(group)
            kind = _GROUP_KEYS.get((child.get("TYPE") or "").upper(), "division")
            record: dict[str, Any] = {} if kind == "subject_group" else {kind: child.get("N") or ""}
            record.update(context)
            groups.setdefault(kind, []).append(record)
            inner = dict(context)
            head = group.first_head
            label = group.inline(head) if head is not None else ""
            inner[kind] = label if kind == "subject_group" else (child.get("N") or "")
            visit(child, inner, group)
            record.update(group.as_dict(always=("heading",)))

        unit.blocks(div, unit.paragraphs, on_div)

    top = _Unit(root)
    units.append(top)
    visit(root, {}, top)
    result = top.as_dict(always=("heading",))
    for kind, records in groups.items():
        result[_PLURALS[kind]] = records
    result["section_count"] = len(sections)
    result["sections"] = sections
    return result, units


def _has_tables(result: dict[str, Any]) -> bool:
    if result.get("tables"):
        return True
    return any(s.get("tables") for s in result.get("sections", []))


def _warnings(units: list[_Unit]) -> list[str]:
    warnings: list[str] = []
    pending = [u for u in units if u.pending_amendments]
    if pending:
        if len(units) == 1:
            warnings.append(
                "eCFR links an amendment to this text that was published in the "
                "Federal Register and may not be in effect yet (see "
                "pending_amendments). Check that document before relying on "
                "this text."
            )
        else:
            names = ", ".join(u.element.get("N") or "?" for u in pending[:10])
            more = f" and {len(pending) - 10} more" if len(pending) > 10 else ""
            warnings.append(
                f"{len(pending)} section(s) have a published amendment that may "
                f"not be in effect yet ({names}{more}; see each section's "
                f"pending_amendments)."
            )
    images = sum(len(u.images) for u in units)
    if images:
        warnings.append(
            f"This text includes {images} image(s), such as formulas, forms or "
            f"figures, that can't be shown as text; each is marked [Image: <link>] "
            f"where it appears."
        )
    unparsed = sum(u.unparsed_tables for u in units)
    if unparsed:
        warnings.append(
            f"{unparsed} table(s) contained content that could not be parsed "
            f"into rows and were omitted. Use raw_xml=True to inspect."
        )
    return warnings


# ---------------------------------------------------------------------------
# Pages for answers too large for one tool reply
# ---------------------------------------------------------------------------

# Measured as sent: the MCP layer sends a tool's dict as JSON indented two
# spaces, which nearly doubles tables. About 16,000-20,000 tokens. Claude Code
# refuses tool output over 25,000 tokens (52.212-3 at 96,187 characters
# bounced), and other clients cut long output off without saying so.
PAGE_CHARS = 64_000

_MARKER = re.compile(r"^\[See (table|note|example) (\d+)(?::.*)?\]$")
# Kept with every piece of a split section, or only with its last piece.
_HEADER_KEYS = ("section", "appendix", "title", "subtitle", "chapter", "subchapter", "part",
                "subpart", "subject_group", "heading", "pending_amendments", "authority", "source")
_TRAILER_KEYS = ("citations", "images", "editorial_notes")
_CONTENT_KEYS = ("paragraphs", "tables", "notes", "examples")


def size_of(value: Any, depth: int = 0) -> int:
    """Characters value takes in the reply: JSON indented two spaces, as the
    MCP layer sends it, nested depth levels deep."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return len(text) + (text.count("\n") + 1) * 2 * depth


def _atoms(unit: dict[str, Any], limit: int) -> list[tuple[str, Any]]:
    """A unit's content in reading order, in pieces small enough to pack."""
    atoms: list[tuple[str, Any]] = [("start", None)]
    used: set[tuple[str, int]] = set()

    def place(kind: str, number: int) -> None:
        entry = next((x for x in unit.get(kind + "s", []) if x.get(kind) == number), None)
        if entry is None or (kind, number) in used:
            return
        used.add((kind, number))
        if kind == "table":
            atoms.extend(("tables", piece) for piece in _table_pieces(entry, limit))
            return
        atoms.append((kind + "s", entry))
        for p in entry.get("paragraphs", []):
            m = _MARKER.match(p)
            if m and m.group(1) == "table":
                place("table", int(m.group(2)))

    for p in unit.get("paragraphs", []):
        atoms.append(("paragraphs", p))
        m = _MARKER.match(p)
        if m:
            place(m.group(1), int(m.group(2)))
    for kind in ("table", "note", "example"):
        for entry in unit.get(kind + "s", []):
            place(kind, entry.get(kind))
    # Citations and editorial notes ride with the unit's last piece; count them there.
    trailer = {k: unit[k] for k in _TRAILER_KEYS if k in unit}
    atoms.append(("end", trailer or None))
    return atoms


def _table_pieces(table: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    if size_of(table) <= limit * 0.8:
        return [table]
    rows = table.get("rows", [])
    head = {k: v for k, v in table.items() if k not in ("rows", "notes")}
    pieces: list[dict[str, Any]] = []
    chunk: list[list[str]] = []
    chunk_size = 0
    budget = int(limit * 0.6)
    for row in rows:
        row_size = size_of(row, 6) + 1
        if chunk and chunk_size + row_size > budget:
            pieces.append({**head, "rows": chunk})
            chunk, chunk_size = [], 0
        chunk.append(row)
        chunk_size += row_size
    if chunk:
        pieces.append({**head, "rows": chunk})
    first = 1
    for i, piece in enumerate(pieces):
        if i:
            piece["continued"] = True
            piece["header_row"] = rows[0]
            piece["first_row"] = first
        first += len(piece["rows"])
    if table.get("notes"):
        pieces[-1]["notes"] = table["notes"]
    return pieces


_GROUP_LISTS = {plural: singular for singular, plural in _PLURALS.items()}


def _identity(record: dict[str, Any], singular: str) -> tuple[tuple[str, str], ...]:
    """Where a part/subpart/... record sits, in the same terms sections use."""
    ident = {k: v for k, v in record.items() if k in _PLURALS and k != "subject_group"}
    if singular == "subject_group":
        ident["subject_group"] = record.get("heading", "")
    return tuple(sorted(ident.items()))


class _Plan:
    """Where every piece of an oversized answer goes, worked out once."""

    def __init__(self, result: dict[str, Any], limit: int):
        self.total_size = size_of(result)
        self.multi = "sections" in result
        self.units = result["sections"] if self.multi else [result]
        # Grouping records (parts, subparts...) go on the pages whose sections
        # they hold, not on every page: a whole chapter has thousands.
        self.groups: list[tuple[str, tuple[tuple[str, str], ...], dict[str, Any]]] = []
        if self.multi:
            self.frame = {k: v for k, v in result.items() if k != "sections" and k not in _GROUP_LISTS}
            for plural, singular in _GROUP_LISTS.items():
                for record in result.get(plural, []):
                    self.groups.append((plural, _identity(record, singular), record))
        else:
            self.frame = {k: v for k, v in result.items()
                          if k not in _CONTENT_KEYS and k not in _HEADER_KEYS and k not in _TRAILER_KEYS}
        by_identity = {ident: i for i, (_, ident, _) in enumerate(self.groups)}
        self.unit_groups: list[list[int]] = []
        for unit in self.units:
            # Each level above the section, outermost first, is one record.
            chain: dict[str, Any] = {}
            wanted = []
            for level in _PLURALS:
                if level in unit:
                    chain[level] = unit[level]
                    found = by_identity.get(tuple(sorted(chain.items())))
                    if found is not None:
                        wanted.append(found)
            self.unit_groups.append(sorted(wanted))
        group_sizes = [size_of(record, 2) + 2 for _, _, record in self.groups]
        # A level with no sections of its own (a reserved subpart) goes on page 1.
        attached = {g for wanted in self.unit_groups for g in wanted}
        self.orphans = [g for g in range(len(self.groups)) if g not in attached]
        headers = [{k: u[k] for k in _HEADER_KEYS if k in u} for u in self.units]
        # Inside a page, an item sits two levels down (key, list); a section's
        # items sit two more down (sections list, section).
        depth = 4 if self.multi else 2
        header_sizes = [size_of(h, depth - 1) + 60 for h in headers]

        frame_size = size_of(self.frame) + 700  # room for the page note
        self.pages: list[list[tuple[int, str, Any]]] = []
        current: list[tuple[int, str, Any]] = []
        current_size = frame_size + sum(group_sizes[g] for g in self.orphans)
        open_unit = None
        on_page: set[int] = set()

        def opening_cost(index: int) -> int:
            return header_sizes[index] + sum(group_sizes[g] for g in self.unit_groups[index] if g not in on_page)

        for index, unit in enumerate(self.units):
            for kind, value in _atoms(unit, limit):
                body = size_of(value, depth) + 2 if value is not None else 0
                cost = body + (opening_cost(index) if index != open_unit else 0)
                if current and current_size + cost > limit:
                    self.pages.append(current)
                    current, current_size = [], frame_size
                    on_page = set()
                    cost = body + opening_cost(index)
                if index != open_unit or not current:
                    on_page.update(self.unit_groups[index])
                current.append((index, kind, value))
                current_size += cost
                open_unit = index
        if current:
            self.pages.append(current)
        self.first_page_of: dict[int, int] = {}
        self.last_page_of: dict[int, int] = {}
        for number, atoms in enumerate(self.pages, start=1):
            for index, _, _ in atoms:
                self.first_page_of.setdefault(index, number)
                self.last_page_of[index] = number

    def page(self, page: int, narrower: str) -> dict[str, Any]:
        total = len(self.pages)
        if page > total:
            raise UserInputError(f"page={page} does not exist; this answer has {total} pages.")
        pieces: list[dict[str, Any]] = []
        by_unit: dict[int, dict[str, Any]] = {}
        for index, kind, value in self.pages[page - 1]:
            piece = by_unit.get(index)
            if piece is None:
                unit = self.units[index]
                piece = {k: unit[k] for k in _HEADER_KEYS if k in unit}
                if self.first_page_of[index] < page:
                    piece["continued_from_previous_page"] = True
                piece["paragraphs"] = []
                by_unit[index] = piece
                pieces.append(piece)
            if kind not in ("start", "end"):
                piece.setdefault(kind, []).append(value)
        for index, piece in by_unit.items():
            if self.last_page_of[index] > page:
                piece["continues_on_next_page"] = True
            else:
                unit = self.units[index]
                piece.update({k: unit[k] for k in _TRAILER_KEYS if k in unit})

        out = dict(self.frame)
        if self.multi:
            wanted = {g for index in by_unit for g in self.unit_groups[index]}
            if page == 1:
                wanted.update(self.orphans)
            wanted = sorted(wanted)
            for g in wanted:
                plural, _, record = self.groups[g]
                out.setdefault(plural, []).append(record)
            out["sections"] = pieces
        else:
            out.update(pieces[0] if pieces else {})
        out["page"] = page
        out["total_pages"] = total
        out["page_note"] = (
            f"This answer is about {self.total_size:,} characters, too long to send at once, "
            f"so it comes in {total} pages. This is page {page} of {total}."
            + (f" Call again with page={page + 1} for the next part." if page < total else " This is the last page.")
            + (f" {narrower}" if narrower else "")
        )
        return out


def paginate(result: dict[str, Any], page: int, *, limit: int = PAGE_CHARS, narrower: str = "") -> dict[str, Any]:
    """Page `page` (1-based) of result, or result itself when it fits.

    Splits only between paragraphs, table rows, notes, examples and
    sections, and says on every page how many pages there are.
    """
    if size_of(result) <= limit:
        if page != 1:
            raise UserInputError(f"This answer fits on one page; page={page} does not exist. Use page=1.")
        return result
    return _Plan(result, limit).page(page, narrower)


def all_pages(result: dict[str, Any], *, limit: int = PAGE_CHARS, narrower: str = "") -> list[dict[str, Any]]:
    """Every page of result (one plan), for tests and offline checks."""
    if size_of(result) <= limit:
        return [result]
    plan = _Plan(result, limit)
    return [plan.page(n, narrower) for n in range(1, len(plan.pages) + 1)]
