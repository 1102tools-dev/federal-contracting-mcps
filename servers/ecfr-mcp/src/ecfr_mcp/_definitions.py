# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Find a term's definition in parsed FAR text.

FAR 2.101 is a list of definitions: each starts with a paragraph that leads
with the term in italics ("*Supplies* means ..."), and the paragraphs after
it, up to the next italic lead, belong to it. index_definitions() indexes
those blocks by name, including the variants people type: the name without
its acronym ("service-disabled veteran-owned small business concern"), the
acronym form ("SDVOSB concern", "COTS"), other italic names in the lead
("*Contract clause* or *clause*"), plurals, hyphen and spacing variants,
and a trailing "means". Mentions are matched on whole words only.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# The italic names at the start of a definition: "*A* or *B* means", "*A, B,* or *C*".
_LEAD = re.compile(r"^\*([^*]+)\*")
_MORE_NAMES = re.compile(r"^\s*(?:,|or|,\s*or)\s*\*([^*]+)\*")
_TRAILING_ACRONYM = re.compile(r"^\s*\(([A-Z][A-Za-z&']{1,10})\)")
_PAREN_ACRONYM = re.compile(r"\s*\(([A-Z][A-Za-z&'.]{1,12}?)(?:'s)?\)\s*")
_SEE = re.compile(r"\(see [“\"]([^”\"]+)[”\"]\)|has the same meaning as \*([^*]+)\*", re.IGNORECASE)
# Common acronyms 2.101 never spells out next to the term.
ACRONYMS = {
    "SAT": "simplified acquisition threshold",
    "MPT": "micro-purchase threshold",
    "UEI": "unique entity identifier",
}
_QUERY_NOISE = re.compile(
    r"^(?:what\s+is\s+|define\s+|definition\s+of\s+|the\s+definition\s+of\s+|the\s+term\s+|the\s+|an?\s+)+",
    re.IGNORECASE,
)
_QUERY_TAIL = re.compile(r"(?:\s+(?:means|is\s+defined\s+as|meaning))+\s*[—–:-]*\s*$", re.IGNORECASE)
# An explicitly introduced list of types can define names without italic leads,
# as Surety does. Ordinary numbered requirements are not such definitions.
_TYPES = re.compile(r"\btypes\b.*\bare as follows:\s*$", re.IGNORECASE)
_TYPE_LEAD = re.compile(r"^\((\d+)\)\s+(?:An?\s+)?([A-Za-z][A-Za-z '-]*?)\s+(?:is|means)\s", re.IGNORECASE)
_NUMBERED = re.compile(r"^\((\d+)\)\s")


def key(text: str) -> str:
    """Compare names without punctuation, case, spacing or possessive suffixes."""
    text = re.sub(r"['’]s\b", "", text.lower())
    return re.sub(r"[^a-z0-9&]", "", text)


def singular(text: str) -> str:
    """'commercial services' -> 'commercial service'; 'supplies' -> 'supply'."""
    words = text.rstrip().split(" ")
    last = words[-1]
    low = last.lower()
    if len(low) > 4 and low.endswith("ies"):
        last = last[:-3] + "y"
    elif len(low) > 4 and re.search(r"(?:ches|shes|sses|xes)$", low):
        last = last[:-2]
    elif len(low) > 3 and low.endswith("s") and not low.endswith("ss"):
        last = last[:-1]
    words[-1] = last
    return " ".join(words)


def clean_query(term: str) -> str:
    text = term.strip().strip("“”\"'‘’?.:;")
    text = _QUERY_NOISE.sub("", text)
    text = _QUERY_TAIL.sub("", text)
    return text.strip().strip("“”\"'‘’,")


def _names(lead: str) -> tuple[list[str], list[str]]:
    """The names a definition goes by, and its acronyms."""
    names: list[str] = []
    m = _LEAD.match(lead)
    if not m:
        return names, []
    raw = [m.group(1)]
    rest = lead[m.end():]
    while True:
        more = _MORE_NAMES.match(rest)
        if not more:
            break
        raw.append(more.group(1))
        rest = rest[more.end():]
    acronyms: list[str] = []
    trailing = _TRAILING_ACRONYM.match(rest)
    if trailing:
        acronyms.append(trailing.group(1))
    for name in raw:
        # "In writing, writing," names two; trailing punctuation and dashes go.
        for part in re.split(r",\s+(?=[a-z])", name):
            part = part.strip().rstrip(",.—-– ").strip()
            if part and part not in names:
                names.append(part)
    for name in list(names):
        acr = _PAREN_ACRONYM.search(name)
        if not acr:
            continue
        acronym = acr.group(1).rstrip(".")
        acronyms.append(acronym)
        before, after = name[: acr.start()].strip(), name[acr.end():].strip()
        for variant in (f"{before} {after}".strip(), f"{acronym} {after}".strip()):
            if variant and variant not in names:
                names.append(variant)
    return names, list(dict.fromkeys(acronyms))


def index_definitions(paragraphs: list[str]) -> list[dict[str, Any]]:
    """Definition blocks of 2.101: lead paragraph plus the paragraphs under it."""
    blocks: list[dict[str, Any]] = []
    for i, p in enumerate(paragraphs):
        if _LEAD.match(p):
            names, acronyms = _names(p)
            blocks.append({"term": names[0] if names else p[:60], "names": names,
                           "acronyms": acronyms, "start": i, "end": i + 1})
        elif blocks:
            blocks[-1]["end"] = i + 1
    # Keep the parent's complete block, and separately index each explicit
    # subtype through the next sibling. A parent query still returns all types.
    subtypes: list[dict[str, Any]] = []
    for block in blocks:
        if not _TYPES.search(paragraphs[block["start"]]):
            continue
        for i in range(block["start"] + 1, block["end"]):
            lead = _TYPE_LEAD.match(paragraphs[i])
            if not lead:
                continue
            end = next((j for j in range(i + 1, block["end"])
                        if _NUMBERED.match(paragraphs[j])), block["end"])
            name = lead.group(2)
            subtypes.append({"term": name, "names": [name], "acronyms": [],
                             "start": i, "end": end})
    blocks.extend(subtypes)
    for block in blocks:
        keys = set()
        for name in block["names"]:
            keys.add(key(name))
            keys.add(key(singular(name)))
        block["keys"] = keys
    return blocks


def _phrase_pattern(text: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in re.split(r"[\s\-–—]+", text.strip()) if w]
    return re.compile(r"(?<![A-Za-z0-9])" + r"[\s\-–—]*".join(words) + r"(?:s|es)?(?![A-Za-z0-9])", re.IGNORECASE)


def find(paragraphs: list[str], term: str) -> dict[str, Any]:
    """Definition blocks for term (best first) and the other paragraphs that mention it."""
    query = clean_query(term)
    blocks = index_definitions(paragraphs)
    wanted = {key(query), key(singular(query))}
    how: dict[int, str] = {}
    for n, block in enumerate(blocks):
        if wanted & block["keys"]:
            primary = block["names"][0] if block["names"] else ""
            how[n] = "name" if wanted & {key(primary), key(singular(primary))} else "other name"
    upper = re.sub(r"[^A-Za-z0-9&]", "", query).upper()
    if not how:
        for n, block in enumerate(blocks):
            if any(a.upper() == upper or a.upper() + "S" == upper for a in block["acronyms"]):
                how.setdefault(n, "acronym")
    if not how and upper in ACRONYMS:
        expanded = ACRONYMS[upper]
        for n, block in enumerate(blocks):
            if key(expanded) in block["keys"]:
                how[n] = f"acronym {upper}"
    rank = {"name": 0, "other name": 1}
    found = sorted(how, key=lambda n: (rank.get(how[n], 2), len(blocks[n]["term"])))
    # Cross-references ("Procurement (see “acquisition”)") bring the target along.
    for n in list(found):
        block = blocks[n]
        lead = paragraphs[block["start"]]
        for see in _SEE.finditer(lead):
            target = key(singular(see.group(1) or see.group(2)))
            target_full = key(see.group(1) or see.group(2))
            for m, other in enumerate(blocks):
                if m not in how and ({target, target_full} & other["keys"]):
                    how[m] = f"referred to by {block['term']}"
                    found.append(m)
    definitions = []
    covered: set[int] = set()
    for n in found:
        block = blocks[n]
        covered.update(range(block["start"], block["end"]))
        definitions.append({
            "kind": "definition",
            "term": block["term"],
            "matched_by": how[n],
            "paragraph_index": block["start"],
            "context": paragraphs[block["start"]:block["end"]],
        })
    pattern = _phrase_pattern(singular(query))
    owner: dict[int, str] = {}
    for block in blocks:
        for i in range(block["start"], block["end"]):
            owner[i] = block["term"]
    mentions = []
    for i, p in enumerate(paragraphs):
        if i in covered:
            continue
        if pattern.search(p.replace("*", "")):
            mention = {"kind": "mention", "paragraph_index": i, "context": [p]}
            if i in owner:
                mention["term"] = owner[i]
            mentions.append(mention)
    suggestions: list[str] = []
    if not definitions:
        names = {name: block["term"] for block in blocks for name in block["names"]}
        close = difflib.get_close_matches(query.lower(), [n.lower() for n in names], n=5, cutoff=0.75)
        lowered = {n.lower(): term for n, term in names.items()}
        # Names that start with the query ("small business" -> "Small business concern").
        stem = key(singular(query))
        starts = [term for name, term in names.items() if key(name).startswith(stem) and stem]
        suggestions = list(dict.fromkeys(starts + [lowered[c] for c in close]))[:8]
    return {"query": query, "definitions": definitions, "mentions": mentions,
            "did_you_mean": suggestions, "block_count": len(blocks)}


def defining_block(paragraphs: list[str], term: str) -> list[str] | None:
    """In another section (19.001, a clause's definitions), the paragraphs that define term."""
    query = singular(clean_query(term))
    words = [re.escape(w) for w in re.split(r"[\s\-–—]+", query) if w]
    if not words:
        return None
    name = r"[\s\-–—]*".join(words) + r"(?:s|es)?"
    # The term opens the paragraph (after at most "(b)" and "Definition."),
    # then "means" or "has the meaning" follows soon, or a dash right after it.
    defining = re.compile(
        r"^(?:\([a-z0-9]{1,4}\)\s*)?(?:Definitions?\.\s*)?" + name +
        r"(?:\W{0,3}—|\W{0,3}(?:\([^)]{1,40}\))?[^.;—]{0,60}?\b(?:means|has the meaning)\b)",
        re.IGNORECASE,
    )
    for i, p in enumerate(paragraphs):
        plain = p.replace("*", "")
        if defining.search(plain):
            block = [p]
            for q in paragraphs[i + 1:]:
                # Sub-paragraphs (1), (i), (A) belong to the definition; the next
                # definition or lettered paragraph does not.
                if re.match(r"^\((?:\d{1,2}|[ivx]{1,5}|[A-Z]|\*\d+\*)\)", q) and not _LEAD.match(q):
                    block.append(q)
                else:
                    break
            return block
    return None
