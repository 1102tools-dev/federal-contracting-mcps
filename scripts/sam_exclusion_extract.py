"""Stream the keyless SAM.gov Exclusions/Public V2 extract.

The real 2026-10-10 V2 file is quoted, comma-delimited CSV (not the pipe
layout used by entity registration). No sensitive/FOUO extracts are supported.
All source records are retained, including individual and cross-reference rows.
"""
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import zipfile

HEADERS = (
    "Classification", "Name", "Prefix", "First", "Middle", "Last", "Suffix",
    "Address 1", "Address 2", "Address 3", "Address 4", "City", "State / Province",
    "Country", "Zip Code", "Open Data Flag", "Blank (Deprecated)",
    "Unique Entity ID", "Exclusion Program", "Excluding Agency", "CT Code",
    "Exclusion Type", "Additional Comments", "Active Date", "Termination Date",
    "Record Status", "Cross-Reference", "SAM Number", "CAGE", "NPI", "Creation_Date",
)
FIELD_MAP = {
    "SAM Number": "exclusion_id", "Unique Entity ID": "uei", "CAGE": "cage_code",
    "Name": "name", "First": "first_name", "Middle": "middle_name",
    "Last": "last_name", "Suffix": "suffix", "Classification": "classification",
    "Exclusion Type": "exclusion_type", "Exclusion Program": "exclusion_program",
    "Excluding Agency": "excluding_agency_code", "Record Status": "record_status",
    "Address 1": "address_line_1", "City": "city", "State / Province": "state",
    "Zip Code": "zip_code", "Country": "country", "Additional Comments": "description",
}


def _date(value, field, line):
    if value is None:
        return None
    try:
        result = dt.date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError("noncanonical ISO date")
        return result.isoformat()
    except ValueError as exc:
        raise ValueError(f"Exclusions line {line}: invalid {field}: {value!r}") from exc


def _rows(stream):
    reader = csv.reader(stream, strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("Empty exclusions extract") from exc
    if tuple(header) != HEADERS:
        raise ValueError("Exclusions V2 header changed; refusing to load")
    count = 0
    # Stable source IDs are unique in the real file. Reject duplicates instead
    # of silently overwriting data; differing actions receive deterministic IDs.
    seen = {}
    for values in reader:
        line = reader.line_num
        if len(values) != len(HEADERS):
            raise ValueError(f"Exclusions line {line}: expected {len(HEADERS)} columns, got {len(values)}")
        source = {key: (value.strip() or None) for key, value in zip(HEADERS, values)}
        if not source["Classification"] or not source["Record Status"]:
            raise ValueError(f"Exclusions line {line}: missing classification or record status")
        row = {target: source[key] for key, target in FIELD_MAP.items()}
        if not row["name"]:
            row["name"] = " ".join(source[key] for key in ("First", "Middle", "Last", "Suffix") if source[key]) or None
        if not row["name"]:
            raise ValueError(f"Exclusions line {line}: missing excluded party name")
        digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        identifier = row["exclusion_id"] or digest
        if identifier in seen:
            if seen[identifier] == digest:
                raise ValueError(f"Exclusions line {line}: duplicate source record {identifier}")
            identifier = identifier + ":" + digest
            if identifier in seen:
                raise ValueError(f"Exclusions line {line}: duplicate source action")
        seen[identifier] = digest
        row["exclusion_id"] = identifier
        row["activation_date"] = _date(source["Active Date"], "Active Date", line)
        indefinite = source["Termination Date"] == "Indefinite"
        row["termination_date"] = None if indefinite else _date(source["Termination Date"], "Termination Date", line)
        row["creation_date"] = _date(source["Creation_Date"], "Creation_Date", line)
        row["last_update_date"] = None  # Not published in the public CSV.
        row["excluding_agency_name"] = None  # Source publishes the code, not the full agency name.
        row["address_line_2"] = ", ".join(source[key] for key in ("Address 2", "Address 3", "Address 4") if source[key]) or None
        row["record_json"] = {
            "exclusionIdentification": {"ueiSAM": row["uei"], "cageCode": row["cage_code"],
                                        "entityName": row["name"], "firstName": row["first_name"],
                                        "middleName": row["middle_name"], "lastName": row["last_name"],
                                        "suffix": row["suffix"], "prefix": source["Prefix"], "npi": source["NPI"]},
            "exclusionDetails": {"classificationType": row["classification"],
                                 "exclusionType": row["exclusion_type"],
                                 "exclusionProgram": row["exclusion_program"],
                                 "excludingAgencyCode": row["excluding_agency_code"]},
            "exclusionActions": {"listOfActions": [{"recordStatus": row["record_status"],
                                                    "activateDate": row["activation_date"],
                                                    "terminationDate": row["termination_date"],
                                                    "terminationType": "Indefinite" if indefinite else ("Definite" if row["termination_date"] else None)}]},
            "exclusionPrimaryAddress": {"addressLine1": row["address_line_1"],
                                 "addressLine2": row["address_line_2"], "city": row["city"],
                                 "stateOrProvinceCode": row["state"], "zipCode": row["zip_code"],
                                 "countryCode": row["country"]},
            "exclusionOtherInformation": {"additionalComments": row["description"], "ctCode": source["CT Code"]},
            "publicExtract": {"crossReference": source["Cross-Reference"], "samNumber": source["SAM Number"],
                              "creationDate": row["creation_date"]},
        }
        count += 1
        yield row
    if not count:
        raise ValueError("Exclusions extract has no records")


def iter_rows(path):
    """Yield normalized public records from CSV or its public ZIP, failing closed.

    Callers must exhaust the iterator before publishing. CSV has no count
    trailer, so the loader's minimum count/keep-ratio checks remain essential.
    ZIP CRC is checked while streaming each member to its end.
    """
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1:
                raise ValueError("Expected exactly one exclusions CSV member")
            member = members[0]
            if (Path(member.filename).name != member.filename or
                    not member.filename.startswith("SAM_Exclusions_Public_Extract_V2_") or
                    not member.filename.upper().endswith(".CSV")):
                raise ValueError("ZIP does not contain an expected public exclusions V2 CSV")
            with archive.open(member) as binary, io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
                yield from _rows(stream)
    else:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield from _rows(stream)
