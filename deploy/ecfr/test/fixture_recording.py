"""A small eCFR recording for the Worker's tests and CI parity.

Writes OUT in the format `scripts/load_ecfr.py record` writes (titles.json,
agencies.json, structure/, parts/, appendices/, manifest.jsonl), built from
the package's real eCFR answers in servers/ecfr-mcp/tests/fixtures/ecfr_xml
(sections 2.101, 25.504-2, 52.212-3, 52.219-9, 52.236-27, 3052.225-71,
subpart 15.3, 2 CFR 200 Appendix VIII) placed in a small Title 48 and Title 2
tree, plus a synthetic DFARS chapter-level appendix.

OUT/parity holds the eCFR answers test/fixture-cases.json needs, keyed as
scripts/parity.py looks them up: each section, subpart, part and appendix as
eCFR sends it, and filtered structure and ancestry answers (the title-down
chain, then the subtree), so CI can compare the Worker with the Python
server without the network.

    servers/ecfr-mcp/.venv/bin/python deploy/ecfr/test/fixture_recording.py OUT
"""
import hashlib, html, json, re, sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
XML = ROOT / "servers/ecfr-mcp/tests/fixtures/ecfr_xml"
DATE = "2026-10-29"
V = "/api/versioner/v1"
DECL = '<?xml version="1.0" encoding="UTF-8"?> \n'

TITLES = {"titles": [
    {"number": 2, "name": "Federal Financial Assistance", "latest_amended_on": "2026-08-17", "latest_issue_date": "2026-08-18",
     "up_to_date_as_of": DATE, "reserved": False},
    {"number": 13, "name": "Business Credit and Assistance", "latest_amended_on": "2026-09-30", "latest_issue_date": "2026-10-01",
     "up_to_date_as_of": DATE, "reserved": False},
    {"number": 35, "name": "Reserved", "latest_amended_on": None, "latest_issue_date": None, "up_to_date_as_of": None, "reserved": True},
    {"number": 48, "name": "Federal Acquisition Regulations System", "latest_amended_on": "2026-10-19",
     "latest_issue_date": "2026-10-28", "up_to_date_as_of": DATE, "reserved": False},
], "meta": {"date": DATE, "import_in_progress": False}}

AGENCIES = {"agencies": [
    {"name": "Department of Defense", "short_name": "DoD", "display_name": "Department of Defense",
     "sortable_name": "Defense, Department of", "slug": "defense-department", "children": [
         {"name": "Defense Acquisition Regulations System", "short_name": "DARS", "display_name": "Defense Acquisition Regulations System, Department of Defense",
          "sortable_name": "Defense Acquisition Regulations System", "slug": "defense-acquisition-regulations-system", "children": [],
          "cfr_references": [{"title": 48, "chapter": "2"}]}],
     "cfr_references": [{"title": 2, "chapter": "XI"}, {"title": 48, "chapter": "2"}]},
    {"name": "General Services Administration", "short_name": "GSA", "display_name": "General Services Administration",
     "sortable_name": "General Services Administration", "slug": "general-services-administration", "children": [],
     "cfr_references": [{"title": 41, "subtitle": "F"}, {"title": 48, "chapter": "5"}]},
    {"name": "Office of Management and Budget", "short_name": "OMB", "display_name": "Office of Management and Budget",
     "sortable_name": "Management and Budget, Office of", "slug": "management-and-budget-office", "children": [],
     "cfr_references": [{"title": 2, "chapter": "II"}]},
]}


def section_xml(name):
    return (XML / name).read_text()


def strip_decl(text):
    return re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text)


def single_escaped(div):
    """A nested DIV's hierarchy_metadata is escaped once; a response root's twice."""
    return div.replace("&amp;quot;", "&quot;")


def meta(path, citation, alternate=None, double=False):
    value = {"path": f"/on/_SUBSTITUTE_DATE_{path}", "citation": citation}
    if alternate:
        value["alternate_reference"] = alternate
    text = html.escape(json.dumps(value, separators=(",", ":")), quote=True)
    return text.replace("&", "&amp;") if double else text


def node(kind, ident, label_level, description, children=None, size=0, section=False, volumes=True, extra=None):
    """A structure node with eCFR's key order."""
    out = {"identifier": ident, "label": f"{label_level}—{description}" if not section else f"{label_level} {description}",
           "label_level": label_level, "label_description": description, "reserved": False, "type": kind}
    if volumes:
        out["volumes"] = ["1"]
    if section:
        out["received_on"] = "2026-10-01T00:00:00-0400"
    out["size"] = size
    if children is not None:
        out["children"] = children
    out.update(extra or {})
    return out


def divs(text):
    """Each DIV8 inside a subpart fixture, by its N."""
    return {m.group(1): m.group(0) for m in re.finditer(r'<DIV8 N="([^"]+)"[\s\S]*?</DIV8>', text)}


def part_xml(title, number, heading, body, alternate):
    root = (f'<DIV5 N="{number}" TYPE="PART" VOLUME="1" hierarchy_metadata="'
            f'{meta(f"/title-{title}/part-{number}", f"{title} CFR Part {number}", alternate, double=True)}">\n'
            f"<HEAD>{heading}</HEAD>\n<AUTH>\n<HED>Authority:</HED><PSPACE>40 U.S.C. 121(c).</PSPACE>\n</AUTH>\n"
            f"<SOURCE>\n<HED>Source:</HED><PSPACE>62 FR 40237, July 25, 1997, unless otherwise noted.</PSPACE>\n</SOURCE>\n")
    return '<?xml version="1.0"?>\n' + root + body + "</DIV5>\n"


def subpart_xml(title, part, ident, heading, sections, alternate):
    return (f'<DIV6 N="{ident}" TYPE="SUBPART" VOLUME="1" hierarchy_metadata="'
            f'{meta(f"/title-{title}/part-{part}/subpart-{ident}", f"{title} CFR Part {part} Subpart {ident}", alternate)}">\n'
            f"<HEAD>{heading}</HEAD>\n" + "\n".join(strip_decl(s) for s in sections) + "\n</DIV6>\n")


def main(out):
    out = Path(out)
    files, answers = {}, {}

    # Title 48: FAR parts 2, 15, 25, 52, HSAR part 3052, a DFARS chapter-level appendix.
    s2101 = section_xml("t48_2.101.xml")
    s25 = section_xml("t48_25.504-2.xml")
    s52 = {n: section_xml(f"t48_{n}.xml") for n in ("52.212-3", "52.219-9", "52.236-27")}
    s3052 = section_xml("t48_3052.225-71.xml")
    sub153 = section_xml("t48_subpart_15.3.xml")
    in153 = divs(sub153)
    parts = {
        "2": part_xml(48, "2", "PART 2—DEFINITIONS OF WORDS AND TERMS",
                      subpart_xml(48, "2", "2.1", "Subpart 2.1—Definitions", [s2101], "FAR Part 2 Subpart 2.1"), "FAR Part 2"),
        "15": part_xml(48, "15", "PART 15—CONTRACTING BY NEGOTIATION", single_escaped(strip_decl(sub153)), "FAR Part 15"),
        "25": part_xml(48, "25", "PART 25—FOREIGN ACQUISITION",
                       subpart_xml(48, "25", "25.5", "Subpart 25.5—Evaluating Foreign Offers—Supply Contracts", [s25],
                                   "FAR Part 25 Subpart 25.5"), "FAR Part 25"),
        "52": part_xml(48, "52", "PART 52—SOLICITATION PROVISIONS AND CONTRACT CLAUSES",
                       subpart_xml(48, "52", "52.2", "Subpart 52.2—Text of Provisions and Clauses", list(s52.values()),
                                   "FAR Part 52 Subpart 52.2"), "FAR Part 52"),
        "3052": part_xml(48, "3052", "PART 3052—SOLICITATION PROVISIONS AND CONTRACT CLAUSES",
                         subpart_xml(48, "3052", "3052.2", "Subpart 3052.2—Text of Provisions and Clauses", [s3052],
                                     "HSAR Part 3052 Subpart 3052.2"), "HSAR Part 3052"),
    }
    appendix_a = (DECL + f'<DIV9 N="Appendix A to Chapter 2" TYPE="APPENDIX" hierarchy_metadata="'
                  f'{meta("/title-48/chapter-2/appendix-Appendix A to Chapter 2", "Appendix A to Chapter 2, Title 48")}">\n'
                  "<HEAD>Appendix A to Chapter 2—Armed Services Board of Contract Appeals</HEAD>\n"
                  "<HD1>Part 1—Charter</HD1>\n<P>1. <I>Establishment.</I> The Armed Services Board of Contract Appeals is established.</P>\n"
                  "<GPOTABLE COLS=\"2\"><BOXHD><CHED>Rule</CHED><CHED>Title</CHED></BOXHD>\n<ROW><ENT>1</ENT><ENT>Appeals</ENT></ROW>\n"
                  "<ROW><ENT>2</ENT><ENT>Notice<SU>1</SU></ENT></ROW>\n</GPOTABLE>\n<FTNT><P><SU>1</SU> Fixture footnote.</P></FTNT>\n</DIV9>\n")

    def sections_of(xml):
        return [(m.group(1), m.group(2)) for m in re.finditer(r'<DIV8 N="([^"]+)"[^>]*>\s*<HEAD>([^<]*)</HEAD>', xml)]

    def section_nodes(xml):
        return [node("section", n, n, head.split(" ", 1)[1] if " " in head else head, size=len(xml), section=True)
                for n, head in sections_of(xml)]

    def subpart_node(ident, desc, xml, extra=None):
        return node("subpart", ident, f"Subpart {ident}", desc, section_nodes(xml), size=len(xml), extra=extra)

    t48 = node("title", "48", "Title 48", "Federal Acquisition Regulations System", [
        node("chapter", "1", " Chapter 1", "Federal Acquisition Regulation", [
            node("subchapter", "A", "Subchapter A", "General", [
                node("part", "2", "Part 2", "Definitions of Words and Terms",
                     [subpart_node("2.1", "Definitions", s2101, {"descendant_range": "2.101 – 2.101"})],
                     size=len(parts["2"]), extra={"descendant_range": "2.101 – 2.101"})],
                 volumes=False, extra={"descendant_range": "2 – 2"}),
            node("subchapter", "C", "Subchapter C", "Contracting Methods and Contract Types", [
                node("part", "15", "Part 15", "Contracting by Negotiation",
                     [subpart_node("15.3", "Source Selection", sub153)], size=len(parts["15"]),
                     extra={"descendant_range": "15.300 – 15.308"})], volumes=False),
            node("subchapter", "F", "Subchapter F", "Special Categories of Contracting", [
                node("part", "25", "Part 25", "Foreign Acquisition", [subpart_node("25.5", "Evaluating Foreign Offers—Supply Contracts", s25)],
                     size=len(parts["25"]))], volumes=False),
            node("subchapter", "H", "Subchapter H", "Clauses and Forms", [
                node("part", "52", "Part 52", "Solicitation Provisions and Contract Clauses",
                     [subpart_node("52.2", "Text of Provisions and Clauses", "".join(s52.values()))], size=len(parts["52"]))],
                 volumes=False),
        ], volumes=False, extra={"descendant_range": "1 – 99"}),
        node("chapter", "2", " Chapter 2", "Defense Federal Acquisition Regulation System, Department of Defense", [
            node("appendix", "Appendix A to Chapter 2", "Appendix A to Chapter 2", "Armed Services Board of Contract Appeals\n",
                 size=len(appendix_a), section=True)], volumes=False),
        node("chapter", "30", " Chapter 30", "Department of Homeland Security, Homeland Security Acquisition Regulation", [
            node("subchapter", "H", "Subchapter H", "Clauses and Forms", [
                node("part", "3052", "Part 3052", "Solicitation Provisions and Contract Clauses",
                     [subpart_node("3052.2", "Text of Provisions and Clauses", s3052)], size=len(parts["3052"]))], volumes=False),
        ], volumes=False),
    ], volumes=False, size=sum(map(len, parts.values())))

    # Title 2: Part 200 with one subpart section and Appendix VIII.
    s200 = (DECL + f'<DIV8 N="200.1" TYPE="SECTION" hierarchy_metadata="{meta("/title-2/section-200.1", "2 CFR 200.1")}">\n'
            "<HEAD>§ 200.1 Definitions.</HEAD>\n<P>These are the definitions for terms used in this part.</P>\n"
            "<P><I>Acquisition cost</I> means the cost of the asset.</P>\n</DIV8>\n")
    app8 = section_xml("t2_200_appendix_VIII.xml")
    part200 = part_xml(2, "200", "PART 200—UNIFORM ADMINISTRATIVE REQUIREMENTS",
                       f'<DIV6 N="A" TYPE="SUBPART" hierarchy_metadata="{meta("/title-2/part-200/subpart-A", "2 CFR Part 200 Subpart A")}">\n'
                       "<HEAD>Subpart A—Acronyms and Definitions</HEAD>\n" + strip_decl(s200) + "</DIV6>\n" + strip_decl(app8), None)
    t2 = node("title", "2", "Title 2", "Federal Financial Assistance", [
        node("subtitle", "A", "Subtitle A", "Office of Management and Budget Guidance for Federal Financial Assistance", [
            node("chapter", "II", " Chapter II", "Office of Management and Budget Guidance", [
                node("part", "200", "Part 200", "Uniform Administrative Requirements", [
                    node("subpart", "A", "Subpart A", "Acronyms and Definitions",
                         [node("section", "200.1", "§ 200.1", "Definitions.", size=len(s200), section=True)], size=len(s200)),
                    node("appendix", "Appendix VIII to Part 200", "Appendix VIII to Part 200",
                         "Nonprofit Organizations Exempted From Subpart E of Part 200\n", size=len(app8), section=True),
                ], size=len(part200))], volumes=False)], volumes=False)], volumes=False, size=len(part200))

    trees = {48: t48, 2: t2}
    files["titles.json"] = json.dumps(TITLES)
    files["agencies.json"] = json.dumps(AGENCIES)
    manifest = [{"key": "titles", "path": f"{V}/titles.json", "params": {}, "file": "titles.json", "status": 200},
                {"key": "agencies", "path": "/api/admin/v1/agencies.json", "params": {}, "file": "agencies.json", "status": 200}]
    for n, tree in trees.items():
        files[f"structure/title-{n}.json"] = json.dumps(tree, separators=(",", ":"), ensure_ascii=False)
        manifest.append({"key": f"structure:{n}", "path": f"{V}/structure/{DATE}/title-{n}.json", "params": {},
                         "file": f"structure/title-{n}.json", "status": 200})
    xml_units = {(48, "part", k): v for k, v in parts.items()}
    xml_units[(2, "part", "200")] = part200
    for (n, kind, ident), text in xml_units.items():
        files[f"parts/title-{n}/part-{ident}.xml"] = text
        manifest.append({"key": f"part:{n}:{ident}", "path": f"{V}/full/{DATE}/title-{n}.xml", "params": {"part": ident},
                         "file": f"parts/title-{n}/part-{ident}.xml", "status": 200})
    files["appendices/title-48/Appendix A to Chapter 2.xml"] = appendix_a
    manifest.append({"key": "appendix:48:Appendix A to Chapter 2", "path": f"{V}/full/{DATE}/title-48.xml",
                     "params": {"chapter": "2", "appendix": "Appendix A to Chapter 2"},
                     "file": "appendices/title-48/Appendix A to Chapter 2.xml", "status": 200})
    for entry in manifest:
        body = files[entry["file"]].encode()
        entry.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), fetched_at=f"{DATE}T12:00:00+00:00", seconds=0)
    files["manifest.jsonl"] = "".join(json.dumps(e) + "\n" for e in manifest)

    # eCFR's answers for the parity cases.
    def answer(path, params, body, status=200, content_type="application/xml"):
        key = httpx.URL("https://www.ecfr.gov" + path, params=params).raw_path.decode()
        answers[key] = (status, content_type, body.encode() if isinstance(body, str) else body)

    full = f"{V}/full/{DATE}"
    singles = {"2.101": s2101, "25.504-2": s25, "3052.225-71": s3052, **s52,
               **{n: DECL + text + "\n" for n, text in in153.items()}}
    for ident, text in singles.items():
        answer(f"{full}/title-48.xml", {"section": ident}, text)
        chapter = "30" if ident.startswith("3052") else "1"
        answer(f"{full}/title-48.xml", {"chapter": chapter, "section": ident}, text)
    answer(f"{V}/full/2026-10-01/title-48.xml", {"section": "15.305"}, singles["15.305"])
    answer(f"{full}/title-48.xml", {"subpart": "15.3"}, sub153)
    for ident, text in parts.items():
        answer(f"{full}/title-48.xml", {"part": ident}, text)
    answer(f"{full}/title-48.xml", {"chapter": "2", "appendix": "Appendix A to Chapter 2"}, appendix_a)
    answer(f"{full}/title-2.xml", {"part": "200", "appendix": "Appendix VIII to Part 200"}, app8)
    answer(f"{full}/title-2.xml", {"section": "200.1"}, s200)
    answer(f"{full}/title-2.xml", {"part": "200"}, part200)
    answer(f"{full}/title-48.xml", {"section": "15.399"}, '{"error":"Not Found"}', 404, "application/json")

    def chains(tree, path=()):
        yield tree, path
        for child in tree.get("children") or []:
            yield from chains(child, path + (tree,))

    def filtered(chain, target):
        out = target
        for above in reversed(chain):
            out = {k: ([out] if k == "children" else v) for k, v in above.items()}
        return out

    for n, tree in trees.items():
        js = lambda v: json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        answer(f"{V}/structure/{DATE}/title-{n}.json", {}, js(tree), content_type="application/json")
        for target, chain in chains(tree):
            kind, ident = target["type"], target.get("identifier")
            answer_tree = filtered(chain, target)
            levels = {x["type"]: x["identifier"] for x in chain + (target,) if x["type"] in ("chapter", "subchapter", "part", "subpart")}
            if kind in ("chapter", "part", "subpart"):
                answer(f"{V}/structure/{DATE}/title-{n}.json", {kind: ident}, js(answer_tree), content_type="application/json")
            if kind == "subchapter":
                answer(f"{V}/structure/{DATE}/title-{n}.json", {"chapter": levels["chapter"], "subchapter": ident}, js(answer_tree),
                       content_type="application/json")
            if kind == "part":
                # eCFR ignores chapter when a part is the deepest filter: any chapter gets the part's own chain.
                for chapter in [c["identifier"] for c, _ in chains(tree) if c["type"] == "chapter"]:
                    for params in ({"part": ident, "chapter": chapter}, {"chapter": chapter, "part": ident}):
                        answer(f"{V}/structure/{DATE}/title-{n}.json", params, js(answer_tree), content_type="application/json")
            if kind == "subpart":
                answer(f"{V}/structure/{DATE}/title-{n}.json", {"part": levels["part"], "subpart": ident}, js(answer_tree),
                       content_type="application/json")
            if kind in ("section", "appendix", "part", "subpart"):
                ancestors = [{k: v for k, v in x.items() if k != "children"} for x in chain + (target,)]
                answer(f"{V}/ancestry/{DATE}/title-{n}.json", {kind: ident}, js({"ancestors": ancestors}), content_type="application/json")
    answer(f"{V}/versions/title-48", {"section": "15.305"}, json.dumps({"content_versions": [
        {"date": "2017-01-01", "amendment_date": "2017-01-01", "issue_date": "2017-01-01", "identifier": "15.305",
         "name": "15.305   Proposal evaluation.", "part": "15", "substantive": True, "removed": False, "subpart": "15.3",
         "title": "48", "type": "section"}], "meta": {"total_count": 1, "total_pages": 1, "latest_amendment_date": "2017-01-01",
                                                     "latest_issue_date": "2017-01-01"}}), content_type="application/json")

    for name, text in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    bodies = out / "parity" / "bodies"
    bodies.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, (status, content_type, body) in answers.items():
        sha = hashlib.sha256(body).hexdigest()
        (bodies / sha).write_bytes(body)
        lines.append(json.dumps({"key": key, "status": status, "content_type": content_type, "sha256": sha, "bytes": len(body)}))
    (out / "parity" / "manifest.jsonl").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
