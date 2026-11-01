#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Write probes.txt: GSA CALC+ query strings that pin down how GSA matches,
filters, sorts and pages, so the Worker's D1 emulation copies GSA's behavior
instead of guessing it. Recorded on GitHub the same night as a full pull
(scripts/load_gsa_calc.py probe), then compared offline with the copy.

Values are encoded the way the Python server encodes them (urllib quote_plus),
so a probe is byte-for-byte a query the server could send. A "repeat:" line is
sent again even when already recorded (GSA's own run-to-run drift).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus as q

TAIL = "page=1&page_size=100&ordering=current_price&sort=asc"


def kw(term: str, tail: str = TAIL) -> str:
    return f"keyword={q(term)}&{tail}"


def search(field: str, value: str, tail: str = TAIL) -> str:
    return f"search={field}:{q(value)}&{tail}"


def suggest(field: str, term: str) -> str:
    return f"suggest-contains={field}:{q(term)}&page=1&page_size=100&ordering=current_price&sort=asc"


def flt(*filters: str, keyword: str | None = None, tail: str = TAIL) -> str:
    parts = [f"keyword={q(keyword)}"] if keyword is not None else []
    for f in filters:
        field, value = f.split(":", 1)
        parts.append(f"filter={field}:{q(value)}")
    return "&".join(parts + [tail])


def order(*pairs: tuple[str, str], keyword: str = "analyst", page: int = 1, size: int = 500) -> str:
    sort = "&".join(f"ordering={f}&sort={d}" for f, d in pairs)
    return f"keyword={q(keyword)}&page={page}&page_size={size}&{sort}"


SECTIONS: list[tuple[str, list[str]]] = [
    ("whole index", [
        "page=1&page_size=1&ordering=current_price&sort=asc",
        "page=1&page_size=10&ordering=current_price&sort=desc",
    ]),
    ("keyword case", [kw("engineer"), kw("ENGINEER"), kw("Engineer"), kw("eNgInEeR")]),
    ("keyword length", [kw("e"), kw("en"), kw("qa"), kw("QA"), kw("it")]),
    ("keyword words", [
        kw("project manager"), kw("manager project"), kw("project  manager"), kw(" project manager "),
        kw("project-manager"), kw("Registered Nurse I"), kw("nurse i"), kw("senior software engineer"),
    ]),
    ("keyword punctuation", [
        kw("c++"), kw("sr."), kw("sr"), kw("a/v"), kw("&"), kw("at&t"), kw("o'neil"), kw('"engineer"'),
        kw("engineer:"), kw("Engineer 1: Sr. Naval Architect"), kw("(senior)"), kw("ii,"), kw("**"),
        kw("[test]"), kw("\\"), kw("100%"), kw("#"), kw("@"), kw("_"),
    ]),
    ("keyword wildcards", [
        kw("eng*neer"), kw("*engineer"), kw("engineer*"), kw("proj*man"), kw("?"), kw("eng?neer"), kw("*"),
    ]),
    ("keyword non-ascii", [kw("café"), kw("CAFÉ"), kw("cafe"), kw("señor"), kw("–")]),
    ("keyword vendor and contract", [
        kw("booz"), kw("booz allen"), kw("allen hamilton"), kw("47QRAA22D004N"), kw("47qraa22d004n"),
        kw("QRAA22"), kw("GS-10F"), kw("GS10F"), kw("ngineer"),
    ]),
    ("keyword other fields", [kw("541611"), kw("54151S"), kw("Facilities Maintenance"), kw("Bachelors"),
                              kw("Customer_Facility"), kw("MAS")]),
    ("keyword no match", [kw("zzzqqqxx")]),
    ("search exact", [
        search("labor_category", "Registered Nurse I"), search("labor_category", "registered nurse i"),
        search("labor_category", "Registered Nurse I "), search("labor_category", "Registered Nurse"),
        search("labor_category", "Engineer 1: Sr. Naval Architect"), search("labor_category", "Engineer 1"),
        search("labor_category", "Engineer*"), search("labor_category", "Program Manager"),
        search("labor_category", "PROGRAM MANAGER"),
        search("vendor_name", "BOOZ ALLEN HAMILTON INC."), search("vendor_name", "booz allen hamilton inc."),
        search("vendor_name", "BOOZ ALLEN"), search("vendor_name", "T47 INTERNATIONAL, INC."),
        search("idv_piid", "47QRAA22D004N"), search("idv_piid", "47qraa22d004n"), search("idv_piid", "47QRAA22"),
    ]),
    ("suggest-contains", [
        suggest("labor_category", "chief"), suggest("labor_category", "CHIEF"), suggest("labor_category", "qa"),
        suggest("labor_category", "project manager"), suggest("labor_category", "eng*neer"),
        suggest("vendor_name", "booz"), suggest("vendor_name", "adv"), suggest("vendor_name", "&"),
        suggest("vendor_name", "saic"), suggest("vendor_name", "pact, inc"),
        suggest("idv_piid", "012"), suggest("idv_piid", "47QRAA"), suggest("idv_piid", "47qraa"),
        suggest("labor_category", "nurse") + "&filter=business_size:S",
    ]),
    ("price bounds", [
        flt("price_range:50,60"), flt("price_range:28.9,28.9"), flt("price_range:28.89,28.9"),
        flt("price_range:28.9,28.91"), flt("price_range:27.92,27.92"), flt("price_range:0,999999"),
        flt("price_range:60,50"), flt("price_range:100,100", keyword="analyst"),
    ]),
    ("experience", [
        flt("experience_range:5,999"), flt("min_years_experience:5"), flt("experience_range:5,5"),
        flt("experience_range:0,0"), flt("experience_range:0,2", keyword="nurse"),
    ]),
    ("education", [
        flt("education_level:BA"), flt("education_level:BA|MA"), flt("education_level:ba"),
        flt("education_level:PHD"), flt("education_level:TEC"), flt("education_level:HS|AA|BA|MA|PHD|TEC"),
        flt("education_level:Bachelors"),
    ]),
    ("business size", [flt("business_size:S"), flt("business_size:O"), flt("business_size:s"),
                       flt("business_size:S", "business_size:O")]),
    ("clearance", [flt("security_clearance:yes"), flt("security_clearance:no"), flt("security_clearance:true"),
                   flt("security_clearance:Yes")]),
    ("sin", [
        flt("sin:541611"), flt("sin:54161"), flt("sin:54151S"), flt("sin:54151s"), flt("sin:541330ENG"),
        flt("sin:541620"), flt("sin:541512"), flt("sin:541611", keyword="analyst"),
    ]),
    ("worksite (ignored?)", [flt("worksite:customer"), flt("worksite:Customer_Facility"),
                             flt("worksite:customer", keyword="nurse")]),
    ("combined filters", [
        flt("education_level:BA", "experience_range:3,999", "price_range:50,100", "business_size:S",
            "security_clearance:no", "sin:54151S", keyword="analyst"),
        flt("education_level:BA|MA", "experience_range:1,999", keyword="Registered Nurse I"),
    ]),
    ("ordering", [
        order(("labor_category", "asc")), order(("labor_category", "desc")),
        order(("vendor_name", "asc")), order(("vendor_name", "desc")),
        order(("education_level", "asc")), order(("min_years_experience", "desc")),
        order(("next_year_price", "asc")), order(("idv_piid", "asc")), order(("business_size", "asc")),
        order(("education_level", "asc"), ("current_price", "desc")),
        order(("current_price", "asc"), ("vendor_name", "asc")),
        order(("current_price", "asc"), keyword="nurse"), order(("current_price", "asc"), keyword="nurse", page=2),
        order(("current_price", "desc"), keyword="nurse"),
        "keyword=analyst&page=1&page_size=100&sort=desc",
        "keyword=analyst&page=1&page_size=100",
    ]),
    ("paging", [
        kw("engineer", "page=20&page_size=500&ordering=current_price&sort=asc"),
        kw("engineer", "page=21&page_size=500&ordering=current_price&sort=asc"),
        kw("engineer", "page=1&page_size=501&ordering=current_price&sort=asc"),
        kw("engineer", "page=1&page_size=0&ordering=current_price&sort=asc"),
        kw("engineer", "page=0&page_size=10&ordering=current_price&sort=asc"),
        kw("nurse", "page=99&page_size=100&ordering=current_price&sort=asc"),
    ]),
    ("exclude", [
        kw("Registered Nurse I", "page=1&page_size=100&ordering=current_price&sort=asc&exclude="
           + q("1710487800|1710487799")),
        kw("Registered Nurse I", "page=1&page_size=100&ordering=current_price&sort=asc&exclude=" + q("1710487800")),
    ]),
    ("igce-style calls (page_size 10)", [
        kw("Program Manager", "page=1&page_size=10&ordering=current_price&sort=asc"),
        kw("Help Desk Specialist", "page=1&page_size=10&ordering=current_price&sort=asc"),
        kw("Cybersecurity Analyst", "page=1&page_size=10&ordering=current_price&sort=asc"),
        flt("sin:541611", tail="page=1&page_size=500&ordering=current_price&sort=asc"),
    ]),
    ("GSA's own drift (sent twice)", [
        "repeat:" + kw("engineer"), "repeat:" + kw("engineer"),
        "repeat:" + kw("analyst", "page=3&page_size=500&ordering=current_price&sort=asc"),
        "repeat:" + kw("analyst", "page=3&page_size=500&ordering=current_price&sort=asc"),
        "repeat:" + kw("Program Manager", "page=1&page_size=10&ordering=current_price&sort=asc"),
        "repeat:" + kw("Program Manager", "page=1&page_size=10&ordering=current_price&sort=asc"),
    ]),
]


def main() -> None:
    lines = [f"# Generated by {Path(__file__).name}; edit that file, not this one."]
    for title, queries in SECTIONS:
        lines.append(f"# {title}")
        lines.extend(queries)
    path = Path(__file__).with_name("probes.txt")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{sum(len(qs) for _, qs in SECTIONS)} probes -> {path}")


if __name__ == "__main__":
    main()
