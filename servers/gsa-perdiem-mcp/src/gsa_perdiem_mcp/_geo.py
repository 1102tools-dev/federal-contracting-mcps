# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Place and county name normalization shared by the snapshot builder and runtime.

GSA defines non-standard areas (NSAs) by county, with a handful of
sub-county carve-outs (city limits, military installations). Keys are
"ST|normalized name" strings so they serialize cleanly into JSON.
"""

from __future__ import annotations

import re

_SAINT_RE = re.compile(r"\bsaint\b")
_ST_DOT_RE = re.compile(r"\bst\.")
_COUNTY_SUFFIX_RE = re.compile(r"\s+(county|parish|counties|parishes)$", re.IGNORECASE)


def norm(name: str) -> str:
    """Lowercase, fold 'Saint'/'St.', drop apostrophes/periods, hyphens -> spaces."""
    s = name.lower().replace("’", "'").replace("‘", "'")
    s = _SAINT_RE.sub("st", s)
    s = _ST_DOT_RE.sub("st", s)
    s = s.replace("'", "").replace("`", "").replace(".", "")
    s = s.replace("-", " ").replace("/", " ").replace(",", " ")
    return re.sub(r"\s+", " ", s).strip()


def county_key(state: str, county: str) -> str:
    """'VA', 'Fairfax County' -> 'VA|fairfax'. Independent cities keep 'city'."""
    return f"{state.strip().upper()}|{norm(_COUNTY_SUFFIX_RE.sub('', county.strip()))}"


def place_key(state: str, place: str) -> str:
    return f"{state.strip().upper()}|{norm(place)}"


# GSA rate-workbook spellings that differ from Census county names.
COUNTY_ALIASES = {
    "MD|queen anne": "MD|queen annes",
    "NH|caroll": "NH|carroll",  # FY2021 spelling
}

# Sub-county definitions GSA expresses by city limits or installation rather
# than whole counties. Keyed by the exact LocationDefined text so that any
# wording change in a new GSA file fails the build for human review.
#   counties:  whole counties (or county-equivalents) in the area
#   places:    places/towns inside other counties that belong to the area
#   excluded:  places carved out of the listed counties
PINNED_DEFINITIONS: dict[tuple[str, str], dict[str, list[str]]] = {
    ("AZ", "Coconino / Yavapai less the city of Sedona"): {
        "counties": ["AZ|coconino", "AZ|yavapai"], "places": [], "excluded": ["AZ|sedona"]},
    ("AZ", "City Limits of Sedona"): {"counties": [], "places": ["AZ|sedona"], "excluded": []},
    ("CA", "Los Angeles / Orange / Ventura / Edwards AFB less the city of Santa Monica"): {
        "counties": ["CA|los angeles", "CA|orange", "CA|ventura"],
        "places": ["CA|edwards afb"], "excluded": ["CA|santa monica"]},
    ("CA", "City limits of Santa Monica"): {"counties": [], "places": ["CA|santa monica"], "excluded": []},
    ("CA", "Inyo / NAWS China Lake"): {
        "counties": ["CA|inyo"], "places": ["CA|naws china lake", "CA|china lake"], "excluded": []},
    ("MA", "Suffolk, city of Cambridge"): {
        "counties": ["MA|suffolk"], "places": ["MA|cambridge"], "excluded": []},
    ("MA", "Middlesex less the city of Cambridge"): {
        "counties": ["MA|middlesex"], "places": [], "excluded": ["MA|cambridge"]},
    ("MA", "City limits of Falmouth"): {"counties": [], "places": ["MA|falmouth"], "excluded": []},
    ("MA", "Barnstable less the city of Falmouth"): {
        "counties": ["MA|barnstable"], "places": [], "excluded": ["MA|falmouth"]},
    ("PA", "Dauphin County excluding Hershey"): {
        "counties": ["PA|dauphin"], "places": [], "excluded": ["PA|hershey"]},
    ("PA", "Hershey"): {"counties": [], "places": ["PA|hershey"], "excluded": []},
    ("TX", "Tarrant County / City of Grapevine"): {
        "counties": ["TX|tarrant"], "places": ["TX|grapevine"], "excluded": []},
    ("DC", "Washington DC (also the cities of Alexandria, Falls Church and Fairfax, "
           "and the counties of Arlington and Fairfax, in Virginia; and the counties "
           "of Montgomery and Prince George's in Maryland)"): {
        "counties": ["DC|district of columbia", "VA|alexandria city", "VA|falls church city",
                     "VA|fairfax city", "VA|arlington", "VA|fairfax",
                     "MD|montgomery", "MD|prince georges"],
        "places": [], "excluded": []},
}

# Independent cities are county-equivalents in these states.
_INDEPENDENT_CITY_STATES = frozenset({"VA", "MD", "MO", "NV"})
_SPECIAL_RE = re.compile(r"\b(less|excluding|except|limits|afb|naws|also|installation)\b", re.IGNORECASE)
_CITY_OF_RE = re.compile(r"^(?:city of|city limits of)\s+(.+)$", re.IGNORECASE)
_TRAILING_CITY_RE = re.compile(r"^(.+?)\s+city$", re.IGNORECASE)


def parse_location_defined(state: str, text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Parse GSA's COUNTY/LOCATION DEFINED text into county/place keys.

    Returns (definition, unparsed_tokens). Callers must treat any unparsed
    token as a build failure.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    pinned = PINNED_DEFINITIONS.get((state, text))
    if pinned is not None:
        return {k: list(v) for k, v in pinned.items()}, []
    if not text:
        return {"counties": [], "places": [], "excluded": []}, ["<empty>"]
    definition: dict[str, list[str]] = {"counties": [], "places": [], "excluded": []}
    unparsed: list[str] = []
    stripped = re.sub(r"\b(Counties|County|Parishes|Parish)\b", "", text)
    for part in (p.strip() for p in re.split(r"/|,", stripped)):
        if not part:
            continue
        m = _CITY_OF_RE.match(part)
        if m and state in _INDEPENDENT_CITY_STATES and not _SPECIAL_RE.search(m.group(1)):
            definition["counties"].append(county_key(state, m.group(1) + " city"))
            continue
        if m or _SPECIAL_RE.search(part):
            unparsed.append(part)
            continue
        m = _TRAILING_CITY_RE.match(part)
        if m and state in _INDEPENDENT_CITY_STATES:
            definition["counties"].append(county_key(state, m.group(1) + " city"))
            continue
        definition["counties"].append(county_key(state, part))
    definition["counties"] = [COUNTY_ALIASES.get(k, k) for k in definition["counties"]]
    return definition, unparsed
