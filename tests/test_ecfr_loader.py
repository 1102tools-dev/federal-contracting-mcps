"""Offline cases for the hosted eCFR D1 loader (no Cloudflare, no network).

Builds a small made-up Title 48 (two parts, a subject group, a reserved subpart,
a hed1 and appendices in and outside parts) as eCFR would send it, then runs
scripts/load_ecfr.py against it: as a recording for build, and through a fake
eCFR (httpx.MockTransport) for refresh and verify. The reference assembler
(deploy/ecfr/scripts/assemble_reference.py) checks the rows rebuild parse().

    servers/ecfr-mcp/.venv/bin/python -I -m pytest -q tests/test_ecfr_loader.py
"""
from __future__ import annotations

import copy
import html
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


loader = module("load_ecfr", ROOT / "scripts/load_ecfr.py")
reference = module("assemble_reference", ROOT / "deploy/ecfr/scripts/assemble_reference.py")
from ecfr_mcp import _xml_text  # noqa: E402  (the loader put the package on sys.path)

DATE = "2026-10-29"
P1 = "chapter:1/subchapter:A/part:1"
P2 = "chapter:1/subchapter:A/part:2"
SG = "ECFR0123456789abcde"


# ---------- a tiny eCFR ----------

def base_model() -> dict:
    """Title 48 as nested (type, identifier, heading, body) tuples, plus titles.json fields."""
    return {
        "titles": {"number": 48, "name": "Federal Acquisition Regulations System", "latest_amended_on": "2026-10-19",
                   "latest_issue_date": "2026-10-28", "up_to_date_as_of": DATE, "reserved": False},
        "versions": [],
        "importing": False,
        "tree": ["title", "48", "Federal Acquisition Regulations System", [
            ["chapter", "1", "Federal Acquisition Regulation", [
                ["subchapter", "A", "General", [
                    ["part", "1", "Federal Acquisition Regulations System", [
                        ["subpart", "1.1", "Purpose, Authority, Issuance", [
                            ["section", "1.101", "Purpose.", "<P>The Federal Acquisition Regulations System is established.</P>"],
                            ["section", "1.102", "Statement of guiding principles.",
                             "<P>(a) The vision is to deliver <I>best value</I>.</P><CITA TYPE=\"N\">[61 FR 39189]</CITA>"],
                        ]],
                        ["subpart", "1.2", "Administration [Reserved]", []],
                        ["appendix", "Appendix A to Part 1", "Rates",
                         "<GPOTABLE><BOXHD><CHED>Year</CHED><CHED>Rate</CHED></BOXHD>"
                         "<ROW><ENT>2026</ENT><ENT>4%</ENT></ROW></GPOTABLE>"],
                    ]],
                    ["part", "2", "Definitions of Words and Terms", [
                        ["subject_group", SG, "Definitions", [
                            ["section", "2.101", "Definitions.", "<P><I>Acquisition</I> means acquiring by contract.</P>"
                             "<XREF>Amended at 91 FR 1234</XREF>"],
                        ]],
                        ["hed1", None, "Clauses", None],
                        ["section", "2.201", "Contract clause.", "<P>Insert the clause at 52.202-1.</P>"
                         "<NOTE><HED>Note:</HED><P>See 2.101.</P></NOTE>"],
                    ]],
                ]],
                ["appendix", "Appendix A to Chapter 1", "Board Rules", "<P>Rule 1. Scope.</P>"],
            ]],
        ]],
    }


HEADS = {"part": "PART {i}—{h}", "subpart": "Subpart {i}—{h}", "chapter": "CHAPTER {i}—{h}",
         "subchapter": "SUBCHAPTER {i}—{h}", "title": "Title {i}—{h}"}
DIVS = {"title": ("DIV1", "TITLE"), "chapter": ("DIV3", "CHAPTER"), "subchapter": ("DIV4", "SUBCHAP"),
        "part": ("DIV5", "PART"), "subpart": ("DIV6", "SUBPART"), "subject_group": ("DIV7", "SUBJGRP"),
        "section": ("DIV8", "SECTION"), "appendix": ("DIV9", "APPENDIX")}


def head(node) -> str:
    kind, ident, heading = node[0], node[1], node[2]
    if kind in ("section",):
        return f"{ident} {heading}"
    if kind == "appendix":
        return f"{ident}—{heading}"
    if kind in ("subject_group", "hed1"):
        return heading
    return HEADS[kind].format(i=ident, h=heading)


def meta_attr(node, double: bool) -> str:
    kind, ident = node[0], node[1]
    path = f"/on/_SUBSTITUTE_DATE_/title-48/{kind}-{ident}"
    text = html.escape(json.dumps({"path": path, "citation": f"48 CFR {ident}"}, separators=(",", ":")), quote=True)
    return html.escape(text, quote=True) if double else text


def xml_of(node, *, meta: bool, root: bool) -> str:
    kind, ident, heading, body = node
    if kind == "hed1":
        return ""
    tag, typ = DIVS[kind]
    attrs = f' N="{html.escape(ident, quote=True)}" TYPE="{typ}"'
    if meta and kind not in ("title", "chapter", "subchapter"):
        attrs += f' hierarchy_metadata="{meta_attr(node, double=root)}"'
    inner = f"<HEAD>{html.escape(head(node))}</HEAD>\n"
    if isinstance(body, str):
        inner += body + "\n"
    else:
        inner += "".join(xml_of(c, meta=meta, root=False) for c in body)
    return f"<{tag}{attrs}>\n{inner}</{tag}>\n"


def find(node, kind, ident):
    if node[0] == kind and node[1] == ident:
        return node
    if isinstance(node[3], list):
        for child in node[3]:
            hit = find(child, kind, ident)
            if hit:
                return hit
    return None


def structure_of(node) -> dict:
    kind, ident, heading, body = node
    out: dict = {}
    if kind == "subject_group":
        out["generated_id"] = True
    if ident is not None:
        out["identifier"] = ident
    label = head(node) if kind != "section" else f"{ident} {heading}"
    out.update(label=label, label_level=label.split("—")[0], label_description=heading,
               reserved="[Reserved]" in heading, type=kind)
    if isinstance(body, str):
        out["volumes"] = ["1"]
        out["received_on"] = "2026-01-01T00:00:00-0500"
        out["size"] = len(body)
    elif body is None:
        out["size"] = 0
    else:
        kids = [structure_of(c) for c in body]
        out["size"] = sum(k["size"] for k in kids)
        out["children"] = kids
    return out


def title_xml(model) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n<ECFR>\n' + xml_of(model["tree"], meta=False, root=False) + "</ECFR>\n"


def scope_xml(model, kind, ident) -> str | None:
    node = find(model["tree"], kind, ident)
    return None if node is None else '<?xml version="1.0"?>\n' + xml_of(node, meta=True, root=True)


def titles_json(model) -> dict:
    reserved = {"number": 35, "name": "Reserved", "latest_amended_on": None, "latest_issue_date": None,
                "up_to_date_as_of": None, "reserved": True}
    return {"titles": [reserved, model["titles"]], "meta": {"date": DATE, "import_in_progress": model["importing"]}}


AGENCIES = {"agencies": [{"name": "General Services Administration", "slug": "gsa", "children": [],
                          "cfr_references": [{"title": 48, "chapter": "5"}]}]}
AGENCIES_TEXT = json.dumps(AGENCIES)


def write_recording(path: Path, model) -> Path:
    """What `record` would have saved for this model."""
    path.mkdir(parents=True, exist_ok=True)
    manifest = []

    def save(key, rel, body, status=200, api=""):
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(body)
        manifest.append({"key": key, "path": api, "params": {}, "file": rel, "status": status})

    save("titles", "titles.json", json.dumps(titles_json(model)))
    save("agencies", "agencies.json", AGENCIES_TEXT)
    save("structure:48", "structure/title-48.json", json.dumps(structure_of(model["tree"])),
         api=f"/api/versioner/v1/structure/{model['titles']['up_to_date_as_of']}/title-48.json")
    for key, node in loader.walk(structure_of(model["tree"])).items():
        if node.unit == key:
            body = scope_xml(model, node.type, node.identifier)
            save(loader.recording_key(48, node), loader.recording_file(48, node), body or "",
                 status=200 if body else 404)
    (path / "manifest.jsonl").write_text("".join(json.dumps(e) + "\n" for e in manifest))
    return path


class FakeEcfr:
    """eCFR's endpoints the loader calls, answered from a model."""

    def __init__(self, model):
        self.model = model
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, dict(request.url.params)
        self.calls.append(str(request.url))
        m = self.model
        if path == "/api/versioner/v1/titles.json":
            return httpx.Response(200, json=titles_json(m))
        if path == "/api/admin/v1/agencies.json":
            return httpx.Response(200, text=AGENCIES_TEXT)
        if path == f"/api/versioner/v1/structure/{m['titles']['up_to_date_as_of']}/title-48.json":
            return httpx.Response(200, json=structure_of(m["tree"]))
        if path == "/api/versioner/v1/versions/title-48.json":
            since = params.get("issue_date[gte]", "")
            versions = [v for v in m["versions"] if v["issue_date"] >= since]
            return httpx.Response(200, json={"content_versions": versions, "meta": {"total_pages": 1}})
        if path == f"/api/versioner/v1/full/{m['titles']['up_to_date_as_of']}/title-48.xml":
            if not params:
                return httpx.Response(200, text=title_xml(m))
            kind = "part" if "part" in params else "appendix"
            body = scope_xml(m, kind, params[kind])
            return httpx.Response(200, text=body) if body else httpx.Response(404, text="not found")
        return httpx.Response(404, text="unknown")


def fetcher(model) -> tuple[loader.Fetcher, FakeEcfr]:
    fake = FakeEcfr(model)
    client = httpx.Client(transport=httpx.MockTransport(fake), base_url=loader.BASE)
    return loader.Fetcher(client, sleep=lambda s: None), fake


def quiet(_message: str) -> None:
    pass


def keys_written(before: dict, db) -> set[str]:
    after = {r["key"]: r["hash"] for r in db.query("SELECT key, hash FROM nodes WHERE title = 48")}
    return {k for k in after.keys() | before.keys() if after.get(k) != before.get(k)}


def hashes(db) -> dict:
    return {r["key"]: r["hash"] for r in db.query("SELECT key, hash FROM nodes WHERE title = 48")}


def dump(db) -> dict:
    return {t: [tuple(r.values()) for r in db.query(f"SELECT * FROM {t} ORDER BY 1, 2")]
            for t in ("titles", "nodes", "chunks", "docs")}


@pytest.fixture()
def built(tmp_path):
    model = base_model()
    rec = write_recording(tmp_path / "rec", model)
    db = loader.LocalD1(tmp_path / "copy.sqlite")
    stats = loader.build(db, rec, log=quiet)
    db.rows_written = 0  # count each test's own writes
    return model, rec, db, stats


# ---------- build ----------

def test_first_build_writes_every_node_and_rebuilds_parse(built, tmp_path):
    model, rec, db, stats = built
    nodes = {r["key"]: r for r in db.query("SELECT * FROM nodes WHERE title = 48")}
    assert len(nodes) == 15 and stats["titles"][-1]["changed"] == 15
    assert "" in nodes and json.loads(nodes[P1]["children"]) == [
        f"{P1}/subpart:1.1", f"{P1}/subpart:1.2", f"{P1}/appendix:Appendix A to Part 1"]
    assert f"{P2}/hed1:#1" in nodes and nodes[f"{P2}/hed1:#1"]["content"] is None
    structure = json.loads(nodes[P1]["structure"])
    assert structure["children"] is True and list(structure)[-1] == "children"
    section = json.loads(nodes[f"{P1}/subpart:1.1/section:1.102"]["content"])
    assert section == {"n": "1.102", "kind": "section", "unit": {
        "heading": "1.102 Statement of guiding principles.", "paragraphs": ["(a) The vision is to deliver *best value*."],
        "citations": ["[61 FR 39189]"]}, "images": 0, "pending": 0, "unparsed": 0}
    group = json.loads(nodes[f"{P2}/subject_group:{SG}"]["content"])
    assert group["label"] == "Definitions" and group["divs"] == [f"{P2}/subject_group:{SG}/section:2.101"]
    assert json.loads(nodes[f"{P2}/subject_group:{SG}/section:2.101"]["meta"])["path"] == \
        "/on/_SUBSTITUTE_DATE_/title-48/section-2.101"
    # Flags: the reserved subpart has no section below it.
    assert {k for k, r in nodes.items() if r["flags"]} == {f"{P1}/subpart:1.2"}
    titles = {r["number"]: r["json"] for r in db.query("SELECT number, json FROM titles")}
    assert json.loads(titles[48]) == model["titles"] and list(json.loads(titles[48])) == list(model["titles"])
    assert 35 in titles
    doc = "".join(r["text"] for r in db.query("SELECT text FROM docs WHERE name = 'agencies.json' ORDER BY seq"))
    assert json.loads(doc) == AGENCIES
    # The reference assembler rebuilds parse() for every part, section, appendix and subpart.
    report = reference.verify(Path(tmp_path / "copy.sqlite"), rec, log=quiet)
    assert report["mismatches"] == []
    assert report["parts"] == {"match": 2}
    assert report["sections_and_appendices"] == {"match": 6}
    assert report["subparts"] == {"match": 1, "flagged: ?": 1}


def test_rebuilding_unchanged_writes_zero_rows(built):
    model, rec, db, _ = built
    again = loader.LocalD1(Path(db.db.execute("PRAGMA database_list").fetchone()[2]))
    stats = loader.build(again, rec, log=quiet)
    assert stats["rows_written"] == 0 and again.rows_written == 0


def test_build_skips_a_title_whose_recording_is_incomplete(tmp_path):
    rec = write_recording(tmp_path / "rec", base_model())
    lines = (rec / "manifest.jsonl").read_text().splitlines()
    (rec / "manifest.jsonl").write_text("\n".join(l for l in lines if '"part:48:2"' not in l) + "\n")
    db = loader.LocalD1(tmp_path / "copy.sqlite")
    stats = loader.build(db, rec, log=quiet)
    assert "48" in json.dumps(stats["skipped"]) and not db.query("SELECT 1 FROM nodes")


def test_chunked_content_reassembles_and_trims(tmp_path, monkeypatch):
    model = base_model()
    words = "Paragraph text with an apostrophe's (and a curly \u2019) worth of words. " * 6
    long_text = "".join(f"<P>({i}) {words}</P>" for i in range(60))
    find(model["tree"], "section", "1.101")[3] = long_text
    rec = write_recording(tmp_path / "rec", model)
    monkeypatch.setattr(loader, "CONTENT_BYTES", 4_000)
    db = loader.LocalD1(tmp_path / "copy.sqlite")
    loader.build(db, rec, log=quiet)
    key = f"{P1}/subpart:1.1/section:1.101"
    row = db.query("SELECT content, chunks FROM nodes WHERE key = ?", [key])[0]
    assert row["content"] is None and row["chunks"] > 3
    pieces = db.query("SELECT seq, text FROM chunks WHERE key = ? ORDER BY seq", [key])
    assert [p["seq"] for p in pieces] == list(range(row["chunks"]))
    assert all(loader.size(loader.quote(p["text"])) <= 4_000 for p in pieces)
    report = reference.verify(Path(tmp_path / "copy.sqlite"), rec, log=quiet)
    assert report["mismatches"] == [] and report["sections_and_appendices"]["match"] == 6
    db.rows_written = 0
    assert loader.build(db, rec, log=quiet)["rows_written"] == 0
    # Shorter text: the row goes back to plain content and its chunks are deleted.
    find(model["tree"], "section", "1.101")[3] = "<P>Short now.</P>"
    rec2 = write_recording(tmp_path / "rec2", model)
    loader.build(db, rec2, log=quiet)
    assert db.query("SELECT chunks FROM nodes WHERE key = ?", [key])[0]["chunks"] == 0
    assert db.query("SELECT COUNT(*) n FROM chunks")[0]["n"] == 0


def test_flags_nested_sections_and_unaligned_divs(tmp_path):
    model = base_model()
    # A section with a nested section DIV, and a division eCFR's structure doesn't list.
    find(model["tree"], "section", "2.201")[3] = (
        '<P>Intro.</P><DIV8 N="2.201a" TYPE="SECTION"><HEAD>2.201a Odd.</HEAD><P>x</P></DIV8>')
    find(model["tree"], "subpart", "1.1")[3].append(["section", "1.199", "Ghost.", "<P>Only in XML.</P>"])
    rec = write_recording(tmp_path / "rec", model)
    # The ghost section is in the XML but not the structure.
    tree = json.loads((rec / "structure/title-48.json").read_text())
    sub = tree["children"][0]["children"][0]["children"][0]["children"][0]
    sub["children"] = [c for c in sub["children"] if c["identifier"] != "1.199"]
    (rec / "structure/title-48.json").write_text(json.dumps(tree))
    db = loader.LocalD1(tmp_path / "copy.sqlite")
    report: dict = {}
    loader.build(db, rec, log=quiet, report=report)
    reasons = report["flagged"]["48"]
    assert reasons[f"{P2}/section:2.201"] == "nested section DIVs"
    assert reasons[f"{P1}/subpart:1.1"] == reasons[P1] == "XML DIV with no structure node"
    assert reasons[f"{P1}/subpart:1.2"] == "no section or appendix below"


# ---------- refresh ----------

def test_refresh_skips_while_ecfr_imports(built):
    model, _, db, _ = built
    model = copy.deepcopy(model)
    model["importing"] = True
    model["titles"]["latest_amended_on"] = "2026-10-30"
    f, fake = fetcher(model)
    stats = loader.refresh(db, f, log=quiet)
    assert stats["skipped"] == "import_in_progress" and db.rows_written == 0
    assert len(fake.calls) == 1


def test_refresh_date_only_writes_the_titles_row_and_version(built):
    model, _, db, _ = built
    model = copy.deepcopy(model)
    model["titles"]["up_to_date_as_of"] = "2026-10-30"
    f, fake = fetcher(model)
    stats = loader.refresh(db, f, log=quiet)
    assert db.rows_written == 2 and stats["titles"][0]["title_row"]  # the titles row and meta version
    assert not any("structure" in c or ".xml" in c for c in fake.calls)
    loader.refresh(db, fetcher(model)[0], log=quiet)
    assert db.rows_written == 2  # nothing more the second time


def test_refresh_one_changed_section_writes_it_and_ancestor_sizes(built):
    model, _, db, _ = built
    before = hashes(db)
    model = copy.deepcopy(model)
    model["titles"].update(latest_amended_on="2026-10-30", latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    find(model["tree"], "section", "1.101")[3] = "<P>The Federal Acquisition Regulations System is hereby established.</P>"
    model["versions"] = [{"issue_date": "2026-10-30", "part": "1", "identifier": "1.101", "type": "section"}]
    f, fake = fetcher(model)
    stats = loader.refresh(db, f, log=quiet)
    assert keys_written(before, db) == {"", "chapter:1", "chapter:1/subchapter:A", P1, f"{P1}/subpart:1.1",
                                        f"{P1}/subpart:1.1/section:1.101"}
    assert stats["rows_written"] == 8  # six nodes, the titles row and meta version
    assert sum(".xml" in c for c in fake.calls) == 1  # only Part 1 was fetched again
    loader.refresh(db, fetcher(model)[0], log=quiet)
    assert db.rows_written == 8


def test_refresh_same_size_edit_found_through_versions(built):
    model, _, db, _ = built
    before = hashes(db)
    model = copy.deepcopy(model)
    model["titles"].update(latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    find(model["tree"], "section", "2.201")[3] = "<P>Insert the clause at 52.202-2.</P><NOTE><HED>Note:</HED><P>See 2.101.</P></NOTE>"
    model["versions"] = [{"issue_date": "2026-10-30", "part": "2", "identifier": "2.201", "type": "section"},
                         {"issue_date": "2026-10-01", "part": "1", "identifier": "1.101", "type": "section"}]
    f, fake = fetcher(model)
    loader.refresh(db, f, log=quiet)
    assert keys_written(before, db) == {f"{P2}/section:2.201"}
    assert db.rows_written == 3
    assert [c for c in fake.calls if ".xml" in c] == [
        f"https://www.ecfr.gov/api/versioner/v1/full/2026-10-30/title-48.xml?part=2"]


def test_refresh_inserted_section_adds_one_row_and_parent_children(built):
    model, _, db, _ = built
    before = hashes(db)
    model = copy.deepcopy(model)
    model["titles"].update(latest_amended_on="2026-10-30", latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    find(model["tree"], "subpart", "1.1")[3].append(["section", "1.103", "Authority.", "<P>New text.</P>"])
    f, _ = fetcher(model)
    loader.refresh(db, f, log=quiet)
    sub = f"{P1}/subpart:1.1"
    assert keys_written(before, db) == {"", "chapter:1", "chapter:1/subchapter:A", P1, sub, f"{sub}/section:1.103"}
    row = db.query("SELECT children, content FROM nodes WHERE key = ?", [sub])[0]
    assert json.loads(row["children"])[-1] == f"{sub}/section:1.103"
    assert json.loads(row["content"])["divs"][-1] == f"{sub}/section:1.103"


def test_refresh_removed_section_deletes_its_row(built):
    model, _, db, _ = built
    model = copy.deepcopy(model)
    model["titles"].update(latest_amended_on="2026-10-30", latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    sub = find(model["tree"], "subpart", "1.1")
    sub[3] = [c for c in sub[3] if c[1] != "1.102"]
    loader.refresh(db, fetcher(model)[0], log=quiet)
    keys = {r["key"] for r in db.query("SELECT key FROM nodes")}
    assert f"{P1}/subpart:1.1/section:1.102" not in keys and f"{P1}/subpart:1.1/section:1.101" in keys


def test_refresh_matches_a_fresh_build(built, tmp_path):
    model, _, db, _ = built
    model = copy.deepcopy(model)
    model["titles"].update(latest_amended_on="2026-10-30", latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    find(model["tree"], "section", "2.101")[3] = "<P>Changed.</P>"
    find(model["tree"], "subpart", "1.1")[3].append(["section", "1.103", "Authority.", "<P>New.</P>"])
    model["versions"] = [{"issue_date": "2026-10-30", "part": "2", "identifier": "2.101", "type": "section"}]
    loader.refresh(db, fetcher(model)[0], log=quiet)
    fresh = loader.LocalD1(tmp_path / "fresh.sqlite")
    loader.build(fresh, write_recording(tmp_path / "rec-new", model), log=quiet)
    assert dump(db) == dump(fresh)


# ---------- verify (safety net) ----------

def test_verify_unchanged_writes_nothing_and_repairs_a_bad_row(built):
    model, _, db, _ = built
    f, fake = fetcher(model)
    stats = loader.verify(db, f, [48], log=quiet)
    assert stats["rows_written"] == 0 and stats["titles"][0]["mismatched"] == 0
    assert sum(".xml" in c for c in fake.calls) == 1  # just the whole-title XML
    key = f"{P2}/section:2.201"
    good = db.query("SELECT content, hash FROM nodes WHERE key = ?", [key])[0]
    db.execute([f"UPDATE nodes SET content = 'garbled', hash = 'x' WHERE key = {loader.quote(key)};"])
    db.rows_written = 0
    f, fake = fetcher(model)
    stats = loader.verify(db, f, [48], log=quiet)
    assert stats["titles"][0]["refetched"] == [P2] and stats["rows_written"] == 2  # the row and meta version
    assert db.query("SELECT content, hash FROM nodes WHERE key = ?", [key])[0] == good


def test_verify_rotation_covers_every_title_each_week(built):
    _, _, db, _ = built
    plan = json.loads(db.query("SELECT value FROM meta WHERE key = 'verify_rotation'")[0]["value"])
    assert len(plan["groups"]) == loader.VERIFY_GROUPS and sorted(n for g in plan["groups"] for n in g) == [48]


# ---------- D1 limits, rows_written, the cap, resume ----------

class FakeD1:
    """The D1 /query endpoint over an in-memory sqlite: one result per request with meta."""

    def __init__(self, fail_after: int | None = None, meta: bool = True):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(loader.SCHEMA.read_text())
        self.payloads: list[dict] = []
        self.fail_after = fail_after
        self.meta = meta

    def __call__(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if self.fail_after is not None and len(self.payloads) > self.fail_after:
            raise RuntimeError("connection reset")
        if "params" in payload:
            rows = [dict(r) for r in self.db.execute(payload["sql"], payload["params"])]
            return {"success": True, "result": [{"results": rows, "meta": {"rows_read": len(rows), "rows_written": 0}}]}
        before = self.db.total_changes
        self.db.executescript(payload["sql"])
        meta = {"rows_written": self.db.total_changes - before} if self.meta else {}
        return {"success": True, "result": [{"results": [], "meta": meta}]}


def remote(fake: FakeD1, max_rows: int | None = 10_000) -> loader.RemoteD1:
    return loader.RemoteD1("db", "token", "account", max_rows=max_rows, post=fake, sleep=lambda s: None)


def test_remote_sums_rows_written_and_matches_local(built, tmp_path):
    model, rec, local, first = built
    fake = FakeD1()
    db = remote(fake)
    stats = loader.build(db, rec, log=quiet)
    assert db.rows_written == stats["rows_written"] == first["rows_written"] > 0
    assert sum(p.get("params") is None for p in fake.payloads) >= 1
    assert loader.build(remote(fake), rec, log=quiet)["rows_written"] == 0


def test_remote_stops_without_rows_written_meta(built):
    _, rec, _, _ = built
    with pytest.raises(RuntimeError, match="rows_written"):
        loader.build(remote(FakeD1(meta=False)), rec, log=quiet)


def test_max_rows_cap_refuses_before_writing_and_stops_after(built):
    _, rec, _, _ = built
    fake = FakeD1()
    with pytest.raises(loader.RowCap, match="Nothing written"):
        loader.build(remote(fake, max_rows=5), rec, log=quiet)
    assert fake.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
    db = remote(FakeD1(), max_rows=5)
    with pytest.raises(loader.RowCap, match="passed --max-rows"):
        db.execute(["INSERT INTO meta (key, value) VALUES " + ", ".join(f"('k{i}', 'v')" for i in range(9)) + ";"])
    assert db.rows_written == 9


def test_resume_after_an_interrupted_remote_run(built, tmp_path, monkeypatch):
    model, rec, local, first = built
    monkeypatch.setattr(loader, "REQUEST_BYTES", 4_000)  # many small requests
    fake = FakeD1(fail_after=6)
    with pytest.raises(RuntimeError, match="connection reset"):
        loader.build(remote(fake), rec, log=quiet)
    fake.fail_after = None
    db = remote(fake)
    loader.build(db, rec, log=quiet)
    assert 0 < db.rows_written < first["rows_written"]
    got = {t: [tuple(r) for r in fake.db.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
           for t in ("titles", "nodes", "chunks", "docs")}
    assert got == dump(local)


def test_statement_and_request_limits(tmp_path, monkeypatch):
    # 3,000 children (165 KB of keys, like 40 CFR 721 subpart E) and 300 KB of content.
    parent = {"identifier": "E", "label": "Subpart E", "type": "subpart", "size": 1, "children": [
        {"identifier": f"721.{10000 + i}", "label": f"721.{10000 + i} Chemical substance.", "type": "section", "size": 1}
        for i in range(3000)]}
    tree = {"identifier": "40", "label": "Title 40", "type": "title", "size": 1, "children": [
        {"identifier": "721", "label": "Part 721", "type": "part", "size": 1, "children": [parent]}]}
    nodes = loader.walk(tree)
    rows = [loader.plain_row(n) for n in nodes.values()]
    big = next(r for r in rows if r.key == "part:721/subpart:E")
    big.content = json.dumps({"n": "E", "kind": "subpart", "unit": {"paragraphs": ["x'—" * 100_000]},
                              "divs": json.loads(big.children), "images": 0, "pending": 0, "unparsed": 0})
    writer = loader.Writer(loader.LocalD1(":memory:"), quiet)
    statements, _ = writer.node_statements(40, rows, {})
    assert max(loader.size(s) for s in statements) <= loader.STATEMENT_BYTES
    fake = FakeD1()
    db = remote(fake, max_rows=None)
    db.execute(statements)
    assert all(loader.size(p["sql"]) <= loader.REQUEST_BYTES for p in fake.payloads) and len(fake.payloads) > 1
    stored = fake.db.execute("SELECT children, content, chunks FROM nodes WHERE key = 'part:721/subpart:E'").fetchone()
    assert stored["children"] == big.children and stored["content"] is None and stored["chunks"] > 3
    text = "".join(t for (t,) in fake.db.execute("SELECT text FROM chunks WHERE key = 'part:721/subpart:E' ORDER BY seq"))
    assert text == big.content
    assert loader.quote("a\x00b'") == "('a' || char(0) || 'b''')"


def test_cli_remote_build_one_title_applies_schema_and_reruns_at_zero(tmp_path, monkeypatch, capsys):
    rec = write_recording(tmp_path / "rec", base_model())
    fake = FakeD1()
    fake.db.executescript("DROP TABLE titles; DROP TABLE nodes; DROP TABLE chunks; DROP TABLE docs; DROP TABLE meta;")
    monkeypatch.setattr(loader.RemoteD1, "_http", lambda self, payload: fake(payload))
    monkeypatch.setenv("CLOUDFLARE_D1_TOKEN", "token")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "846d3e41e48446abcd3570c0959f9fb5")
    args = ["build", "--remote", "--database-id", "00000000-0000-4000-8000-000000000000",
            "--rec", str(rec), "--titles", "48", "--json", str(tmp_path / "out.json")]
    assert loader.main(args) == 0
    first = json.loads((tmp_path / "out.json").read_text())
    assert first["titles"][0]["rows_written"] > 15 and first["rows_written"] > first["titles"][0]["rows_written"]
    assert "title 48:" in capsys.readouterr().err
    assert fake.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 15
    assert loader.main(args) == 0
    assert json.loads((tmp_path / "out.json").read_text())["rows_written"] == 0
    # The cap: a title that would pass --max-rows is refused before anything is written for it.
    fake2 = FakeD1()
    monkeypatch.setattr(loader.RemoteD1, "_http", lambda self, payload: fake2(payload))
    assert loader.main(args + ["--max-rows", "10"]) == 2
    assert "passes --max-rows" in json.loads((tmp_path / "out.json").read_text())["stopped"]
    assert fake2.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0


def test_build_never_rolls_back_a_refreshed_title(built):
    model, rec, db, _ = built
    newer = copy.deepcopy(model)
    newer["titles"].update(latest_amended_on="2026-10-30", latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    find(newer["tree"], "section", "1.101")[3] = "<P>Newer text.</P>"
    loader.refresh(db, fetcher(newer)[0], log=quiet)
    after = hashes(db)
    db.rows_written = 0
    stats = loader.build(db, rec, log=quiet)
    assert "newer than this recording" in stats["skipped"][48] and db.rows_written == 0 and hashes(db) == after


def version(db) -> str | None:
    rows = db.query("SELECT value FROM meta WHERE key = 'version'")
    return rows[0]["value"] if rows else None


def test_every_writing_run_sets_a_new_version_last(built, tmp_path):
    model, rec, db, _ = built
    first = version(db)
    assert first
    loader.build(db, rec, log=quiet)  # writes nothing
    loader.refresh(db, fetcher(model)[0], log=quiet)  # eCFR unchanged: writes nothing
    loader.verify(db, fetcher(model)[0], [48], log=quiet)
    assert db.rows_written == 0 and version(db) == first
    newer = copy.deepcopy(model)
    newer["titles"].update(latest_amended_on="2026-10-30", latest_issue_date="2026-10-30", up_to_date_as_of="2026-10-30")
    find(newer["tree"], "section", "2.101")[3] = "<P>Changed.</P>"
    loader.refresh(db, fetcher(newer)[0], log=quiet)
    second = version(db)
    assert second and second != first
    # Remote: the version upsert is the last statement of the run's last request, after the titles row.
    fake = FakeD1()
    loader.build(remote(fake), rec, log=quiet)
    writes = [p["sql"] for p in fake.payloads if "params" not in p]
    last = writes[-1].rstrip().splitlines()[-1]
    assert last.startswith("INSERT INTO meta (key, value) VALUES ('version', ")
    title_writes = [i for i, sql in enumerate(writes) if "INSERT INTO titles" in sql]
    assert all("'version'" in writes[i].rsplit("INSERT INTO titles", 1)[1] for i in title_writes)


# ---------- audit (real part answers for derived parts) ----------

APPENDIX_C1 = "chapter:1/appendix:Appendix A to Chapter 1"


def derived_copy(tmp_path, model):
    """A copy built from a recording whose Part 2 file was 'derived': the subject
    group's citation differs from what eCFR's real ?part=2 answer says."""
    rec = write_recording(tmp_path / "derived-rec", model)
    path = rec / "parts/title-48/part-2.xml"
    text = path.read_text()
    assert f"48 CFR {SG}" in text
    path.write_text(text.replace(f"48 CFR {SG}", "48 CFR Part 2 Definitions"))
    db = loader.LocalD1(tmp_path / "derived.sqlite")
    loader.build(db, rec, log=quiet)
    db.rows_written = 0
    return db


def node_rows(db) -> dict:
    return {r["key"]: (r["hash"], r["content"], r["meta"]) for r in db.query("SELECT key, hash, content, meta FROM nodes")}


def cursor(db) -> dict:
    return json.loads(db.query("SELECT value FROM meta WHERE key = 'audit_cursor'")[0]["value"])


def ticking(step: float):
    """A clock that moves step seconds every time it is read."""
    t = {"now": -step}

    def clock() -> float:
        t["now"] += step
        return t["now"]
    return clock


def test_audit_rewrites_only_a_derived_node_that_differs(tmp_path):
    model = base_model()
    db = derived_copy(tmp_path, model)
    before, first_version = node_rows(db), version(db)
    f, fake = fetcher(model)
    logs: list[str] = []
    stats = loader.audit(db, f, [48], log=logs.append)
    group = f"{P2}/subject_group:{SG}"
    after = node_rows(db)
    assert {k for k in after if after[k] != before[k]} == {group}
    assert json.loads(after[group][2])["citation"] == f"48 CFR {SG}"
    report = stats["titles"][0]
    assert report["fetched"] == 3 and report["nodes_changed"] == 1 and report["differed"] == {P2: 1}
    assert report["rows_written"] == 2  # the node and meta version
    assert any(group in line for line in logs) and any("1 nodes changed in 1 parts" in line for line in logs)
    assert version(db) != first_version
    assert [c.split("?")[1] for c in fake.calls] == [
        "part=1", "part=2", "chapter=1&appendix=Appendix+A+to+Chapter+1"]
    assert cursor(db)["done"] is True
    # The copy now equals a build from the real answers.
    real = loader.LocalD1(tmp_path / "real.sqlite")
    loader.build(real, write_recording(tmp_path / "real-rec", model), log=quiet)
    assert node_rows(db) == node_rows(real)


def test_audit_of_identical_parts_writes_no_content(built):
    model, _, db, _ = built
    before, first_version = node_rows(db), version(db)
    stats = loader.audit(db, fetcher(model)[0], [48], log=quiet)
    assert node_rows(db) == before and version(db) == first_version
    assert stats["titles"][0]["rows_written"] == 0 and stats["titles"][0]["nodes_changed"] == 0
    # Only the cursor moved (loader state, not content).
    assert db.rows_written == 2  # cursor saves: end of Title 48, then the plan marked done


def test_audit_stops_on_its_time_budget_and_resumes_at_the_cursor(tmp_path, monkeypatch, capsys):
    model = base_model()
    db = derived_copy(tmp_path, model)
    monkeypatch.setattr(loader, "AUDIT_BATCH", 1)
    # Each clock read is 20 s (start, title, then one per part); a 1-minute budget allows
    # two part fetches, then stops cleanly.
    f, fake = fetcher(model)
    stats = loader.audit(db, f, [48], minutes=1, clock=ticking(20), log=quiet)
    assert "time budget" in stats["stopped"] and stats["titles"][0]["fetched"] == 2
    assert cursor(db)["title"] == 48 and cursor(db)["after"] == P2 and cursor(db)["done"] is False
    assert stats["titles"][0]["nodes_changed"] == 1  # Part 2's fix was written before stopping
    assert len(fake.calls) == 2
    # The next run fetches only what is left, then marks the audit done.
    f, fake = fetcher(model)
    stats = loader.audit(db, f, [48], log=quiet)
    assert [c.split("?")[1] for c in fake.calls] == ["chapter=1&appendix=Appendix+A+to+Chapter+1"]
    assert stats["titles"][0]["fetched"] == 1 and cursor(db)["done"] is True
    # Done means done until --restart.
    f, fake = fetcher(model)
    assert loader.audit(db, f, [48], log=quiet)["titles"] == [] and fake.calls == []
    loader.audit(db, f, [48], restart=True, log=quiet)
    assert len(fake.calls) == 3


def test_audit_command_exits_cleanly_on_its_budget(tmp_path, monkeypatch, capsys):
    model = base_model()
    db = derived_copy(tmp_path, model)
    f, _ = fetcher(model)
    monkeypatch.setattr(loader, "Fetcher", lambda: f)
    args = ["audit", "--local", str(tmp_path / "derived.sqlite"), "--titles", "48", "--minutes", "0",
            "--json", str(tmp_path / "audit.json")]
    assert loader.main(args) == 0
    out = json.loads((tmp_path / "audit.json").read_text())
    assert "time budget" in out["stopped"] and out["requests"] == 0


def test_audit_follows_the_copy_date_and_never_mixes_dates(tmp_path, monkeypatch):
    model = base_model()
    db = derived_copy(tmp_path, model)
    monkeypatch.setattr(loader, "AUDIT_BATCH", 1)
    loader.audit(db, fetcher(model)[0], [48], minutes=1, clock=ticking(20), log=quiet)
    # A refresh moved Title 48 to 10-30 between runs: the rest is audited at 10-30.
    newer = copy.deepcopy(model)
    newer["titles"]["up_to_date_as_of"] = "2026-10-30"
    loader.refresh(db, fetcher(newer)[0], log=quiet)
    f, fake = fetcher(newer)
    loader.audit(db, f, [48], log=quiet)
    assert fake.calls == ["https://www.ecfr.gov/api/versioner/v1/full/2026-10-30/title-48.xml"
                          "?chapter=1&appendix=Appendix+A+to+Chapter+1"]
    # A move during a run: the batch fetched at the old date is not written, and the cursor stays.
    db2 = derived_copy(tmp_path / "second", model)
    before = node_rows(db2)
    fake2 = FakeEcfr(model)

    def moving(request):
        response = fake2(request)
        if len(fake2.calls) == 2:  # someone else moves the copy while Part 2 is being fetched
            newer_row = dict(model["titles"], up_to_date_as_of="2026-10-30")
            db2.execute(upserts_titles(newer_row))
        return response
    client = httpx.Client(transport=httpx.MockTransport(moving), base_url=loader.BASE)
    stats = loader.audit(db2, loader.Fetcher(client, sleep=lambda s: None), [48], log=quiet)
    assert "moved off 2026-10-29" in stats["stopped"]
    assert node_rows(db2) == before  # Part 2's fix, fetched at the old date, was not written
    assert cursor(db2)["after"] == P1 and cursor(db2)["done"] is False  # the next run redoes Part 2


def upserts_titles(row: dict) -> list[str]:
    text = loader.dumps(row)
    return loader.upserts("titles", ("number", "json", "hash"), ("number",), [[48, text, loader.sha(text)]])


def test_audit_skips_title_48_unless_named(built):
    model, _, db, _ = built
    f, fake = fetcher(model)
    stats = loader.audit(db, f, None, log=quiet)
    assert stats["plan"] == [] and fake.calls == []


def test_audit_remote_sums_rows_written_respects_the_cap_and_keeps_work_on_a_403(tmp_path):
    model = base_model()
    rec = write_recording(tmp_path / "derived-rec", model)
    part2 = rec / "parts/title-48/part-2.xml"
    part2.write_text(part2.read_text().replace(f"48 CFR {SG}", "48 CFR Part 2 Definitions"))
    fake_d1 = FakeD1()
    loader.build(remote(fake_d1), rec, log=quiet)
    # The cap: Part 2's fix would pass --max-rows 1, so nothing of it is written.
    with pytest.raises(loader.RowCap):
        loader.audit(remote(fake_d1, max_rows=1), fetcher(model)[0], [48], log=quiet)
    group = f"{P2}/subject_group:{SG}"
    stale = fake_d1.db.execute("SELECT meta FROM nodes WHERE key = ?", (group,)).fetchone()[0]
    assert "Part 2 Definitions" in stale
    # eCFR refuses (403) after Part 2: the fix is written, the cursor saved, then the run stops.
    fake = FakeEcfr(model)

    def refusing(request):
        if len(fake.calls) == 2:
            fake.calls.append(str(request.url))
            return httpx.Response(403, text="forbidden")
        return fake(request)
    client = httpx.Client(transport=httpx.MockTransport(refusing), base_url=loader.BASE)
    db = remote(fake_d1)
    with pytest.raises(loader.Stop):
        loader.audit(db, loader.Fetcher(client, sleep=lambda s: None), [48], log=quiet)
    assert db.rows_written == 3  # the node, meta version, the cursor
    fixed = fake_d1.db.execute("SELECT meta FROM nodes WHERE key = ?", (group,)).fetchone()[0]
    assert f"48 CFR {SG}" in fixed
    saved = json.loads(fake_d1.db.execute("SELECT value FROM meta WHERE key = 'audit_cursor'").fetchone()[0])
    assert saved["after"] == P2
