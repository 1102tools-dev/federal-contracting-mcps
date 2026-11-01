#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Reference assembler: eCFR answers rebuilt from the D1 rows, for the Worker to port.

assemble(db, title, key, date) returns exactly what ecfr_mcp._xml_text.parse()
returns for eCFR's XML answer at that node's scope (?section=, ?appendix=,
?subpart=, ?part=), reading only the rows scripts/load_ecfr.py writes
(deploy/ecfr/schema.sql; PORT_PROGRESS.md "Content format"). A section or
appendix is one unit; a part or subpart is the container shape: its own text,
one list per grouping level, section_count and sections. Nodes with flags & 1
can't be rebuilt; the Worker forwards them. The strings below are copies of
_xml_text's; `verify` checks they still match.

verify: assemble() against parse() over a recording, for every part, every
section and appendix (its DIV sliced from the part answer) and every subpart,
skipping and counting flagged nodes.

    servers/ecfr-mcp/.venv/bin/python -I deploy/ecfr/scripts/assemble_reference.py verify \
        --db deploy/ecfr/.snapshot.nosync/ecfr-48.sqlite \
        --rec deploy/ecfr/.snapshot.nosync/rec-2026-10-29 [--titles 48] [--probe deploy/ecfr/.snapshot.nosync/probe]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ECFR_SITE = "https://www.ecfr.gov"
UNIT_KEYS = ("heading", "paragraphs", "citations", "tables", "notes", "examples",
             "images", "pending_amendments", "editorial_notes")
PLURALS = {
    "title": "titles", "subtitle": "subtitles", "chapter": "chapters",
    "subchapter": "subchapters", "part": "parts", "subpart": "subparts",
    "subject_group": "subject_groups", "division": "divisions",
}
TABLE_NOTE = (
    "Tables are in 'tables'. Each has 'table' (its number, matching the "
    "[See table N] marker in the paragraphs), an optional 'caption', and "
    "'rows' (lists of cell strings). [fn N] marks a footnote reference."
)
PENDING_ONE = (
    "eCFR links an amendment to this text that was published in the "
    "Federal Register and may not be in effect yet (see "
    "pending_amendments). Check that document before relying on "
    "this text."
)


def load(db: sqlite3.Connection, title: int, key: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """A node row and its parsed content (chunks joined in seq order)."""
    row = db.execute("SELECT content, chunks, meta, flags FROM nodes WHERE title = ? AND key = ?", (title, key)).fetchone()
    if row is None:
        raise LookupError(f"title {title} has no node {key!r}")
    content, chunks, meta, flags = row
    if chunks:
        content = "".join(t for (t,) in db.execute(
            "SELECT text FROM chunks WHERE title = ? AND key = ? ORDER BY seq", (title, key)))
    return {"meta": meta, "flags": flags}, (json.loads(content) if content is not None else None)


def unit_dict(unit: dict[str, Any], always: tuple[str, ...]) -> dict[str, Any]:
    """_Unit.as_dict(always=...) from the stored as_dict(): a key appears when it has
    a value or is in always (heading "" and lists [] when empty), in this order."""
    out: dict[str, Any] = {}
    for key in UNIT_KEYS:
        if key in unit:
            out[key] = unit[key]
        elif key in always:
            out[key] = "" if key == "heading" else []
    for key in ("authority", "source"):
        if key in unit:
            out[key] = unit[key]
    return out


def metadata(meta: dict[str, Any] | None, date: str | None) -> dict[str, Any] | None:
    """_xml_text._metadata: the date in for eCFR's placeholder, then url."""
    if meta is None:
        return None
    meta = dict(meta)
    path = meta.get("path")
    if isinstance(path, str) and "_SUBSTITUTE_DATE_" in path:
        meta["path"] = path.replace("/on/_SUBSTITUTE_DATE_/", f"/on/{date}/" if date else "/current/")
    if isinstance(meta.get("path"), str) and meta["path"].startswith("/"):
        meta["url"] = ECFR_SITE + meta["path"]
    return meta


def warnings(units: list[dict[str, Any]]) -> list[str]:
    """_xml_text._warnings from the stored counts (units in parse order: the top, then
    every DIV depth-first in document order)."""
    out: list[str] = []
    pending = [u for u in units if u["pending"]]
    if pending:
        if len(units) == 1:
            out.append(PENDING_ONE)
        else:
            names = ", ".join(u["n"] or "?" for u in pending[:10])
            more = f" and {len(pending) - 10} more" if len(pending) > 10 else ""
            out.append(
                f"{len(pending)} section(s) have a published amendment that may "
                f"not be in effect yet ({names}{more}; see each section's "
                f"pending_amendments)."
            )
    images = sum(u["images"] for u in units)
    if images:
        out.append(
            f"This text includes {images} image(s), such as formulas, forms or "
            f"figures, that can't be shown as text; each is marked [Image: <link>] "
            f"where it appears."
        )
    unparsed = sum(u["unparsed"] for u in units)
    if unparsed:
        out.append(
            f"{unparsed} table(s) contained content that could not be parsed "
            f"into rows and were omitted. Use raw_xml=True to inspect."
        )
    return out


def assemble(db: sqlite3.Connection, title: int, key: str, date: str | None) -> dict[str, Any]:
    """parse(eCFR's answer for this node, date), from the rows."""
    row, content = load(db, title, key)
    if content is None:
        raise LookupError(f"title {title} node {key!r} has no content")
    units = [content]
    if content["kind"] in ("section", "appendix"):
        result = unit_dict(content["unit"], ("heading", "paragraphs", "citations"))
    else:
        sections: list[dict[str, Any]] = []
        groups: dict[str, list[dict[str, Any]]] = {}

        def visit(group: dict[str, Any], context: dict[str, str]) -> None:
            for child_key in group["divs"]:
                child = load(db, title, child_key)[1]
                units.append(child)
                if child["kind"] in ("section", "appendix"):
                    entry: dict[str, Any] = {child["kind"]: child["n"]}
                    entry.update(context)
                    entry.update(unit_dict(child["unit"], ("heading", "paragraphs")))
                    sections.append(entry)
                    continue
                kind = child["kind"]
                record: dict[str, Any] = {} if kind == "subject_group" else {kind: child["n"]}
                record.update(context)
                groups.setdefault(kind, []).append(record)
                inner = dict(context)
                inner[kind] = child["label"] if kind == "subject_group" else child["n"]
                visit(child, inner)
                record.update(unit_dict(child["unit"], ("heading",)))

        visit(content, {})
        result = unit_dict(content["unit"], ("heading",))
        for kind, records in groups.items():
            result[PLURALS[kind]] = records
        result["section_count"] = len(sections)
        result["sections"] = sections
    meta = metadata(json.loads(row["meta"]) if row["meta"] else None, date)
    if meta:
        result["hierarchy_metadata"] = [meta]
    if result.get("tables") or any(s.get("tables") for s in result.get("sections", [])):
        result["table_note"] = TABLE_NOTE
    notes = warnings(units)
    if notes:
        result["warning"] = " ".join(notes)
    return result


# ---------- verification against parse() ----------

def first_difference(a: Any, b: Any, path: str = "") -> str:
    """Where two JSON values first differ (key order counts), for reports."""
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            return f"{path or '/'}: keys {list(a)[:12]} vs {list(b)[:12]}"
        for k in a:
            if json.dumps(a[k], ensure_ascii=False) != json.dumps(b[k], ensure_ascii=False):
                return first_difference(a[k], b[k], f"{path}/{k}")
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} vs {len(b)} items"
        for i, (x, y) in enumerate(zip(a, b)):
            if json.dumps(x, ensure_ascii=False) != json.dumps(y, ensure_ascii=False):
                return first_difference(x, y, f"{path}/{i}")
    return f"{path}: {json.dumps(a, ensure_ascii=False)[:160]} vs {json.dumps(b, ensure_ascii=False)[:160]}"


def verify(db_path: Path, rec: Path, titles: list[int] | None = None, probe: Path | None = None,
           log=print) -> dict[str, Any]:
    root_dir = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root_dir / "servers/ecfr-mcp/src"))
    sys.path.insert(0, str(root_dir / "scripts"))
    import xml.etree.ElementTree as ET

    import load_ecfr
    from ecfr_mcp import _xml_text

    assert TABLE_NOTE == _xml_text.TABLE_NOTE and ECFR_SITE == _xml_text.ECFR_SITE and PLURALS == _xml_text._PLURALS
    db = sqlite3.connect(db_path)
    recording = load_ecfr.Recording(rec)
    report_path = Path(str(db_path) + ".flags.json")
    reasons: dict[str, dict[str, str]] = json.loads(report_path.read_text()).get("flagged", {}) if report_path.exists() else {}
    counts: dict[str, Counter[str]] = {s: Counter() for s in ("part", "section", "subpart")}
    mismatches: list[str] = []

    def same(expected: dict[str, Any], got: dict[str, Any]) -> bool:
        return json.dumps(expected, ensure_ascii=False) == json.dumps(got, ensure_ascii=False)

    def check(scope: str, n: int, key: str, flags: int, xml: str, date: str) -> None:
        if flags & 1:
            counts[scope]["flagged: " + reasons.get(str(n), {}).get(key, "?")] += 1
            return
        expected = _xml_text.parse(xml, date)
        try:
            got = assemble(db, n, key, date)
        except LookupError as exc:
            got = {"error": str(exc)}
        if same(expected, got):
            counts[scope]["match"] += 1
        else:
            counts[scope]["MISMATCH"] += 1
            if len(mismatches) < 40:
                mismatches.append(f"{n} {key}: {first_difference(expected, got)}")

    def slice_of(element: Any) -> str:
        tail, element.tail = element.tail, None
        try:
            return ET.tostring(element, encoding="unicode")
        finally:
            element.tail = tail

    rows = db.execute("SELECT number, json FROM titles ORDER BY number").fetchall()
    for number, text in rows:
        row = json.loads(text)
        if (titles and number not in titles) or row.get("reserved"):
            continue
        date = row["up_to_date_as_of"]
        started = time.monotonic()
        nodes = {k: (t, i, f) for k, t, i, f in db.execute(
            "SELECT key, type, identifier, flags FROM nodes WHERE title = ?", (number,))}
        tree = load_ecfr.walk(json.loads((rec / "structure" / f"title-{number}.json").read_text()))
        fetch = recording.fetch(number)
        for key, unit_keys in load_ecfr.by_unit(tree).items():
            node = tree[key]
            got = fetch(node)
            if got is None or got[0] != 200:
                counts["part"]["no XML recorded"] += 1
                continue
            xml = got[1]
            check("section" if node.type == "appendix" else "part", number, key, nodes[key][2], xml, date)
            if node.type == "appendix":
                continue
            root = _xml_text._parse_root(xml)
            if root is None:
                continue
            # Every section, appendix and subpart DIV in the answer, matched to its node
            # by type and identifier within this part.
            by_ident: dict[tuple[str, str], list[str]] = {}
            for k in unit_keys[1:]:
                by_ident.setdefault((tree[k].type, tree[k].identifier or ""), []).append(k)
            for element in root.iter():
                if element is root:
                    continue
                tag = element.tag.upper() if isinstance(element.tag, str) else ""
                if tag in ("DIV8", "DIV9"):
                    scope, kind = "section", ("appendix" if tag == "DIV9" else "section")
                elif tag == "DIV6" and (element.get("TYPE") or "").upper() == "SUBPART":
                    scope, kind = "subpart", "subpart"
                else:
                    continue
                matches = by_ident.get((kind, element.get("N") or ""), [])
                if len(matches) != 1:
                    counts[scope][f"skipped: {len(matches)} nodes with this identifier"] += 1
                    continue
                check(scope, number, matches[0], nodes[matches[0]][2], slice_of(element), date)
        log(f"title {number}: checked in {time.monotonic() - started:.0f}s "
            f"(parts {dict(counts['part'])}, sections {dict(counts['section'])}, subparts {dict(counts['subpart'])})")

    probes: Counter[str] = Counter()
    if probe and (48 in (titles or [48])):
        date = json.loads(db.execute("SELECT json FROM titles WHERE number = 48").fetchone()[0])["up_to_date_as_of"]
        for name, key in (("s15305.xml", "chapter:1/subchapter:C/part:15/subpart:15.3/section:15.305"),
                          ("sp153.xml", "chapter:1/subchapter:C/part:15/subpart:15.3"),
                          ("p15.xml", "chapter:1/subchapter:C/part:15")):
            if (probe / name).exists():
                expected = _xml_text.parse((probe / name).read_bytes(), date)
                got = assemble(db, 48, key, date)
                probes["match" if same(expected, got) else "MISMATCH"] += 1
                if not same(expected, got):
                    mismatches.append(f"probe {name}: {first_difference(expected, got)}")
    return {"parts": dict(counts["part"]), "sections_and_appendices": dict(counts["section"]),
            "subparts": dict(counts["subpart"]), "probe_answers": dict(probes), "mismatches": mismatches}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="assemble() vs parse() over a recording")
    v.add_argument("--db", required=True, type=Path)
    v.add_argument("--rec", required=True, type=Path)
    v.add_argument("--titles", type=int, nargs="*")
    v.add_argument("--probe", type=Path)
    v.add_argument("--json", type=Path, help="also write the report here")
    s = sub.add_parser("show", help="print one node's assembled answer")
    s.add_argument("--db", required=True, type=Path)
    s.add_argument("--title", required=True, type=int)
    s.add_argument("--key", required=True)
    s.add_argument("--date")
    args = parser.parse_args(argv)
    if args.command == "show":
        print(json.dumps(assemble(sqlite3.connect(args.db), args.title, args.key, args.date), indent=2, ensure_ascii=False))
        return 0
    report = verify(args.db, args.rec, args.titles, args.probe, log=lambda m: print(m, file=sys.stderr, flush=True))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    bad = sum(c.get("MISMATCH", 0) for c in (report["parts"], report["sections_and_appendices"],
                                              report["subparts"], report["probe_answers"]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
