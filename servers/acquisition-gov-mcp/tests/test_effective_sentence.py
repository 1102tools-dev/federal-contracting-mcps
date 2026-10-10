"""Explicit effective-date sentence in the official DoD Part 1 deviation."""
import pytest
from acquisition_gov_mcp import _pdf

@pytest.mark.p2
@pytest.mark.parametrize('line', [
    'Effective February 1, 2026, contracting officers shall use the revised FAR.',
    '  Effective February 1, 2026, contracting officers shall use the revised FAR.',
    'Effective\nFebruary 1, 2026, contracting officers shall use the revised FAR.',
])
def test_explicit_effective_sentence_is_document_metadata(line):
    fields=_pdf._extract_document_fields([(1,line)])
    assert fields['effective_date']=='2026-02-01'
    assert fields['issuance_date'] is None

@pytest.mark.p2
@pytest.mark.parametrize('line', [
    'The prior deviation became effective February 1, 2026.',
    'The quoted memo was effective February 1, 2026.',
    'Effective immediately, following February 1, 2026 discussions.',
    'Effective upon contract award on February 1, 2026.',
    'Effective February 30, 2026, contracting officers shall use the revised FAR.',
    '"Effective February 1, 2026," said the earlier memo.',
])
def test_narrative_conditional_invalid_or_quoted_effective_date_is_not_metadata(line):
    assert _pdf._extract_document_fields([(1,line)])['effective_date'] is None
