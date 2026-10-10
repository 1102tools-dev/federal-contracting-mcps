"""Regression for GSA's current supplement preceding its original deviation."""
import pytest
from acquisition_gov_mcp import _pdf

HEADER = "Docusign Envelope ID: 385F63C5\nPage 1 of 2\n2/20/2026 | 11:48:46 GMT\nGSA Office of Governmentwide Policy\nRFO-2025-19\nSupplement 1"
ORIGINAL = "Page 1 of 9\n9/26/2025\nRFO-2025-19\nOriginal deviation"

@pytest.mark.p1
@pytest.mark.parametrize("pages", [[(1, HEADER)], [(1, HEADER), (3, ORIGINAL)]])
def test_timestamp_letterhead_identifies_current_supplement(pages):
    assert _pdf._extract_document_fields(pages)["issuance_date"] == "2026-02-20"

@pytest.mark.p2
def test_original_only_range_preserves_original_date():
    assert _pdf._extract_document_fields([(3, ORIGINAL)])["issuance_date"] == "2025-09-26"

@pytest.mark.p2
@pytest.mark.parametrize("line", ["Discussed on 2/20/2026 | 11:48:46 GMT", "2/20/2026 | not a timestamp", "2/20/2026 | 99:99:99 GMT"])
def test_narrative_and_malformed_timestamp_are_not_letterhead_dates(line):
    assert _pdf._extract_document_fields([(1, line)])["issuance_date"] is None
