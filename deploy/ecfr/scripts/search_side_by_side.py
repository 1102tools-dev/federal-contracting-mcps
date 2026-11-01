#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""search_cfr: live eCFR search vs a full-text index over the copy.

live:    run each query through the package's own search_cfr (eCFR search plus
         the current-text check), paced as the server paces, and save the answers.
compare: build SQLite FTS5 over the copy's section text (local only, no D1),
         run the same queries, and report top-10 overlap with eCFR, known-item
         hits in the top 5, and the FTS index's row count.

    servers/ecfr-mcp/.venv/bin/python -I deploy/ecfr/scripts/search_side_by_side.py live --out DIR
    servers/ecfr-mcp/.venv/bin/python -I deploy/ecfr/scripts/search_side_by_side.py compare --out DIR --db ecfr-all.sqlite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "servers" / "ecfr-mcp" / "src"))

# Questions a contractor or contracting officer asks, with a title when the
# question names one. Judged by overlap with eCFR's own top 10.
NATURAL = [
    ("small business set-aside", 48), ("organizational conflict of interest", 48),
    ("past performance evaluation", 48), ("sole source justification and approval", 48),
    ("limitations on subcontracting", 48), ("termination for convenience", 48),
    ("equitable adjustment changes clause", 48), ("cyber incident reporting", 48),
    ("safeguarding covered defense information", 48), ("Buy American domestic end product", 48),
    ("Service Contract Labor Standards wage determination", 48), ("Davis-Bacon wage rates", 48),
    ("unsolicited proposal", 48), ("option to extend services", 48),
    ("time-and-materials ceiling price", 48), ("economic price adjustment", 48),
    ("protest to GAO", 48), ("debriefing of offerors", 48),
    ("simplified acquisition threshold", 48), ("micro-purchase threshold", 48),
    ("System for Award Management registration", 48), ("Huawei ZTE telecommunications equipment", 48),
    ("cost accounting standards applicability", 48), ("entertainment costs unallowable", 48),
    ("competition in procurement standards", 2), ("lodging per diem allowance", 41),
    ("reduction in force veterans preference", 5), ("suspension and debarment", None),
    ("price reductions clause", 48), ("independent government cost estimate", None),
]


async def live(out: Path) -> None:
    from ecfr_mcp import server
    out.mkdir(parents=True, exist_ok=True)
    answers = {}
    path = out / "live.json"
    if path.exists():
        answers = json.loads(path.read_text())
    known = out / "known.json"
    extra = [(q, t) for q, t, _ in json.loads(known.read_text())] if known.exists() else []
    for query, title in NATURAL + extra:
        key = f"{title}|{query}"
        if key in answers:
            continue
        try:
            answers[key] = await server.search_cfr(query=query, title=title, per_page=20)
        except Exception as exc:  # recorded, not fatal
            answers[key] = {"error": f"{type(exc).__name__}: {exc}"}
        path.write_text(json.dumps(answers, indent=1))
        print(key, len((answers[key] or {}).get("results", [])), flush=True)


def known_items(db: sqlite3.Connection, n: int, seed: int = 7) -> list[tuple[str, int, str]]:
    """Section headings as queries: the section itself should come back near the top."""
    rows = db.execute("SELECT title, identifier, structure FROM nodes WHERE type = 'section' AND flags = 0").fetchall()
    headings = [(title, ident, json.loads(structure).get("label_description") or "") for title, ident, structure in rows]
    # A heading shared by many sections ("Scope of subpart") has no single right answer.
    seen: dict[tuple[int, str], int] = {}
    for title, _, heading in headings:
        seen[(title, heading.lower())] = seen.get((title, heading.lower()), 0) + 1
    rng = random.Random(seed)
    picks = []
    for title, ident, heading in rng.sample(headings, n * 6):
        if (len(heading.split()) >= 3 and "reserved" not in heading.lower()
                and seen[(title, heading.lower())] == 1):
            picks.append((heading.rstrip("."), title, ident))
        if len(picks) == n:
            break
    return picks


def section_text(content: str) -> tuple[str, str]:
    unit = json.loads(content)["unit"]
    body = " ".join(unit.get("paragraphs", []))
    for table in unit.get("tables", []):
        body += " " + " ".join(" ".join(r) for r in table.get("rows", []))
    return unit.get("heading", ""), body


def build_fts(db: sqlite3.Connection, fts_path: Path) -> sqlite3.Connection:
    fts = sqlite3.connect(fts_path)
    fts.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(title UNINDEXED, identifier UNINDEXED, heading, body, tokenize='porter unicode61')")
    if not fts.execute("SELECT count(*) FROM search").fetchone()[0]:
        before = fts.total_changes
        rows = db.execute("SELECT n.title, n.identifier, COALESCE(n.content, (SELECT group_concat(text, '') FROM "
                          "(SELECT text FROM chunks c WHERE c.title = n.title AND c.key = n.key ORDER BY seq))) "
                          "FROM nodes n WHERE n.type IN ('section', 'appendix')")
        for title, ident, content in rows:
            if content:
                fts.execute("INSERT INTO search VALUES (?, ?, ?, ?)", (title, ident, *section_text(content)))
        fts.commit()
        print("fts rows changed:", fts.total_changes - before)
    return fts


def fts_search(fts: sqlite3.Connection, query: str, title: int | None, k: int = 10) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if len(w) > 1]
    match = " ".join(f'"{w}"' for w in words)
    sql = "SELECT title, identifier FROM search WHERE search MATCH ?" + (" AND title = ?" if title else "")
    sql += " ORDER BY bm25(search, 0, 0, 4.0, 1.0) LIMIT ?"
    args = [match] + ([title] if title else []) + [k]
    return [f"{t}:{i}" for t, i in fts.execute(sql, args)]


def live_ids(answer: dict, k: int = 10) -> list[str]:
    ids = []
    for row in (answer or {}).get("results", []):
        h = row.get("hierarchy") or {}
        ident = h.get("section") or h.get("appendix")
        if ident and f"{h.get('title')}:{ident}" not in ids:
            ids.append(f"{h.get('title')}:{ident}")
    return ids[:k]


def compare(out: Path, db_path: Path) -> None:
    db = sqlite3.connect(db_path)
    fts = build_fts(db, out / "fts.sqlite")
    answers = json.loads((out / "live.json").read_text())
    report = {"natural": [], "known": []}
    for query, title in NATURAL:
        ours, theirs = fts_search(fts, query, title), live_ids(answers.get(f"{title}|{query}"))
        report["natural"].append({"query": query, "title": title, "overlap": len(set(ours) & set(theirs)),
                                  "ecfr": theirs, "ours": ours})
    for query, title, ident in json.loads((out / "known.json").read_text()):
        want = f"{title}:{ident}"
        ours, theirs = fts_search(fts, query, title, 5), live_ids(answers.get(f"{title}|{query}"), 5)
        report["known"].append({"query": query, "want": want, "ours": want in ours, "ecfr": want in theirs})
    nat = report["natural"]
    known = report["known"]
    summary = {
        "natural_queries": len(nat),
        "mean_top10_overlap": round(sum(r["overlap"] for r in nat) / len(nat), 2),
        "known_items": len(known),
        "known_top5_ours": sum(r["ours"] for r in known),
        "known_top5_ecfr": sum(r["ecfr"] for r in known),
        "fts_rows": fts.execute("SELECT count(*) FROM search").fetchone()[0],
    }
    report["summary"] = summary
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(summary, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["known", "live", "compare"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args()
    if args.command == "known":
        picks = known_items(sqlite3.connect(args.db), args.n)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "known.json").write_text(json.dumps(picks, indent=1))
        print(len(picks), "known-item queries")
    elif args.command == "live":
        asyncio.run(live(args.out))
    else:
        compare(args.out, args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
