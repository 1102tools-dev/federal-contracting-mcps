# SPDX-License-Identifier: MIT
"""scripts/build_oews_db.py on synthetic BLS files (no network)."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_oews_db.py"
spec = importlib.util.spec_from_file_location("build_oews_db", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

NATIONAL = "OEUN0000000000000151252"
STATE = "OEUS5100000000000151252"


def _tsv(header: list[str], rows: list[list[str]]) -> str:
    return "\r\n".join("\t".join(r) for r in [header, *rows]) + "\r\n"


def _files(**overrides) -> dict[str, str]:
    data_rows = []
    for key in (NATIONAL, STATE):
        for i in range(1, 18):
            dt = f"{i:02d}"
            if key == NATIONAL and dt in ("16", "17"):
                continue
            value, note = ("-", "8") if (key == STATE and dt == "15") else (f"{i}.50", "")
            data_rows.append([f"{key}{dt}     ", "2025", "A01", f"  {value}", note])
    files = {
        "oe.data.0.Current": _tsv(builder.HEADERS["oe.data.0.Current"], data_rows),
        "oe.area": _tsv(builder.HEADERS["oe.area"], [
            ["00", "0000000", "N", "National"], ["51", "5100000", "S", "Virginia"]]),
        "oe.industry": _tsv(builder.HEADERS["oe.industry"], [
            ["000000", "Cross-Industry", "0", "T", "0"]]),
        "oe.occupation": _tsv(builder.HEADERS["oe.occupation"], [
            ["151252", "Software Developers", "", "3", "T", "1"]]),
        "oe.datatype": _tsv(builder.HEADERS["oe.datatype"], [[f"{i:02d}", f"type {i}"] for i in range(1, 18)]),
        "oe.footnote": _tsv(builder.HEADERS["oe.footnote"], [["8", "Estimate not released."]]),
        "oe.release": _tsv(builder.HEADERS["oe.release"], [["2025A01", "May 2025"]]),
    }
    files.update(overrides)
    return files


@pytest.fixture
def source_dir(tmp_path, monkeypatch):
    src = tmp_path / "cache"
    src.mkdir()

    def write(files):
        for name, text in files.items():
            (src / name).write_bytes(text.encode("utf-8"))

    def fake_head(url):
        return {"last_modified": "2026-05-15", "etag": '"x"', "bytes": (src / url.rsplit("/", 1)[1]).stat().st_size}

    monkeypatch.setattr(builder, "head", fake_head)
    write(_files())
    return SimpleNamespace(path=src, write=write)


def _build(source_dir, out):
    out.mkdir(exist_ok=True)
    return builder.build(source_dir.path, out)


def test_build_pivots_and_records_provenance(source_dir, tmp_path):
    out = tmp_path / "out"
    manifest = _build(source_dir, out)
    assert manifest["counts"] == {"data_rows": 32, "cells": 2, "areas": 2, "industries": 1, "occupations": 1}
    assert manifest["release"]["description"] == "May 2025"
    assert manifest["sources"]["oe.area"]["last_modified"] == "2026-05-15"
    gz = out / manifest["file"]
    assert hashlib.sha256(gz.read_bytes()).hexdigest() == manifest["file_sha256"]
    db = tmp_path / "check.sqlite"
    db.write_bytes(gzip.decompress(gz.read_bytes()))
    assert hashlib.sha256(db.read_bytes()).hexdigest() == manifest["database_sha256"]
    con = sqlite3.connect(db)
    assert con.execute("SELECT v08, f08, v16 FROM cell WHERE key = ?", (NATIONAL,)).fetchone() == ("8.50", None, None)
    assert con.execute("SELECT v15, f15 FROM cell WHERE key = ?", (STATE,)).fetchone() == ("-", "8")
    assert dict(con.execute("SELECT name, value FROM meta"))["release_code"] == "2025A01"
    assert json.loads((out / "manifest.json").read_text()) == manifest


def test_build_is_deterministic(source_dir, tmp_path):
    a = _build(source_dir, tmp_path / "a")
    b = _build(source_dir, tmp_path / "b")
    assert a["file_sha256"] == b["file_sha256"]
    assert a["database_sha256"] == b["database_sha256"]


@pytest.mark.parametrize(
    "override,message",
    [
        ({"oe.area": _tsv(["state", "area_code", "areatype_code", "area_name"], [])}, "header changed"),
        ({"oe.release": _tsv(builder.HEADERS["oe.release"], [["2025A01", "May 2025"], ["2024A01", "May 2024"]])},
         "one release row"),
        ({"oe.area": _tsv(builder.HEADERS["oe.area"], [["00", "0000000", "N", "National"]])}, "missing from oe.area"),
        ({"oe.footnote": _tsv(builder.HEADERS["oe.footnote"], [["1", "other"]])}, "missing from oe.footnote"),
        ({"oe.datatype": _tsv(builder.HEADERS["oe.datatype"], [["01", "Employment"]])}, "differ from 01-17"),
    ],
)
def test_schema_drift_fails_the_build(source_dir, tmp_path, override, message):
    source_dir.write(override)
    with pytest.raises(builder.BuildError, match=message):
        _build(source_dir, tmp_path / "out")


def test_wrong_release_year_in_data_fails(source_dir, tmp_path):
    files = _files()
    source_dir.write({"oe.data.0.Current": files["oe.data.0.Current"].replace("\t2025\t", "\t2024\t", 1)})
    with pytest.raises(builder.BuildError, match="not the 2025A01 release"):
        _build(source_dir, tmp_path / "out")


def test_count_swing_against_prior_build_fails(source_dir, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps({"counts": {"data_rows": 1000, "cells": 2, "areas": 2, "occupations": 1}}))
    with pytest.raises(builder.BuildError, match="data_rows changed by more than 10%"):
        builder.build(source_dir.path, out)


def test_failed_build_leaves_published_data_untouched(source_dir, tmp_path):
    out = tmp_path / "out"
    first = _build(source_dir, out)
    source_dir.write({"oe.footnote": _tsv(builder.HEADERS["oe.footnote"], [["1", "other"]])})
    assert builder.main(["--cache", str(source_dir.path), "--out", str(out)]) == 1
    assert json.loads((out / "manifest.json").read_text()) == first
    assert not list(out.glob(".oews-*"))
