"""Saved real public Exclusions V2 slice and strict malformed-input checks."""
import csv
import importlib.util
import io
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sam_exclusion_extract", ROOT / "scripts/sam_exclusion_extract.py")
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
FIXTURE = ROOT / "tests/fixtures/sam_public/exclusions_v2_26283_slice.csv"


def source_rows():
    with FIXTURE.open(encoding="utf-8", newline="") as stream:
        return list(csv.reader(stream))


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(rows)
    return path


def test_real_v2_slice_preserves_all_classifications_and_cross_references():
    rows = list(parser.iter_rows(FIXTURE))
    assert len(rows) >= 16
    assert {r["classification"] for r in rows} == {"Firm", "Individual", "Vessel", "Special Entity Designation"}
    assert len({r["exclusion_id"] for r in rows}) == len(rows)
    assert any(r["record_json"]["publicExtract"]["crossReference"] for r in rows)
    assert all(r["record_status"] == "Active" for r in rows)
    person = next(r for r in rows if r["classification"] == "Individual")
    assert person["name"] == "Simone Courtney Gueringer"
    assert person["activation_date"] == "2024-10-09"
    assert person["termination_date"] == "2028-10-23"
    assert person["last_update_date"] is None


def test_indefinite_is_explicit_in_action_not_an_invalid_iso_date():
    record = next(r for r in parser.iter_rows(FIXTURE) if r["uei"] == "XPZTY4KVJL51")
    assert record["name"] == "0DAY TECHNOLOGIES"
    assert record["termination_date"] is None
    action = record["record_json"]["exclusionActions"]["listOfActions"][0]
    assert action["terminationType"] == "Indefinite"
    assert record["excluding_agency_code"] == "OFAC"
    assert record["excluding_agency_name"] is None
    assert "excludingAgencyName" not in record["record_json"]["exclusionDetails"]
    assert record["country"] == "RUS"
    projection = record["record_json"]
    assert projection["exclusionIdentification"]["entityName"] == "0DAY TECHNOLOGIES"
    assert "name" not in projection["exclusionIdentification"]
    assert "npi" in projection["exclusionIdentification"]
    assert "prefix" in projection["exclusionIdentification"]
    assert "samNumber" not in projection["exclusionIdentification"]
    assert "exclusionAddress" not in projection
    assert projection["exclusionPrimaryAddress"]["countryCode"] == "RUS"
    assert "description" not in projection["exclusionDetails"]
    assert projection["exclusionOtherInformation"]["additionalComments"] == "Redacted for Security Reasons"
    assert "ctCode" in projection["exclusionOtherInformation"]


def test_zip_stream_matches_csv(tmp_path):
    path = tmp_path / "exclusions.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SAM_Exclusions_Public_Extract_V2_26283.CSV", FIXTURE.read_bytes())
    assert list(parser.iter_rows(path)) == list(parser.iter_rows(FIXTURE))


@pytest.mark.parametrize("member", ["../SAM_Exclusions_Public_Extract_V2_26283.CSV", "FOUO.CSV", "nested/SAM_Exclusions_Public_Extract_V2_26283.CSV"])
def test_zip_rejects_unsafe_or_non_public_member(tmp_path, member):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, FIXTURE.read_bytes())
    with pytest.raises(ValueError):
        list(parser.iter_rows(path))


def test_zip_rejects_multiple_data_members(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SAM_Exclusions_Public_Extract_V2_26283.CSV", FIXTURE.read_bytes())
        archive.writestr("second.csv", FIXTURE.read_bytes())
    with pytest.raises(ValueError):
        list(parser.iter_rows(path))


def test_header_change_rejected(tmp_path):
    rows = source_rows()
    rows[0][0] = "Classification V3"
    with pytest.raises(ValueError, match="header changed"):
        list(parser.iter_rows(write_rows(tmp_path / "bad.csv", rows)))


def test_short_row_and_unclosed_quote_rejected(tmp_path):
    rows = source_rows()
    rows[-1].pop()
    with pytest.raises(ValueError, match="expected 31 columns"):
        list(parser.iter_rows(write_rows(tmp_path / "bad.csv", rows)))
    path = tmp_path / "quote.csv"
    path.write_bytes(FIXTURE.read_bytes() + b'"unterminated')
    with pytest.raises(csv.Error):
        list(parser.iter_rows(path))


def test_invalid_date_rejected(tmp_path):
    rows = source_rows()
    rows[1][parser.HEADERS.index("Active Date")] = "2026-02-31"
    with pytest.raises(ValueError, match="invalid Active Date"):
        list(parser.iter_rows(write_rows(tmp_path / "bad.csv", rows)))


def test_duplicate_record_rejected(tmp_path):
    rows = source_rows()
    rows.append(rows[1])
    with pytest.raises(ValueError, match="duplicate source record"):
        list(parser.iter_rows(write_rows(tmp_path / "bad.csv", rows)))


def test_different_action_same_source_id_disambiguated(tmp_path):
    rows = source_rows()[:2]
    other = rows[1].copy()
    other[parser.HEADERS.index("Active Date")] = "2025-01-01"
    rows.append(other)
    records = list(parser.iter_rows(write_rows(tmp_path / "actions.csv", rows)))
    assert records[0]["exclusion_id"] != records[1]["exclusion_id"]
    assert records[1]["exclusion_id"].startswith(records[0]["exclusion_id"] + ":")


def test_header_only_rejected(tmp_path):
    with pytest.raises(ValueError, match="no records"):
        list(parser.iter_rows(write_rows(tmp_path / "empty.csv", source_rows()[:1])))


def test_real_firm_parity_pool_has_sixty_public_active_uei_records():
    rows = list(parser.iter_rows(FIXTURE.with_name("exclusions_v2_26283_firms.csv")))
    assert len(rows) == 60
    assert all(r["classification"] == "Firm" and r["uei"] and r["record_status"] == "Active" for r in rows)
    assert len({r["exclusion_id"] for r in rows}) == 60
