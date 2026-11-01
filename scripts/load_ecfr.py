#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Keep a copy of the current eCFR in D1 for the hosted eCFR Worker.

record: download one date's eCFR (titles, agencies, every title's structure,
every part's XML as eCFR answers ?part=X) into a recording directory, one XML
request at a time with eCFR's own 3-second gap. Resumable: a rerun skips what
the manifest already holds.

    servers/ecfr-mcp/.venv/bin/python scripts/load_ecfr.py record \
        --date 2026-10-29 --out deploy/ecfr/.snapshot.nosync/rec-2026-10-29 [--titles 48 2]

build: turn a recording into the rows the Worker reads (deploy/ecfr/schema.sql).
Every structure node of every title, each part's XML parsed per DIV with the
ecfr-mcp package's own _xml_text (PORT_PROGRESS.md "Content format" and
"Flags"), each titles.json row and agencies.json. Only rows whose hash changed
are written, so rebuilding an unchanged copy writes nothing.

    ... load_ecfr.py build --rec deploy/ecfr/.snapshot.nosync/rec-2026-10-29 \
        --local deploy/ecfr/.snapshot.nosync/ecfr-48.sqlite --titles 48

refresh: hourly, change-only, from live eCFR. Skips while eCFR is importing. A
title whose latest_amended_on or latest_issue_date moved gets its structure at
the new date, and only the parts that changed (structure diff plus versions
issued since the stored issue date) are fetched again. A title whose only
change is up_to_date_as_of costs one row (plus meta version: every write ends
by moving it, so the Worker's answer cache never outlives a content change).

verify: the daily safety net. Re-downloads about 7 titles' whole-title XML in a
weekly rotation and compares each part's parsed text with the stored rows'
hashes. Only parts that differ are fetched again and rewritten.

Targets: --local PATH (a sqlite file with schema.sql) or --remote (the D1 HTTP
API with CLOUDFLARE_D1_TOKEN, CLOUDFLARE_ACCOUNT_ID, and the database id from
--database-id, ECFR_D1_DATABASE_ID or deploy/ecfr/wrangler.jsonc
env.production). Remote runs add up every result's meta.rows_written and stop
once a run passes --max-rows (default 200,000).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "deploy/ecfr"
SCHEMA = WORKER_DIR / "schema.sql"
sys.path.insert(0, str(ROOT / "servers/ecfr-mcp/src"))  # the package this script parses with

from ecfr_mcp import _xml_text  # noqa: E402
from ecfr_mcp._xml_text import _GROUP_KEYS, _SECTION_DIVS, _Unit, _tag  # noqa: E402

BASE = "https://www.ecfr.gov"
V = "/api/versioner/v1"
USER_AGENT = "ecfr-mcp-loader (+https://github.com/1102tools-dev/federal-contracting-mcps)"
XML_GAP = 3.0  # seconds after the previous XML request completes (docs/pacing.md)
JSON_GAP = 0.6
STATEMENT_BYTES = 90_000  # D1 allows 100 KB per SQL statement
REQUEST_BYTES = 900_000   # SQL per D1 HTTP API request
CONTENT_BYTES = 85_000    # content (or a doc piece) over this goes to chunks
PAGE_ROWS = 5_000         # stored rows read per query
MAX_ROWS = 200_000        # default --max-rows for remote runs
NODE_WRITES = 3           # D1 rows written per node row: the row, its primary-key index, nodes_identifier
VERIFY_GROUPS = 7         # the safety net sees every title once a week
DOC_AGENCIES = "agencies.json"


class Stop(Exception):
    """eCFR refused us (403) or kept failing; stop without guessing."""


class RowCap(Exception):
    """A run would pass --max-rows; stop before writing more."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def part_file(identifier: str) -> str:
    """A part identifier as a file name ('/' and '%' never meet the disk raw)."""
    return identifier.replace("%", "%25").replace("/", "%2F")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------- eCFR requests ----------

class Fetcher:
    """One eCFR request at a time: XML 3 s after the previous one completes, JSON 0.6 s apart."""

    def __init__(self, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        self.client = client or httpx.Client(base_url=BASE, headers={"User-Agent": USER_AGENT}, timeout=600.0)
        self.sleep = sleep
        self.last_xml_end = 0.0
        self.last_json_start = 0.0
        self.requests = 0

    def get(self, path: str, params: dict[str, str] | None, *, xml: bool) -> tuple[int, bytes, float]:
        """(status, body, seconds). 200 and 404 come back; 403 stops; anything else is retried."""
        status: int | None = None
        error = None
        for attempt in range(1, 6):
            if xml:
                wait = self.last_xml_end + XML_GAP - time.monotonic()
            else:
                wait = self.last_json_start + JSON_GAP - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            started = time.monotonic()
            self.last_json_start = started
            self.requests += 1
            try:
                r = self.client.get(path, params=params or {})
            except httpx.HTTPError as exc:
                status, body, error = None, b"", f"{type(exc).__name__}: {exc}"
            else:
                status, body, error = r.status_code, r.content, None
            finally:
                if xml:
                    self.last_xml_end = time.monotonic()
            if status == 403:
                raise Stop(f"403 from eCFR on {path} {params}; stopping")
            if status in (200, 404):
                return status, body, round(time.monotonic() - started, 2)
            pause = 60 * attempt if status == 429 else 10 * attempt
            print(f"  {path} {params or ''}: {status or error}; retry {attempt} in {pause}s", flush=True)
            self.sleep(pause)
        raise Stop(f"{path} {params} kept failing ({status or error})")

    def json(self, path: str, params: dict[str, str] | None = None) -> Any:
        status, body, _ = self.get(path, params, xml=False)
        if status != 200:
            raise Stop(f"{path} {params or ''} answered {status}")
        return json.loads(body)


class Recorder:
    def __init__(self, out: Path, date: str, fetcher: Fetcher | None = None):
        self.out = out
        self.date = date
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest_path = out / "manifest.jsonl"
        self.done: dict[str, dict[str, Any]] = {}
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.done[entry["key"]] = entry
        self.fetcher = fetcher or Fetcher()

    def fetch(self, key: str, path: str, params: dict[str, str] | None, dest: Path, *, xml: bool) -> dict[str, Any]:
        """One request, saved to dest and logged in the manifest. 404 is recorded, not retried.
        A part written from the whole-title XML (deploy/ecfr/scripts/derive_parts.py) is fetched for real."""
        if key in self.done and self.done[key].get("status") in (200, 404) and not self.done[key].get("derived"):
            return self.done[key]
        status, body, seconds = self.fetcher.get(path, params, xml=xml)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(dest)
        entry = {
            "key": key, "path": path, "params": params or {}, "file": str(dest.relative_to(self.out)),
            "status": status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "fetched_at": now(), "seconds": seconds,
        }
        with self.manifest_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        self.done[key] = entry
        return entry

    def run(self, titles: list[int] | None) -> None:
        self.fetch("titles", f"{V}/titles.json", None, self.out / "titles.json", xml=False)
        self.fetch("agencies", "/api/admin/v1/agencies.json", None, self.out / "agencies.json", xml=False)
        listed = json.loads((self.out / "titles.json").read_text())["titles"]
        numbers = [t["number"] for t in listed if not t.get("reserved")]
        if titles:
            numbers = [n for n in titles if n in numbers]
        for n in numbers:
            self.fetch(f"structure:{n}", f"{V}/structure/{self.date}/title-{n}.json", None,
                       self.out / "structure" / f"title-{n}.json", xml=False)
        for n in numbers:
            nodes = walk(json.loads((self.out / "structure" / f"title-{n}.json").read_text()))
            jobs = [(recording_key(n, node), xml_params(node), recording_file(n, node))
                    for key, node in nodes.items() if node.unit == key]
            todo = [j for j in jobs if j[0] not in self.done or self.done[j[0]].get("derived")]
            print(f"title {n}: {len(jobs)} requests, {len(todo)} to go", flush=True)
            for i, (key, params, rel) in enumerate(todo, 1):
                entry = self.fetch(key, f"{V}/full/{self.date}/title-{n}.xml", params, self.out / rel, xml=True)
                if i % 50 == 0 or entry["status"] != 200:
                    print(f"  {i}/{len(todo)} {key} {entry['status']} {entry['bytes']:,} B {entry['seconds']}s", flush=True)
        print("recording complete", flush=True)


# ---------- structure ----------

@dataclass
class Node:
    """One structure node. unit: the key of the request that carries its text
    (its part, or itself for an appendix outside any part); None above parts."""
    key: str
    type: str
    identifier: str | None
    raw: dict[str, Any]
    structure: str
    children: list[str] | None
    unit: str | None
    chapter: str | None

    @property
    def children_text(self) -> str | None:
        return None if self.children is None else dumps(self.children)


def escape(identifier: str) -> str:
    return identifier.replace("%", "%25").replace("/", "%2F")


def walk(tree: dict[str, Any]) -> dict[str, Node]:
    """Every node of a title's structure by key, in eCFR's order.

    A key is the path below the title, one "type:identifier" step per level
    ('/' and '%' escaped); a node with no identifier (hed1) is "type:#n", n its
    0-based position among its siblings. The title itself is ''.
    """
    nodes: dict[str, Node] = {}

    def visit(raw: dict[str, Any], key: str, unit: str | None, chapter: str | None) -> None:
        kind = raw.get("type")
        if kind == "chapter":
            chapter = raw.get("identifier")
        if kind == "part" or (kind == "appendix" and unit is None):
            unit = key
        kids = raw.get("children")
        keys = None
        if isinstance(kids, list):
            keys = []
            for i, child in enumerate(kids):
                ident = child.get("identifier")
                step = f"{child.get('type')}:#{i}" if ident is None else f"{child.get('type')}:{escape(str(ident))}"
                keys.append(f"{key}/{step}" if key else step)
        structure = dumps({k: (True if k == "children" and isinstance(v, list) else v) for k, v in raw.items()})
        ident = raw.get("identifier")
        nodes[key] = Node(key, kind, None if ident is None else str(ident), raw, structure, keys, unit, chapter)
        for child, child_key in zip(kids or [], keys or []):
            visit(child, child_key, unit, chapter)

    visit(tree, "", None, None)
    return nodes


def tree_from_rows(stored: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The structure tree back from stored rows (structure with children: true, children keys)."""
    def build(key: str) -> dict[str, Any]:
        row = stored[key]
        node = json.loads(row["structure"])
        if node.get("children") is True:
            node["children"] = [build(k) for k in json.loads(row["children"] or "[]")]
        return node
    return build("")


def xml_params(node: Node) -> dict[str, str]:
    """The ?part= or ?appendix= request for a fetch unit."""
    if node.type == "part":
        return {"part": node.identifier or ""}
    params = {"chapter": node.chapter} if node.chapter else {}
    params["appendix"] = node.identifier or ""
    return params


def recording_key(number: int, node: Node) -> str:
    return f"{node.type}:{number}:{node.identifier}"


def recording_file(number: int, node: Node) -> str:
    if node.type == "part":
        return f"parts/title-{number}/part-{part_file(node.identifier or '')}.xml"
    return f"appendices/title-{number}/{part_file(node.identifier or '')}.xml"


# ---------- parsed content ----------

class Div:
    """One XML DIV and its _Unit as _xml_text._parse_container renders it."""

    __slots__ = ("element", "unit", "kind", "label", "divs")

    def __init__(self, element: Any, unit: _Unit, kind: str, label: str | None = None):
        self.element = element
        self.unit = unit
        self.kind = kind
        self.label = label
        self.divs: list[Div] = []


def div_kind(element: Any) -> str:
    tag = _tag(element)
    if tag in _SECTION_DIVS:
        return "appendix" if tag == "DIV9" else "section"
    return _GROUP_KEYS.get((element.get("TYPE") or "").upper(), "division")


def capture(root: Any) -> Div:
    """_parse_container's walk over root, keeping each DIV's own _Unit.

    The same calls in the same order: a section or appendix is a fresh _Unit
    and render() (nested DIVs inlined); a grouping level is a fresh _Unit,
    inline(first HEAD) for its label, then blocks() with on_div for its child
    DIVs. A section or appendix root is rendered whole, as parse() does.
    """
    top = Div(root, _Unit(root), div_kind(root))
    if top.kind in ("section", "appendix"):
        top.unit.render()
        return top

    def visit(div: Div) -> None:
        def on_div(child: Any) -> None:
            if _tag(child) in _SECTION_DIVS:
                section = _Unit(child)
                section.render()
                div.divs.append(Div(child, section, div_kind(child)))
                return
            group = _Unit(child)
            kind = div_kind(child)
            head = group.first_head
            label = group.inline(head) if head is not None else ""
            sub = Div(child, group, kind, label)
            div.divs.append(sub)
            visit(sub)

        div.unit.blocks(div.element, div.unit.paragraphs, on_div)

    visit(top)
    return top


def raw_meta(element: Any) -> dict[str, Any] | None:
    """hierarchy_metadata read as _xml_text._metadata reads it, placeholder kept, no url."""
    raw = element.get("hierarchy_metadata")
    if not raw:
        return None
    for candidate in (raw, html.unescape(raw)):
        try:
            meta = json.loads(candidate)
            break
        except ValueError:
            continue
    else:
        return None
    return meta if isinstance(meta, dict) else None


def content_text(div: Div, keys: dict[int, str]) -> str:
    """nodes.content for one DIV (PORT_PROGRESS.md "Content format")."""
    unit = div.unit
    content: dict[str, Any] = {"n": div.element.get("N") or "", "kind": div.kind, "unit": unit.as_dict()}
    if div.kind == "subject_group":
        content["label"] = div.label
    if div.kind not in ("section", "appendix"):
        content["divs"] = [keys[id(d)] for d in div.divs if id(d) in keys]
    content["images"] = len(unit.images)
    content["pending"] = len(unit.pending_amendments)
    content["unparsed"] = unit.unparsed_tables
    return dumps(content)


def has_section_below(element: Any) -> bool:
    return any(_tag(e) in _SECTION_DIVS for e in element.iter() if e is not element)


@dataclass
class Row:
    key: str
    type: str
    identifier: str | None
    structure: str
    children: str | None
    content: str | None
    meta: str | None
    flags: int

    @property
    def hash(self) -> str:
        return row_hash(self.structure, self.children, self.content, self.meta, self.flags)


def row_hash(structure: str, children: str | None, content: str | None, meta: str | None, flags: int) -> str:
    return sha(json.dumps([structure, children, content, meta, flags], ensure_ascii=False))[:32]


def plain_row(node: Node, flags: int = 0) -> Row:
    return Row(node.key, node.type, node.identifier, node.structure, node.children_text, None, None, flags)


def by_unit(nodes: dict[str, Node]) -> dict[str, list[str]]:
    """Each fetch unit's node keys (the unit first), in structure order."""
    out: dict[str, list[str]] = defaultdict(list)
    for key, node in nodes.items():
        if node.unit:
            out[node.unit].append(key)
    return out


def unit_rows(nodes: dict[str, Node], unit_key: str, got: tuple[int, str] | None, root: Any = None,
              keys: list[str] | None = None) -> tuple[dict[str, Row], dict[str, str], dict[str, int]]:
    """Rows for every node in one fetch unit (a part, or an appendix outside parts).

    got is (status, xml text); root, when given, is the unit's element already
    parsed (the safety net slices it from the whole-title XML). keys: the unit's
    node keys (by_unit). Returns rows, {key: reason} for flagged nodes, and
    alignment counts.
    """
    unit = nodes[unit_key]
    if keys is None:
        keys = [k for k, n in nodes.items() if n.unit == unit_key]
    problems: dict[str, str] = {}
    counts: Counter[str] = Counter()
    if root is None:
        if got is None or got[0] != 200:
            reason = "not recorded" if got is None else f"eCFR answered {got[0]}"
            rows = {}
            for k in keys:
                if nodes[k].type != "hed1":
                    problems[k] = reason
                rows[k] = plain_row(nodes[k], 1 if k in problems else 0)
            return rows, problems, counts
        root = _xml_text._parse_root(got[1])
        if root is None:
            rows = {}
            for k in keys:
                if nodes[k].type != "hed1":
                    problems[k] = "XML eCFR sent could not be parsed"
                rows[k] = plain_row(nodes[k], 1 if k in problems else 0)
            return rows, problems, counts

    top = capture(root)
    if top.kind != unit.type or (top.element.get("N") or "") != (unit.identifier or ""):
        problems[unit_key] = f"XML root is {top.kind} {top.element.get('N')!r}"

    # Pair each XML DIV with the structure node of the same type and identifier,
    # preferring a child of the node its parent DIV paired with.
    free: dict[tuple[str, str], list[str]] = defaultdict(list)
    for k in keys:
        if k != unit_key and nodes[k].type != "hed1":
            free[(nodes[k].type, nodes[k].identifier or "")].append(k)
    paired: dict[int, str] = {id(top): unit_key}
    pairs: list[tuple[Div, str]] = [(top, unit_key)]

    def visit(div: Div, key: str | None, chain: list[str]) -> None:
        siblings = set(nodes[key].children or []) if key else set()
        for child in div.divs:
            candidates = free.get((child.kind, child.element.get("N") or ""))
            child_key = None
            if candidates:
                inside = [k for k in candidates if k in siblings]
                child_key = inside[0] if inside else candidates[0]
                candidates.remove(child_key)
                if not inside:
                    counts["nesting differs from structure"] += 1
            if child_key is None:
                counts["XML DIV with no structure node"] += 1
                for k in chain:
                    problems.setdefault(k, "XML DIV with no structure node")
            else:
                paired[id(child)] = child_key
                pairs.append((child, child_key))
            visit(child, child_key, chain + [child_key] if child_key else chain)

    visit(top, unit_key, [unit_key])
    for leftover in free.values():
        for k in leftover:
            problems[k] = "no XML DIV"
            counts["no XML DIV"] += 1

    rows: dict[str, Row] = {}
    for div, key in pairs:
        node = nodes[key]
        below = has_section_below(div.element)
        if div.kind in ("section", "appendix"):
            if below:
                problems.setdefault(key, "nested section DIVs")
        elif not below:
            problems.setdefault(key, "no section or appendix below")
        elif div is not top and div.unit.first_head is not None and any(
                _tag(e) == "IMG" for e in div.unit.first_head.iter()):
            # inline(HEAD) for the label counts its images twice in a parent's
            # answer, but not when this DIV is the root of its own answer.
            problems.setdefault(key, "image in heading")
        meta = raw_meta(div.element)
        rows[key] = Row(key, node.type, node.identifier, node.structure, node.children_text,
                        content_text(div, paired), None if meta is None else dumps(meta), 0)
    for k in keys:
        if k not in rows:
            rows[k] = plain_row(nodes[k])
    for k, row in rows.items():
        row.flags = 1 if k in problems else 0
    return rows, problems, counts


def title_rows(nodes: dict[str, Node], fetch: Callable[[Node], tuple[int, str] | None],
               units: set[str] | None = None, log: Callable[[str], None] | None = None,
               ) -> tuple[dict[str, Row], dict[str, str], Counter[str]]:
    """Rows for every node above the parts, plus every node in the fetch units
    asked for (all of them when units is None)."""
    rows: dict[str, Row] = {}
    problems: dict[str, str] = {}
    counts: Counter[str] = Counter()
    groups = by_unit(nodes)
    wanted = [k for k in groups if units is None or k in units]
    for key, node in nodes.items():
        if node.unit is None:
            # Nothing above a part has a DIV of its own in a part answer.
            if node.type in ("section", "subpart", "subject_group"):
                problems[key] = "outside any part"
            rows[key] = plain_row(node, 1 if key in problems else 0)
    for i, key in enumerate(wanted, 1):
        got = fetch(nodes[key])
        unit_rows_, unit_problems, unit_counts = unit_rows(nodes, key, got, keys=groups[key])
        rows.update(unit_rows_)
        problems.update(unit_problems)
        counts.update(unit_counts)
        if log and i % 200 == 0:
            log(f"  parsed {i}/{len(wanted)} parts")
    return rows, problems, counts


# ---------- D1 ----------

def quote(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if "\x00" in text:
        return "(" + " || char(0) || ".join(quote(part) for part in text.split("\x00")) + ")"
    return "'" + text.replace("'", "''") + "'"


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def upserts(table: str, columns: tuple[str, ...], key: tuple[str, ...], rows: list[list[Any]]) -> list[str]:
    """Multi-row upserts, each under the D1 statement limit. An existing row is
    updated in place (not deleted and re-inserted as INSERT OR REPLACE would)."""
    head = f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
    rest = [c for c in columns if c not in key]
    tail = f" ON CONFLICT ({', '.join(key)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in rest) + ";"
    fixed = size(head) + size(tail)
    statements, values, used = [], [], fixed
    for row in rows:
        value = "(" + ", ".join(quote(v) for v in row) + ")"
        length = size(value) + 2
        if length + fixed > STATEMENT_BYTES:
            raise ValueError(f"row too large for one statement in {table}")
        if values and used + length > STATEMENT_BYTES:
            statements.append(head + ", ".join(values) + tail)
            values, used = [], fixed
        values.append(value)
        used += length
    if values:
        statements.append(head + ", ".join(values) + tail)
    return statements


def split_text(text: str, limit: int | None = None) -> list[str]:
    """Pieces whose SQL literal stays under limit bytes (CONTENT_BYTES), cut between characters."""
    limit = limit or CONTENT_BYTES
    pieces, start = [], 0
    while start < len(text):
        n = min(limit, len(text) - start)
        while n > 1 and size(quote(text[start:start + n])) > limit:
            n = max(1, n * 9 // 10)
        pieces.append(text[start:start + n])
        start += n
    return pieces or [""]


NODE_COLUMNS = ("title", "key", "type", "identifier", "structure", "children", "content", "chunks", "meta", "flags", "hash")
NODE_KEY = ("title", "key")


class Target:
    """What every database target shares: the rows-written count and its cap."""

    target = "local"

    def __init__(self, max_rows: int | None = None):
        self.max_rows = max_rows
        self.rows_written = 0
        self.rows_read = 0

    def count(self, written: int) -> None:
        self.rows_written += written
        if self.max_rows is not None and self.rows_written > self.max_rows:
            raise RowCap(f"{self.rows_written:,} rows written passed --max-rows {self.max_rows:,}; stopping")

    def room(self, planned: int, what: str) -> None:
        if self.max_rows is not None and self.rows_written + planned > self.max_rows:
            raise RowCap(f"{what} would write about {planned:,} rows; with {self.rows_written:,} written this run "
                         f"that passes --max-rows {self.max_rows:,}. Nothing written for it.")


class LocalD1(Target):
    """A sqlite file with schema.sql applied, for wrangler dev, tests and parity runs."""

    def __init__(self, path: Path | str, max_rows: int | None = None):
        super().__init__(max_rows)
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text())

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.db.execute(sql, params)]
        self.rows_read += len(rows)
        return rows

    def execute(self, statements: list[str]) -> int:
        if not statements:
            return 0
        before = self.db.total_changes
        try:
            self.db.executescript("BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;")
        except sqlite3.Error:
            if self.db.in_transaction:
                self.db.rollback()
            raise
        written = self.db.total_changes - before
        self.count(written)
        return written


class RemoteD1(Target):
    """The D1 HTTP API /query endpoint (what wrangler d1 execute --remote uses).

    Every result's meta.rows_written is added up; a result without it stops the
    run, and so does passing max_rows. Statements are idempotent upserts and
    deletes, so a retried request after a lost answer does no harm.
    """

    target = "remote"

    def __init__(self, database_id: str, token: str, account_id: str, max_rows: int | None = MAX_ROWS,
                 post: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        super().__init__(max_rows)
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.token = token
        self.post = post or self._http
        self.sleep = sleep
        self.calls = 0

    def _http(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(4):
            request = urllib.request.Request(self.url, data=data, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "1102tools-ecfr-loader"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:1000].decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    self.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP API returned {exc.code}: {detail}") from None
            except urllib.error.URLError as exc:
                if attempt < 3:
                    self.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP API unreachable: {exc.reason}") from None
        raise AssertionError("unreachable")

    def _results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls += 1
        body = self.post(payload)
        if not body.get("success"):
            raise RuntimeError(f"D1 query failed: {json.dumps(body.get('errors'))[:1000]}")
        results = body.get("result")
        if not isinstance(results, list) or not results or any(
                not isinstance((r.get("meta") or {}).get("rows_written"), int) for r in results):
            raise RuntimeError("D1 write metrics unavailable (no meta.rows_written); stopping before any further writes")
        self.rows_read += sum(int((r.get("meta") or {}).get("rows_read") or 0) for r in results)
        self.count(sum(r["meta"]["rows_written"] for r in results))
        return results

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        return self._results({"sql": sql, "params": list(params)})[0].get("results") or []

    def execute(self, statements: list[str]) -> int:
        before = self.rows_written
        batch: list[str] = []
        used = 0
        for statement in statements:
            length = size(statement) + 1
            if length > STATEMENT_BYTES + 1:
                raise ValueError(f"statement of {length:,} bytes is over the D1 limit")
            if batch and used + length > REQUEST_BYTES:
                self._results({"sql": "\n".join(batch)})
                batch, used = [], 0
            batch.append(statement)
            used += length
        if batch:
            self._results({"sql": "\n".join(batch)})
        return self.rows_written - before


def wrangler_config() -> dict[str, Any]:
    return json.loads(re.sub(r"^\s*//.*$", "", (WORKER_DIR / "wrangler.jsonc").read_text(), flags=re.M))


def database_id(argument: str | None) -> str:
    value = argument or os.environ.get("ECFR_D1_DATABASE_ID")
    if not value:
        databases = wrangler_config().get("env", {}).get("production", {}).get("d1_databases") or []
        value = next((d.get("database_id") for d in databases if d.get("binding") == "DB"), None) or (
            databases[0].get("database_id") if databases else None)
    if not value or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
        raise SystemExit("Set --database-id or ECFR_D1_DATABASE_ID to the ecfr D1 database id "
                         "(or add it to deploy/ecfr/wrangler.jsonc env.production d1_databases).")
    return value


def ensure_schema(db: Target) -> None:
    """Remote: apply schema.sql once if the tables aren't there yet."""
    have = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"titles", "nodes", "chunks", "docs", "meta"} <= have:
        statements = [s.strip() + ";" for s in re.sub(r"--[^\n]*", "", SCHEMA.read_text()).split(";") if s.strip()]
        db.execute(statements)


# ---------- change-only writes ----------

class Writer:
    """Writes only rows whose hash differs from the stored one; the titles row goes last.

    Every write also sets meta 'version' to a new value as its last statement (after
    the titles row, so in the run's last request too). The Worker keys its answer
    cache to it, so no cached answer outlives a content change. Nothing to write,
    no new version.
    """

    def __init__(self, db: Target, log: Callable[[str], None] = print):
        self.db = db
        self.log = log

    def write(self, statements: list[str]) -> int:
        if not statements:
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        version = f"{stamp}-{sha(stamp + chr(10).join(statements))[:8]}"
        return self.db.execute(statements + upserts("meta", ("key", "value"), ("key",), [["version", version]]))

    def stored_nodes(self, title: int, columns: tuple[str, ...] = ("key", "chunks", "hash")) -> dict[str, dict[str, Any]]:
        stored: dict[str, dict[str, Any]] = {}
        last: str | None = None
        while True:
            where = "key >= ''" if last is None else "key > ?"
            params = [title] if last is None else [title, last]
            rows = self.db.query(f"SELECT {', '.join(columns)} FROM nodes WHERE title = ? AND {where} "
                                 f"ORDER BY key LIMIT {PAGE_ROWS}", params)
            for r in rows:
                stored[r["key"]] = r
            if len(rows) < PAGE_ROWS:
                return stored
            last = rows[-1]["key"]

    def stored_title(self, title: int) -> dict[str, Any] | None:
        rows = self.db.query("SELECT number, json, hash FROM titles WHERE number = ?", [title])
        return rows[0] if rows else None

    def node_statements(self, title: int, changed: list[Row], stored: dict[str, dict[str, Any]]) -> tuple[list[str], int]:
        """(statements, rows they write) for changed rows: plain rows packed into
        multi-row upserts, then each chunked row's chunks before its row, then trims."""
        plain: list[list[Any]] = []
        single: list[str] = []
        trims: list[str] = []
        planned = 0
        probe = upserts("nodes", NODE_COLUMNS, NODE_KEY, [[0] + [None] * 10])[0]
        overhead = size(probe) - size("(0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)")
        for row in changed:
            values = [title, row.key, row.type, row.identifier, row.structure, row.children,
                      row.content, 0, row.meta, row.flags, row.hash]

            def length() -> int:
                return overhead + size("(" + ", ".join(quote(v) for v in values) + ")")

            pieces: list[str] = []
            if row.content is not None and (size(quote(row.content)) > CONTENT_BYTES or length() > STATEMENT_BYTES):
                pieces = split_text(row.content)
                values[6], values[7] = None, len(pieces)
            appends: list[str] = []
            if length() > STATEMENT_BYTES:
                # Only a very long children list gets here (40 CFR 721 subpart E): insert
                # its first piece, then append the rest.
                parts = split_text(row.children or "", CONTENT_BYTES // 2)
                values[5] = parts[0]
                where = f" WHERE title = {title} AND key = {quote(row.key)};"
                appends = [f"UPDATE nodes SET children = children || {quote(p)}{where}" for p in parts[1:]]
            old_chunks = int((stored.get(row.key) or {}).get("chunks") or 0)
            if pieces or appends:
                for seq, piece in enumerate(pieces):
                    single.extend(upserts("chunks", ("title", "key", "seq", "text"), ("title", "key", "seq"),
                                          [[title, row.key, seq, piece]]))
                single.extend(upserts("nodes", NODE_COLUMNS, NODE_KEY, [values]))
                single.extend(appends)
                planned += len(pieces) * 2 + NODE_WRITES + len(appends)
            else:
                plain.append(values)
                planned += NODE_WRITES
            if old_chunks > len(pieces):
                trims.append(f"DELETE FROM chunks WHERE title = {title} AND key = {quote(row.key)} AND seq >= {len(pieces)};")
                planned += (old_chunks - len(pieces)) * 2
        return upserts("nodes", NODE_COLUMNS, NODE_KEY, plain) + single + trims, planned

    @staticmethod
    def delete_statements(title: int, removed: list[str], stored: dict[str, dict[str, Any]]) -> tuple[list[str], int]:
        statements: list[str] = []
        planned = 0
        for table, keys in (("nodes", removed), ("chunks", [k for k in removed if int(stored[k].get("chunks") or 0)])):
            batch: list[str] = []
            used = 0
            for key in keys:
                q = quote(key)
                if batch and used + size(q) + 2 > STATEMENT_BYTES - 200:
                    statements.append(f"DELETE FROM {table} WHERE title = {title} AND key IN ({', '.join(batch)});")
                    batch, used = [], 0
                batch.append(q)
                used += size(q) + 2
            if batch:
                statements.append(f"DELETE FROM {table} WHERE title = {title} AND key IN ({', '.join(batch)});")
            planned += sum(NODE_WRITES if table == "nodes" else 2 * int(stored[k].get("chunks") or 0) for k in keys)
        return statements, planned

    def sync_title(self, title: int, rows: dict[str, Row], keep: set[str] | None,
                   stored: dict[str, dict[str, Any]] | None, title_json: str | None) -> dict[str, Any]:
        """Write rows whose hash changed, delete stored nodes not in keep (None: delete
        nothing), then the titles row when title_json differs from the stored one."""
        if stored is None:
            stored = self.stored_nodes(title)
        changed = [r for k, r in rows.items() if (stored.get(k) or {}).get("hash") != r.hash]
        removed = sorted(k for k in stored if k not in keep) if keep is not None else []
        statements, planned = self.node_statements(title, changed, stored)
        deletes, planned_deletes = self.delete_statements(title, removed, stored)
        statements += deletes
        planned += planned_deletes
        title_changed = False
        if title_json is not None:
            old = self.stored_title(title)
            if old is None or old["hash"] != sha(title_json):
                statements += upserts("titles", ("number", "json", "hash"), ("number",), [[title, title_json, sha(title_json)]])
                planned += 1
                title_changed = True
        if statements:
            planned += 1  # meta version
        self.db.room(planned, f"Title {title}")
        written = self.write(statements)
        return {"title": title, "changed": len(changed), "deleted": len(removed), "title_row": title_changed,
                "statements": len(statements), "rows_written": written}

    def sync_doc(self, name: str, text: str) -> int:
        """A whole document in pieces; rewritten only when its hash changes."""
        digest = sha(text)
        stored = self.db.query("SELECT value FROM meta WHERE key = ?", [f"docs:{name}"])
        if stored and stored[0]["value"] == digest:
            return 0
        pieces = split_text(text)
        statements: list[str] = []
        for seq, piece in enumerate(pieces):
            statements += upserts("docs", ("name", "seq", "text"), ("name", "seq"), [[name, seq, piece]])
        statements.append(f"DELETE FROM docs WHERE name = {quote(name)} AND seq >= {len(pieces)};")
        statements += upserts("meta", ("key", "value"), ("key",), [[f"docs:{name}", digest]])
        self.db.room(2 * len(pieces) + 2, name)
        return self.write(statements)

    def sync_meta(self, key: str, value: str) -> int:
        stored = self.db.query("SELECT value FROM meta WHERE key = ?", [key])
        if stored and stored[0]["value"] == value:
            return 0
        return self.write(upserts("meta", ("key", "value"), ("key",), [[key, value]]))


def rotation(sizes: dict[int, int], start: str) -> str:
    """The safety net's weekly rotation: the titles in VERIFY_GROUPS groups of about
    equal size; day d checks group (d - start) % VERIFY_GROUPS."""
    groups: list[list[int]] = [[] for _ in range(VERIFY_GROUPS)]
    totals = [0] * VERIFY_GROUPS
    for n in sorted(sizes, key=lambda n: (-sizes[n], n)):
        i = totals.index(min(totals))
        groups[i].append(n)
        totals[i] += sizes[n]
    return dumps({"start": start, "groups": [sorted(g) for g in groups]})


def sync_rotation(writer: Writer, sizes: dict[int, int], today: Date) -> int:
    """Keep the rotation in meta (title -> size from the copy); rewritten only when
    the set of titles changes, so a day's check writes nothing."""
    stored = writer.db.query("SELECT value FROM meta WHERE key = 'verify_rotation'")
    if stored:
        groups = json.loads(stored[0]["value"])["groups"]
        if sorted(n for g in groups for n in g) == sorted(sizes):
            return 0
    return writer.sync_meta("verify_rotation", rotation(sizes, today.isoformat()))


# ---------- sources ----------

class Recording:
    """A directory written by `record`."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict[str, Any]] = {}
        manifest = path / "manifest.jsonl"
        if manifest.exists():
            for line in manifest.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.entries[entry["key"]] = entry

    def text(self, name: str) -> str:
        return (self.path / name).read_bytes().decode("utf-8", errors="replace")

    def date(self, number: int) -> str | None:
        entry = self.entries.get(f"structure:{number}")
        m = re.search(r"/structure/(\d{4}-\d{2}-\d{2})/", (entry or {}).get("path", ""))
        return m.group(1) if m else None

    def has(self, number: int, node: Node) -> bool:
        return (self.entries.get(recording_key(number, node)) or {}).get("status") in (200, 404)

    def fetch(self, number: int) -> Callable[[Node], tuple[int, str] | None]:
        def get(node: Node) -> tuple[int, str] | None:
            entry = self.entries.get(recording_key(number, node))
            if not entry or entry.get("status") not in (200, 404):
                return None
            if entry["status"] == 404:
                return 404, ""
            return 200, self.text(entry["file"])
        return get


def live_fetch(fetcher: Fetcher, number: int, date: str) -> Callable[[Node], tuple[int, str]]:
    def get(node: Node) -> tuple[int, str]:
        status, body, _ = fetcher.get(f"{V}/full/{date}/title-{number}.xml", xml_params(node), xml=True)
        return status, body.decode("utf-8", errors="replace")
    return get


# ---------- commands ----------

def build(db: Target, rec: Path, titles: list[int] | None = None, log: Callable[[str], None] = print,
          report: dict[str, Any] | None = None, partial: bool = False) -> dict[str, Any]:
    """Recording -> rows. Change-only, so a rerun resumes and an unchanged rebuild writes 0 rows."""
    recording = Recording(rec)
    writer = Writer(db, log)
    listed = json.loads(recording.text("titles.json"))["titles"]
    stats: dict[str, Any] = {"titles": [], "skipped": {}, "flags": Counter(), "alignment": Counter()}
    flagged: dict[str, dict[str, str]] = {}
    copy_dates = {r["number"]: json.loads(r["json"]).get("up_to_date_as_of") for r in db.query("SELECT number, json FROM titles")}
    for row in listed:
        n = row["number"]
        if titles and n not in titles:
            continue
        if row.get("reserved"):
            stats["titles"].append(writer.sync_title(n, {}, None, {}, dumps(row)))
            continue
        structure = rec / "structure" / f"title-{n}.json"
        if not structure.exists():
            stats["skipped"][n] = "no structure recorded"
            continue
        if recording.date(n) != row.get("up_to_date_as_of"):
            stats["skipped"][n] = f"recorded at {recording.date(n)} but titles.json says {row.get('up_to_date_as_of')}"
            continue
        if (copy_dates.get(n) or "") > row["up_to_date_as_of"]:
            # A refresh already moved this title past the recording; never roll it back.
            stats["skipped"][n] = f"the copy is at {copy_dates[n]}, newer than this recording"
            continue
        nodes = walk(json.loads(structure.read_text()))
        fetch = recording.fetch(n)
        missing = [k for k, node in nodes.items() if node.unit == k and not recording.has(n, node)]
        if missing and not partial:
            stats["skipped"][n] = f"{len(missing)} of its parts not recorded yet"
            continue
        started = time.monotonic()
        rows, problems, counts = title_rows(nodes, fetch, log=log)
        result = writer.sync_title(n, rows, set(nodes), None, dumps(row))
        result.update(nodes=len(nodes), flagged=len(problems), seconds=round(time.monotonic() - started, 1))
        stats["titles"].append(result)
        stats["flags"].update(problems.values())
        stats["alignment"].update(counts)
        flagged[str(n)] = problems
        log(f"title {n}: {len(nodes):,} nodes, {result['changed']:,} changed, {result['deleted']:,} deleted, "
            f"{len(problems)} flagged, {result['rows_written']:,} rows written ({result['seconds']}s)")
    if (rec / "agencies.json").exists():
        stats["agencies_rows_written"] = writer.sync_doc(DOC_AGENCIES, recording.text("agencies.json"))
    numbers = [r["number"] for r in db.query("SELECT number, json FROM titles") if not json.loads(r["json"]).get("reserved")]
    sizes = {r["title"]: int(json.loads(r["structure"]).get("size") or 0) for r in db.query(
        f"SELECT title, structure FROM nodes WHERE title IN ({', '.join(map(str, numbers)) or 'NULL'}) AND key = ''")}
    stats["rotation_rows_written"] = sync_rotation(writer, sizes, Date.today())
    stats["rows_written"] = db.rows_written
    if report is not None:
        report["flagged"] = flagged
    return stats


def version_units(fetcher: Fetcher, number: int, since: str, nodes: dict[str, Node]) -> set[str]:
    """Fetch units touched by versions issued on or after since."""
    path = f"{V}/versions/title-{number}.json"
    params = {"issue_date[gte]": since}
    first = fetcher.json(path, params)
    versions = list(first.get("content_versions") or [])
    pages = int((first.get("meta") or {}).get("total_pages") or 1)
    for page in range(2, min(pages, 25) + 1):
        versions += fetcher.json(path, {**params, "page": str(page)}).get("content_versions") or []
    if pages > 25:
        return {k for k, n in nodes.items() if n.unit == k}  # too many to list: every part
    parts = {str(v.get("part")) for v in versions if v.get("part")}
    idents = {str(v.get("identifier")) for v in versions if v.get("identifier")}
    return {k for k, n in nodes.items() if n.unit == k and (
        (n.type == "part" and n.identifier in parts) or (n.type == "appendix" and n.identifier in idents))}


def changed_units(nodes: dict[str, Node], stored: dict[str, dict[str, Any]]) -> set[str]:
    """Fetch units holding a node that was added, removed, or changed in the structure."""
    units: set[str] = set()
    for key, node in nodes.items():
        old = stored.get(key)
        if node.unit and (old is None or old["structure"] != node.structure or old["children"] != node.children_text):
            units.add(node.unit)
    for key in stored.keys() - nodes.keys():
        steps = key.split("/")
        for i in range(len(steps) - 1, 0, -1):
            parent = nodes.get("/".join(steps[:i]))
            if parent is not None:
                if parent.unit:
                    units.add(parent.unit)
                break
    return units


def refresh(db: Target, fetcher: Fetcher, titles: list[int] | None = None,
            log: Callable[[str], None] = print) -> dict[str, Any]:
    """Live eCFR -> rows, change-only."""
    writer = Writer(db, log)
    doc = fetcher.json(f"{V}/titles.json")
    if (doc.get("meta") or {}).get("import_in_progress"):
        log("eCFR is importing (meta.import_in_progress); skipping this run")
        return {"skipped": "import_in_progress", "rows_written": 0, "requests": fetcher.requests}
    stored_titles = {r["number"]: r for r in db.query("SELECT number, json, hash FROM titles")}
    if not titles and not stored_titles:
        raise SystemExit("The copy is empty: load it with build from a recording first "
                         "(or pass --titles to fetch those titles whole from eCFR).")
    stats: dict[str, Any] = {"titles": [], "flags": Counter()}
    for row in doc.get("titles") or []:
        n = row.get("number")
        if titles and n not in titles:
            continue
        text = dumps(row)
        old_row = stored_titles.get(n)
        if old_row and old_row["hash"] == sha(text):
            continue
        old = json.loads(old_row["json"]) if old_row else None
        same = old is not None and all(old.get(k) == row.get(k) for k in ("latest_amended_on", "latest_issue_date"))
        if same or row.get("reserved") or not row.get("up_to_date_as_of"):
            result = writer.sync_title(n, {}, None, {}, text)
            log(f"title {n}: only up_to_date_as_of moved ({result['rows_written']} row)")
            stats["titles"].append(result)
            continue
        date = row["up_to_date_as_of"]
        nodes = walk(fetcher.json(f"{V}/structure/{date}/title-{n}.json"))
        stored = writer.stored_nodes(n, ("key", "structure", "children", "chunks", "hash"))
        units = changed_units(nodes, stored)
        if old is None or not old.get("latest_issue_date") or not stored:
            units = {k for k, node in nodes.items() if node.unit == k}
        else:
            units |= version_units(fetcher, n, old["latest_issue_date"], nodes)
        rows, problems, _ = title_rows(nodes, live_fetch(fetcher, n, date), units, log)
        result = writer.sync_title(n, rows, set(nodes), stored, text)
        result.update(parts_fetched=len(units))
        stats["titles"].append(result)
        stats["flags"].update(problems.values())
        log(f"title {n}: {len(units)} parts fetched, {result['changed']} rows changed, "
            f"{result['deleted']} deleted, {result['rows_written']:,} rows written")
    status, body, _ = fetcher.get("/api/admin/v1/agencies.json", None, xml=False)
    if status == 200:
        stats["agencies_rows_written"] = writer.sync_doc(DOC_AGENCIES, body.decode("utf-8", errors="replace"))
    stats["rows_written"] = db.rows_written
    stats["requests"] = fetcher.requests
    return stats


def whole_title_units(root: Any) -> dict[tuple[str, str], Any]:
    """Each part DIV, and each appendix DIV outside parts, in a whole-title XML."""
    found: dict[tuple[str, str], Any] = {}

    def visit(element: Any) -> None:
        for child in element:
            tag = _tag(child)
            if tag == "DIV5" and (child.get("TYPE") or "").upper() == "PART":
                found.setdefault(("part", child.get("N") or ""), child)
            elif tag == "DIV9":
                found.setdefault(("appendix", child.get("N") or ""), child)
            elif tag.startswith("DIV"):
                visit(child)

    visit(root)
    return found


def verify(db: Target, fetcher: Fetcher, titles: list[int] | None = None, today: Date | None = None,
           log: Callable[[str], None] = print) -> dict[str, Any]:
    """Re-read today's slice of the rotation from eCFR's whole-title XML; fetch
    and rewrite only the parts whose parsed text no longer matches."""
    writer = Writer(db, log)
    today = today or Date.today()
    stored_titles = {r["number"]: json.loads(r["json"]) for r in db.query("SELECT number, json FROM titles")}
    if not titles:
        rows = db.query("SELECT value FROM meta WHERE key = 'verify_rotation'")
        if not rows:
            raise SystemExit("No verify_rotation in meta; run build first.")
        plan = json.loads(rows[0]["value"])
        day = (today - Date.fromisoformat(plan["start"])).days % len(plan["groups"])
        titles = plan["groups"][day]
    stats: dict[str, Any] = {"titles": []}
    for n in titles:
        row = stored_titles.get(n)
        if not row or row.get("reserved") or not row.get("up_to_date_as_of"):
            continue
        date = row["up_to_date_as_of"]
        stored = writer.stored_nodes(n, ("key", "structure", "children", "chunks", "meta", "hash"))
        if not stored:
            continue
        nodes = walk(tree_from_rows(stored))
        status, body, _ = fetcher.get(f"{V}/full/{date}/title-{n}.xml", None, xml=True)
        if status != 200:
            log(f"title {n}: whole-title XML answered {status}; skipped")
            continue
        root = _xml_text._parse_root(body.decode("utf-8", errors="replace"))
        found = whole_title_units(root) if root is not None else {}
        del body
        mismatched: list[str] = []
        groups = by_unit(nodes)
        units = list(groups)
        for key in units:
            element = found.get((nodes[key].type, nodes[key].identifier or ""))
            if element is None:
                mismatched.append(key)
                continue
            rows, _, _ = unit_rows(nodes, key, None, root=element, keys=groups[key])
            for k, r in rows.items():
                old = stored.get(k)
                # The whole-title XML has no hierarchy_metadata: compare with the stored one.
                if old is None or row_hash(r.structure, r.children, r.content, old["meta"], r.flags) != old["hash"]:
                    mismatched.append(key)
                    break
        del root, found
        written = 0
        if mismatched:
            rows, _, _ = title_rows(nodes, live_fetch(fetcher, n, date), set(mismatched), log)
            rows = {k: r for k, r in rows.items() if nodes[k].unit in mismatched}
            written = writer.sync_title(n, rows, None, stored, None)["rows_written"]
        stats["titles"].append({"title": n, "parts": len(units), "mismatched": len(mismatched),
                                "refetched": mismatched[:20], "rows_written": written})
        log(f"title {n}: {len(units)} parts checked, {len(mismatched)} differed, {written} rows written")
    stats["rows_written"] = db.rows_written
    stats["requests"] = fetcher.requests
    return stats


def target(args: argparse.Namespace) -> Target:
    if args.remote:
        token = os.environ.get("CLOUDFLARE_D1_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
        if not token:
            raise SystemExit("Set CLOUDFLARE_D1_TOKEN.")
        account = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or wrangler_config().get("account_id")
        db = RemoteD1(database_id(args.database_id), token, account,
                      max_rows=MAX_ROWS if args.max_rows is None else args.max_rows)
        ensure_schema(db)
        return db
    if args.local:
        return LocalD1(args.local, max_rows=args.max_rows)
    raise SystemExit("Pass --remote or --local PATH.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="download one date of eCFR into a recording directory")
    rec.add_argument("--date", required=True)
    rec.add_argument("--out", required=True, type=Path)
    rec.add_argument("--titles", type=int, nargs="*")
    for name, text in (("build", "recording -> database, change-only"),
                       ("refresh", "live eCFR -> database, change-only"),
                       ("verify", "today's safety-net slice: whole-title XML vs stored hashes")):
        p = sub.add_parser(name, help=text)
        where = p.add_mutually_exclusive_group(required=True)
        where.add_argument("--remote", action="store_true", help="write to the ecfr D1 database")
        where.add_argument("--local", type=Path, help="write to this sqlite file")
        p.add_argument("--database-id")
        p.add_argument("--max-rows", type=int, help=f"stop once a run writes more rows (remote default {MAX_ROWS:,})")
        p.add_argument("--titles", type=int, nargs="*")
        p.add_argument("--json", type=Path, help="also write the run's stats here")
        if name == "build":
            p.add_argument("--rec", required=True, type=Path, help="recording directory")
            p.add_argument("--partial", action="store_true", help=argparse.SUPPRESS)  # dev: build what is recorded so far
    args = parser.parse_args(argv)
    if args.command == "record":
        try:
            Recorder(args.out, args.date).run(args.titles)
        except Stop as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            return 2
        return 0

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    db = target(args)
    report: dict[str, Any] = {}
    stats: dict[str, Any] = {}
    code = 0
    try:
        if args.command == "build":
            stats = build(db, args.rec, args.titles, log, report, partial=args.partial)
        elif args.command == "refresh":
            stats = refresh(db, Fetcher(), args.titles, log)
        else:
            stats = verify(db, Fetcher(), args.titles, log=log)
    except (Stop, RowCap) as exc:
        log(f"stopped: {exc}")
        stats["stopped"] = str(exc)
        code = 2
    except Exception as exc:  # D1 or eCFR trouble: still say what was written
        log(traceback.format_exc())
        stats["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    stats["rows_written"] = db.rows_written
    stats["rows_read"] = db.rows_read
    if isinstance(db, RemoteD1):
        stats["d1_requests"] = db.calls
    log(f"rows written: {db.rows_written:,}")
    text = json.dumps(stats, indent=2, default=str)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    if args.command == "build" and args.local and report:
        Path(str(args.local) + ".flags.json").write_text(json.dumps(report, indent=1) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
