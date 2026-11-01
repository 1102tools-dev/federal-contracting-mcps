#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Part answers from eCFR's whole-title XML, instead of one ?part= request per part.

eCFR's whole-title download is the same text as its ?part= answers, but it
leaves out the hierarchy_metadata (path and citation) each DIV carries in a
part answer. This writes that metadata from the rule eCFR follows, and checks
the rule against parts recorded the slow way before anything relies on it.

    PY="servers/ecfr-mcp/.venv/bin/python -I deploy/ecfr/scripts/derive_parts.py"
    $PY fetch  --rec REC --titles 1 2 ...    # whole-title XML into REC/full/, paced
    $PY sample --rec REC --per-title 4       # a few real ?part= answers per title into REC/sample/
    $PY check  --rec REC                     # derived vs every real part answer on disk
    $PY write  --rec REC --titles 6 7 ...    # derived part files for parts not recorded

Title 48 is never derived: its metadata adds FAR cross-references
(alternate_reference, primary_far_section), and it is recorded part by part.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "servers" / "ecfr-mcp" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ecfr_mcp import _xml_text as X  # noqa: E402
from load_ecfr import Fetcher, now, part_file  # noqa: E402

V = "/api/versioner/v1"
PLACEHOLDER = "/on/_SUBSTITUTE_DATE_"


def date_of(rec: Path) -> str:
    return json.loads((rec / "titles.json").read_text())["meta"]["date"]


def manifest(rec: Path) -> dict[str, dict[str, Any]]:
    entries = {}
    path = rec / "manifest.jsonl"
    for line in path.read_text().splitlines() if path.exists() else []:
        if line.strip():
            entry = json.loads(line)
            entries[entry["key"]] = entry
    return entries


def log_entry(rec: Path, entry: dict[str, Any]) -> None:
    with (rec / "manifest.jsonl").open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def save(rec: Path, key: str, path: str, params: dict[str, str], rel: str, status: int, body: bytes,
         seconds: float, derived: str | None = None) -> None:
    dest = rec / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    entry = {"key": key, "path": path, "params": params, "file": rel, "status": status, "bytes": len(body),
             "sha256": hashlib.sha256(body).hexdigest(), "fetched_at": now(), "seconds": round(seconds, 2)}
    if derived:
        entry["derived"] = derived
    log_entry(rec, entry)


def head_text(element: ET.Element) -> str:
    head = next((c for c in element if X._tag(c) == "HEAD"), None)
    return " ".join("".join(head.itertext()).split()) if head is not None else ""


# Titles eCFR gives a second name: 14 CFR is the Federal Aviation Regulations,
# 41 CFR the Federal Management Regulation (eCFR says FMR for the FTR too).
ALTERNATE = {14: "FAR", 41: "FMR"}


def stamp(part: ET.Element, title: int) -> ET.Element:
    """A copy of one whole-title PART div with eCFR's hierarchy_metadata written in."""
    part = copy.deepcopy(part)
    p = part.get("N") or ""
    base = f"{PLACEHOLDER}/title-{title}"
    def put(element: ET.Element, path: str, citation: str) -> None:
        meta = {"path": path, "citation": citation}
        if title in ALTERNATE:
            name = ALTERNATE[title]
            meta["alternate_reference"] = (citation.replace(f", Title {title}", f", {name}")
                                           if citation.endswith(f", Title {title}")
                                           else citation.replace(f"{title} CFR", name, 1))
        element.set("hierarchy_metadata", json.dumps(meta, ensure_ascii=False, separators=(",", ":")))

    def visit(element: ET.Element, subpart: str | None) -> None:
        for child in element:
            tag, n = X._tag(child), child.get("N") or ""
            kind = (child.get("TYPE") or "").upper()
            if tag == "DIV6" and kind == "SUBPART":
                put(child, f"{base}/part-{p}/subpart-{n}", f"{title} CFR Part {p} Subpart {n}")
                visit(child, n)
                continue
            if tag == "DIV7" and kind == "SUBJGRP":
                where = f"{title} CFR Part {p}" + (f" Subpart {subpart}" if subpart else "")
                put(child, f"{base}/part-{p}/subject-group-{n}", f"{where} - {head_text(child)}")
            elif tag == "DIV8":
                # A section numbered outside its part (43 CFR part 3430 holds 3431.x) is linked under the part.
                link = n if n.startswith(f"{p}.") or "." not in n else f"{p}.{n}"
                put(child, f"{base}/section-{link}", f"{title} CFR {n}")
            elif tag == "DIV9":
                put(child, f"{base}/part-{p}/appendix-{n}", f"{n}, Title {title}")
            visit(child, subpart)

    put(part, f"{base}/part-{p}", f"{title} CFR Part {p}")
    visit(part, None)
    return part


def whole_title_parts(rec: Path, title: int) -> dict[str, ET.Element]:
    root = X._parse_root((rec / "full" / f"title-{title}.xml").read_text(encoding="utf-8", errors="replace"))
    return {d.get("N") or "": d for d in root.iter("DIV5") if (d.get("TYPE") or "").upper() == "PART"}


def metas(root: ET.Element) -> list[tuple[str, str, str, Any]]:
    out = []
    for d in root.iter():
        tag = X._tag(d)
        if tag.startswith("DIV"):
            raw = d.get("hierarchy_metadata")
            meta = None
            if raw:
                for candidate in (raw, X.html.unescape(raw)):
                    try:
                        meta = json.loads(candidate)
                        break
                    except ValueError:
                        continue
            out.append((tag, d.get("TYPE") or "", d.get("N") or "", meta))
    return out


def real_parts(rec: Path) -> list[tuple[int, str, Path]]:
    """Every real ?part= answer on disk: the recording and the samples."""
    found = []
    for entry in manifest(rec).values():
        if entry["key"].startswith(("part:", "sample:")) and entry["status"] == 200 and not entry.get("derived"):
            _, title, ident = entry["key"].split(":", 2)
            found.append((int(title), ident, rec / entry["file"]))
    return found


def cmd_fetch(rec: Path, titles: list[int]) -> None:
    fetcher, date, done = Fetcher(), date_of(rec), manifest(rec)
    for n in titles:
        key = f"full:{n}"
        if done.get(key, {}).get("status") == 200:
            continue
        path = f"{V}/full/{date}/title-{n}.xml"
        status, body, seconds = fetcher.get(path, None, xml=True)
        if status != 200:
            raise SystemExit(f"title {n}: HTTP {status}; stopping")
        save(rec, key, path, {}, f"full/title-{n}.xml", status, body, seconds)
        print(f"title {n}: {len(body):,} bytes in {seconds:.1f}s", flush=True)


def cmd_sample(rec: Path, per_title: int, seed: int = 11) -> None:
    """Real ?part= answers to check the rule on: parts with subject groups and
    appendices first, then random ones."""
    fetcher, date, done = Fetcher(), date_of(rec), manifest(rec)
    recorded = {(t, i) for t, i, _ in real_parts(rec)}
    rng = random.Random(seed)
    for f in sorted((rec / "structure").glob("title-*.json"), key=lambda f: int(f.stem.split("-")[1])):
        title = int(f.stem.split("-")[1])
        if title == 48 or any(t == title for t, _ in recorded):
            continue
        parts: list[tuple[str, set[str]]] = []

        def walk(node: dict[str, Any], owner: tuple[str, set[str]] | None) -> None:
            if node.get("type") == "part":
                owner = (node["identifier"], set())
                parts.append(owner)
            elif owner is not None:
                owner[1].add(node.get("type"))
            for child in node.get("children") or []:
                walk(child, owner)

        walk(json.loads(f.read_text()), None)
        picks: list[str] = []
        for want in ("subject_group", "appendix", "subpart"):
            have = [p for p, kinds in parts if want in kinds and p not in picks]
            if have:
                picks.append(rng.choice(have))
        rest = [p for p, _ in parts if p not in picks]
        picks += rng.sample(rest, max(0, min(per_title - len(picks), len(rest))))
        for ident in picks[:per_title]:
            key = f"sample:{title}:{ident}"
            if key in done:
                continue
            path = f"{V}/full/{date}/title-{title}.xml"
            status, body, seconds = fetcher.get(path, {"part": ident}, xml=True)
            if status not in (200, 404):
                raise SystemExit(f"{key}: HTTP {status}; stopping")
            save(rec, key, path, {"part": ident}, f"sample/title-{title}/part-{part_file(ident)}.xml", status, body, seconds)
        print(f"title {title}: sampled {min(per_title, len(picks))} parts", flush=True)


def cmd_check(rec: Path) -> int:
    """Derived vs real, two ways: every DIV's metadata, and the whole parse()
    answer for the part (what get_cfr_content(part=...) returns)."""
    date = date_of(rec)
    by_title: dict[int, list[tuple[str, Path]]] = {}
    for title, ident, path in real_parts(rec):
        if title != 48:
            by_title.setdefault(title, []).append((ident, path))
    checked = divs = bad = 0
    for title in sorted(by_title):
        if not (rec / "full" / f"title-{title}.xml").exists():
            print(f"title {title}: whole-title XML not fetched; skipped")
            continue
        parts = whole_title_parts(rec, title)
        for ident, path in by_title[title]:
            real_xml = path.read_text(encoding="utf-8", errors="replace")
            if ident not in parts:
                print(f"MISSING {title} part {ident} in the whole-title XML")
                bad += 1
                continue
            derived = stamp(parts[ident], title)
            want, got = metas(X._parse_root(real_xml)), metas(derived)
            divs += len(want)
            problems = [f"{w} != {g}" for w, g in zip(want, got) if w != g]
            if len(want) != len(got):
                problems.append(f"{len(want)} DIVs recorded, {len(got)} derived")
            derived_xml = ET.tostring(derived, encoding="unicode")
            if X.parse(real_xml, date) != X.parse(derived_xml, date):
                problems.append("parse() answers differ")
            checked += 1
            if problems:
                bad += 1
                print(f"MISMATCH {title} part {ident}: {problems[0][:300]} ({len(problems)} problems)")
        print(f"title {title}: {len(by_title[title])} parts checked", flush=True)
    print(f"checked {checked} parts, {divs} DIVs; {bad} with differences")
    return 1 if bad else 0


def cmd_write(rec: Path, titles: list[int]) -> None:
    """Derived files for every part (and out-of-part appendix) not already
    recorded. Out-of-part appendices can't be derived; they are logged as 404,
    so the copy flags them and the Worker forwards them live."""
    date, done = date_of(rec), manifest(rec)
    for title in titles:
        if title == 48:
            raise SystemExit("Title 48 is recorded part by part, never derived")
        parts = whole_title_parts(rec, title)
        tree = json.loads((rec / "structure" / f"title-{title}.json").read_text())
        wrote = kept = appendices = 0

        def walk(node: dict[str, Any], chapter: str | None, in_part: bool) -> None:
            nonlocal wrote, kept, appendices
            kind = node.get("type")
            if kind == "chapter":
                chapter = node.get("identifier")
            if kind == "part":
                ident = node["identifier"]
                key = f"part:{title}:{ident}"
                if done.get(key, {}).get("status") in (200, 404):
                    kept += 1
                    return
                path = f"{V}/full/{date}/title-{title}.xml"
                rel = f"parts/title-{title}/part-{part_file(ident)}.xml"
                if ident not in parts:
                    save(rec, key, path, {"part": ident}, rel, 404, b"", 0, derived="not in the whole-title XML")
                else:
                    body = ET.tostring(stamp(parts[ident], title), encoding="unicode").encode()
                    save(rec, key, path, {"part": ident}, rel, 200, body, 0, derived="whole-title")
                wrote += 1
                return
            if kind == "appendix" and not in_part:
                key = f"appendix:{title}:{node['identifier']}"
                if key not in done:
                    params = {"chapter": chapter} if chapter else {}
                    params["appendix"] = node["identifier"]
                    save(rec, key, f"{V}/full/{date}/title-{title}.xml", params,
                         f"appendices/title-{title}/{part_file(node['identifier'])}.xml", 404, b"", 0,
                         derived="out-of-part appendix: answered live")
                    appendices += 1
            for child in node.get("children") or []:
                walk(child, chapter, in_part)

        walk(tree, None, False)
        print(f"title {title}: {wrote} parts derived, {kept} already recorded, {appendices} appendices left live",
              flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["fetch", "sample", "check", "write"])
    parser.add_argument("--rec", type=Path, required=True)
    parser.add_argument("--titles", type=int, nargs="*")
    parser.add_argument("--per-title", type=int, default=4)
    args = parser.parse_args()
    listed = json.loads((args.rec / "titles.json").read_text())["titles"]
    titles = args.titles or [t["number"] for t in listed if not t.get("reserved") and t["number"] != 48]
    if args.command == "fetch":
        cmd_fetch(args.rec, titles)
    elif args.command == "sample":
        cmd_sample(args.rec, args.per_title)
    elif args.command == "check":
        return cmd_check(args.rec)
    else:
        cmd_write(args.rec, titles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
