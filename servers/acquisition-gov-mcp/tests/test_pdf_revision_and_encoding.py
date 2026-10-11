"""Confirmed NASA revision-date and GSA outlined-text regressions, two PDFs only."""
from pathlib import Path

import pytest

from acquisition_gov_mcp import _pdf


FIXTURES = Path(__file__).parent / 'fixtures/content-round'


def read(name, start=1, end=2):
    return _pdf._read_pdf((FIXTURES / f'{name}.pdf').read_bytes(), page_start=start, page_end=end)


@pytest.mark.p1
def test_nasa_revision_a_uses_current_letterhead_date():
    text, status, _, fields, _, _ = read('nasa-part39-revisiona')
    assert status == 'complete'
    assert 'PCD 25-06A' in text and 'Revision A' in text
    assert fields['issuance_date'] == fields['effective_date'] == '2026-03-13'


@pytest.mark.p2
def test_nasa_revision_effective_as_dated_does_not_invent_date_outside_header_range():
    fields = read('nasa-part39-revisiona', 2, 2)[3]
    assert fields['issuance_date'] is None
    assert fields['effective_date'] is None


@pytest.mark.p1
def test_consecutive_revised_letterhead_dates_choose_last_date_before_body():
    pages = [(1, 'PCD 25-06A\nJuly 11, 2025\nMarch 13, 2026\nPURPOSE: Revision A updates the deviation.'),
             (2, 'EFFECTIVE DATE: This PCD is effective as dated.')]
    fields = _pdf._extract_document_fields(pages)
    assert fields['issuance_date'] == fields['effective_date'] == '2026-03-13'


@pytest.mark.p2
@pytest.mark.parametrize('pages', [
    [(1, 'July 11, 2025\nPURPOSE: Original deviation.'), (3, 'March 13, 2026\nLater attachment.')],
    [(1, 'July 11, 2025\nOriginal deviation.\nMarch 13, 2026\nHistorical discussion.')],
    [(1, 'Original letterhead\nJuly 11, 2025'), (2, 'March 13, 2026\nAttachment date')],
])
def test_nonconsecutive_attachment_or_body_date_does_not_override_letterhead(pages):
    assert _pdf._extract_document_fields(pages)['issuance_date'] == '2025-07-11'


@pytest.mark.p1
def test_gsa_outlined_words_are_disclosed_as_partial_without_incomplete_rule_fragments():
    text, status, warnings, _, _, _ = read('gsa-part8-supplement1')
    assert status == 'partial'
    assert any('Page 2 contains outlined text that could not be recovered' in warning for warning in warnings)
    assert 'Important words could not be extracted' in text
    assert 'Read the official PDF before deciding which rule applies' in text
    assert 'Makes the use of OFPP-' not in text
    assert 'contracts mandatory' not in text


@pytest.mark.p2
def test_ordinary_pdf_text_remains_complete_without_outlined_text_warning():
    text, status, warnings, _, _, _ = read('nasa-part39-revisiona')
    assert status == 'complete' and 'Revision A' in text
    assert not any('outlined text' in warning for warning in warnings)


@pytest.mark.p2
@pytest.mark.parametrize('origin', [(0, 0), (300, 700)])
def test_outlined_letter_detection_does_not_depend_on_position_on_page(monkeypatch, origin):
    x, y = origin
    glyph = [([x, y], b'm'), ([x + 2, y + 4, x + 6, y + 8, x + 9, y + 10], b'c'), ([], b'f')]

    class Page:
        def get_contents(self):
            return b'content'

    class Stream:
        operations = glyph * 60

    monkeypatch.setattr(_pdf, 'ContentStream', lambda contents, reader: Stream())
    assert _pdf._has_outlined_text(Page(), object()) is True
