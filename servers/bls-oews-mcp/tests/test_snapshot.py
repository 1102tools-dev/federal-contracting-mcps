# SPDX-License-Identifier: MIT
"""The bundled OEWS database: integrity, provenance, and golden values.

Tests marked golden pin values from the May 2025 release (published May 15,
2026), checked against the live BLS v1 API when that release was bundled.
They skip when a newer release is bundled; tests/test_live_parity.py checks
any release against the live API, and the automated refresh runs it before
publishing.
"""

from __future__ import annotations

import asyncio
import hashlib
from importlib import resources

import pytest

from bls_oews_mcp import constants, snapshot
from bls_oews_mcp.server import mcp


def _payload(result):
    return result.structured_content if hasattr(result, "structured_content") else result


def _bundled(name: str) -> bytes:
    return resources.files("bls_oews_mcp").joinpath("data", name).read_bytes()


def test_manifest_hash_matches_bundled_file():
    meta = snapshot.manifest()
    assert hashlib.sha256(_bundled(meta["file"])).hexdigest() == meta["file_sha256"]


def test_decompressed_database_matches_manifest():
    meta = snapshot.manifest()
    path = snapshot.database_path()
    assert path.stat().st_size == meta["database_bytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["database_sha256"]
    snapshot.verify()


def test_constants_match_bundled_release():
    meta = snapshot.manifest()
    assert constants.OEWS_CURRENT_YEAR == meta["data_year"]
    assert constants.OEWS_RELEASE_NAME == meta["release"]["description"]


def test_manifest_records_every_source():
    sources = snapshot.manifest()["sources"]
    assert set(sources) == {
        "oe.data.0.Current", "oe.area", "oe.industry", "oe.occupation",
        "oe.datatype", "oe.footnote", "oe.release",
    }
    for name, src in sources.items():
        assert src["url"] == f"https://download.bls.gov/pub/time.series/oe/{name}"
        assert len(src["sha256"]) == 64
        assert src["bytes"] > 0


@pytest.mark.golden
def test_release_counts():
    counts = snapshot.manifest()["counts"]
    assert counts == {
        "data_rows": 6_023_970, "cells": 370_172, "areas": 583,
        "industries": 444, "occupations": 1_104,
    }


@pytest.mark.golden
def test_golden_values():
    got = snapshot.lookup([
        "OEUN000000000000015125208",  # Software Developers, national hourly median
        "OEUN000000000000015125204",  # annual mean
        "OEUM004790000000015125201",  # DC metro employment
    ])
    assert got["OEUN000000000000015125208"] == ("65.38", [])
    assert got["OEUN000000000000015125204"] == ("148100", [])
    assert got["OEUM004790000000015125201"] == ("69060", [])


@pytest.mark.golden
def test_unreleased_cell_carries_its_footnote():
    value, notes = snapshot.lookup(["OEUM001018000000015125404"])["OEUM001018000000015125404"]
    assert value == "-"
    assert notes == [{"code": "8", "text": "Estimate not released."}]


@pytest.mark.golden
def test_top_coded_wage_footnote():
    value, notes = snapshot.lookup(["OEUM001054000000029121515"])["OEUM001054000000029121515"]
    assert value == "-"
    assert notes[0]["code"] == "5"
    assert "$239,200 per year" in notes[0]["text"]


def test_missing_and_malformed_series_return_none():
    got = snapshot.lookup(["OEUN000000000000099999904", "OEUN0000000", "OEUN000000000000015125299"])
    assert set(got.values()) == {None}


def test_ratio_datatypes_absent_at_national_scope():
    # 16/17 exist only at state/metro scope; national cells have no value.
    assert snapshot.lookup(["OEUN000000000000015125217"])["OEUN000000000000015125217"] is None
    assert snapshot.lookup(["OEUS510000000000015125217"])["OEUS510000000000015125217"] is not None


def test_lookup_handles_many_series():
    keys = [f"OEUN0000000000000{occ}04" for occ in constants.COMMON_SOC_CODES] * 40
    got = snapshot.lookup(keys)
    assert all(got[k] is not None for k in keys)


@pytest.mark.golden
def test_names():
    assert snapshot.occupation_name("151252") == "Software Developers"
    assert snapshot.area_name("0047900") == "Washington-Arlington-Alexandria, DC-VA-MD-WV"
    assert snapshot.area_name("5100000") == "Virginia"
    assert snapshot.occupation_name("999999") is None


def test_corrupt_cache_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setenv("BLS_OEWS_DATA_DIR", str(tmp_path))
    snapshot.database_path.cache_clear()
    try:
        first = snapshot.database_path()
        first.write_bytes(b"not a database")
        snapshot.database_path.cache_clear()
        again = snapshot.database_path()
        assert again == first
        assert hashlib.sha256(again.read_bytes()).hexdigest() == snapshot.manifest()["database_sha256"]
    finally:
        monkeypatch.undo()
        snapshot.database_path.cache_clear()


def test_source_block_cites_bls():
    src = snapshot.source()
    assert src["kind"] == "bundled_bls_oews_files"
    assert src["release"] == constants.OEWS_RELEASE_NAME
    assert src["published"] == snapshot.manifest()["sources"]["oe.data.0.Current"]["last_modified"]
    assert src["data_file"].endswith("/oe.data.0.Current")
    assert "cannot vouch for the data" in src["notice"]
    assert src["retrieved"] == snapshot.manifest()["retrieved"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_wage_data", {"occ_code": "151252"}),
        ("compare_metros", {"occ_code": "151252", "metro_codes": ["47900"]}),
        ("compare_occupations", {"occ_codes": ["151252"]}),
        ("igce_wage_benchmark", {"occ_code": "151252"}),
        ("detect_latest_year", {}),
        ("get_data_status", {}),
        ("list_common_soc_codes", {}),
        ("list_common_metros", {}),
    ],
)
def test_every_tool_result_cites_the_bundled_source(name, args):
    data = _payload(asyncio.run(mcp.call_tool(name, args)))
    assert data["source"]["kind"] == "bundled_bls_oews_files"


def test_data_status_needs_no_key():
    data = _payload(asyncio.run(mcp.call_tool("get_data_status", {})))
    assert data["status"] == "bundled"
    assert data["api_key_required"] is False
    assert data["data_year"] == constants.OEWS_CURRENT_YEAR
    assert set(data["sources"]) == set(snapshot.manifest()["sources"])


@pytest.mark.golden
def test_rse_datatypes_format_as_percent():
    data = _payload(asyncio.run(mcp.call_tool(
        "get_wage_data", {"occ_code": "151252", "datatypes": ["02", "05"]},
    )))
    assert data["wages"]["Employment RSE (%)"]["formatted"] == "0.6%"
    assert data["wages"]["Mean Wage RSE (%)"]["formatted"] == "0.4%"


@pytest.mark.golden
def test_names_in_results():
    data = _payload(asyncio.run(mcp.call_tool(
        "get_wage_data", {"occ_code": "151252", "scope": "metro", "area_code": "47900"},
    )))
    assert data["occ_title"] == "Software Developers"
    assert data["area_name"] == "Washington-Arlington-Alexandria, DC-VA-MD-WV"
