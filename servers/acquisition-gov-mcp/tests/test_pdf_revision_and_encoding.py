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
def test_consecutive_revised_letterhead_dates_choose_latest_date_before_body():
    pages = [(1, 'PCD 25-06A\nJuly 11, 2025\nMarch 13, 2026\nPURPOSE: Revision A updates the deviation.'),
             (2, 'EFFECTIVE DATE: This PCD is effective as dated.')]
    fields = _pdf._extract_document_fields(pages)
    assert fields['issuance_date'] == fields['effective_date'] == '2026-03-13'


@pytest.mark.p1
@pytest.mark.parametrize('date_lines', [
    'March 13, 2026\nJuly 11, 2025',
    'March 13, 2026\nJuly 11, 2025\nAugust 20, 2025',
    'March 13, 2026\nFebruary 30, 2026',
    'February 30, 2026\nMarch 13, 2026',
])
def test_adjacent_letterhead_dates_choose_latest_valid_value_regardless_of_order(date_lines):
    fields = _pdf._extract_document_fields([(1, f'PCD Revision A\n{date_lines}\nPURPOSE: Revised deviation.'),
                                            (2, 'EFFECTIVE DATE: This PCD is effective as dated.')])
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


@pytest.mark.p1
@pytest.mark.parametrize('name,expected_text', [
    ('dos-part1-letterhead', 'Acquisition Alert 25-17'),
    ('cftc-part12-supplement1-page3', 'CFTC Class Deviation RFO-2025-12'),
    ('doi-part5-page2', 'The DOI acquisition workforce shall follow the RFO part 5 model deviation text'),
])
def test_saved_readable_pages_remain_usable_without_whole_page_replacement(name, expected_text):
    text, status, warnings, _, total, end = read(name, 1, 1)
    assert total == end == 1
    assert status == 'complete'
    assert expected_text in ' '.join(text.split())
    if name == 'cftc-part12-supplement1-page3':
        assert 'DATE: August 20, 2025' in text
    assert not any('outlined text' in warning for warning in warnings)
    assert '[Parser notice:' not in text


@pytest.mark.p2
@pytest.mark.parametrize('origin', [(0, 0), (300, 700)])
@pytest.mark.parametrize('scale', [1, 0.5])
def test_outlined_letter_detection_does_not_depend_on_position_or_graphics_scale(monkeypatch, origin, scale):
    x, y = origin
    operations = [([scale, 0, 0, scale, 0, 0], b'cm')]
    for letter in range(60):
        left = x + letter * 6
        operations.extend([([left / scale, y / scale], b'm'),
                           ([(left + 2) / scale, (y + 4) / scale, (left + 6) / scale, (y + 8) / scale,
                             (left + 9) / scale, (y + 10) / scale], b'c'), ([], b'f')])

    class Page:
        def get_contents(self):
            return b'content'

        def extract_text(self):
            return ''

    class Stream:
        pass

    Stream.operations = operations

    monkeypatch.setattr(_pdf, 'ContentStream', lambda contents, reader: Stream())
    assert _pdf._has_outlined_text(Page(), object()) is True


@pytest.mark.p2
def test_dense_compact_vector_logo_is_not_treated_as_a_row_of_missing_words(monkeypatch):
    operations = []
    for shape in range(60):
        x, y = (shape % 10) * 3, (shape // 10) * 3
        operations.extend([([x, y], b'm'), ([x + 2, y + 4, x + 6, y + 8, x + 9, y + 10], b'c'), ([], b'f')])

    class Page:
        def get_contents(self):
            return b'content'

        def extract_text(self):
            return ''

    class Stream:
        pass

    Stream.operations = operations
    monkeypatch.setattr(_pdf, 'ContentStream', lambda contents, reader: Stream())
    assert _pdf._has_outlined_text(Page(), object()) is False


@pytest.mark.p2
@pytest.mark.parametrize('readable_characters,withhold', [(180, True), (181, False)])
def test_whole_page_withholding_requires_at_least_twenty_five_percent_missing_glyphs(monkeypatch, readable_characters, withhold):
    operations = []
    for letter in range(60):
        left = letter * 6
        operations.extend([([left, 100], b'm'),
                           ([left + 2, 104, left + 6, 108, left + 9, 110], b'c'), ([], b'f')])

    class Page:
        def get_contents(self):
            return b'content'

        def extract_text(self):
            return 'a' * readable_characters

    class Stream:
        pass

    Stream.operations = operations
    monkeypatch.setattr(_pdf, 'ContentStream', lambda contents, reader: Stream())
    # Sixty missing glyphs out of 240 total characters reaches 25%; one more
    # readable character must preserve the mostly readable page instead.
    assert _pdf._has_outlined_text(Page(), object()) is withhold
