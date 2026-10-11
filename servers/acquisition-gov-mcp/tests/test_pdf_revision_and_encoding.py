"""Confirmed NASA revision-date and GSA outlined-text regressions, two PDFs only."""
from pathlib import Path
import re

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
def test_gsa_outlined_required_use_text_is_recovered_and_disclosed(monkeypatch):
    calls = []

    def recover(body, page_number, *, timeout):
        calls.append((page_number, timeout))
        assert body.startswith(b'%PDF')
        return 'Makes the use of OFPP-designated “Required Use” contracts mandatory.'

    monkeypatch.setattr(_pdf, '_ocr_outlined_page', recover)
    text, status, warnings, _, _, _ = read('gsa-part8-supplement1')
    assert status == 'complete'
    assert 'OFPP-designated “Required Use” contracts mandatory' in text
    assert [number for number, _ in calls] == [1, 2], 'both saved pages contain letters drawn as outlines'
    assert all(0 < timeout <= 20 for _, timeout in calls)
    assert any('recovered with OCR' in warning and 'Page 2' in warning for warning in warnings)
    assert any('struck-through or superseded wording' in warning for warning in warnings)


@pytest.mark.p1
def test_gsa_outlined_words_missing_without_ocr_are_not_claimed_complete(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError('OCR tools unavailable')

    monkeypatch.setattr(_pdf, '_ocr_outlined_page', unavailable)
    _, status, warnings, _, _, _ = read('gsa-part8-supplement1')
    assert status == 'partial'
    assert any('Page 2 contains outlined text that could not be recovered' in warning for warning in warnings)


@pytest.mark.p1
def test_gsa_saved_official_pdf_recovers_actual_required_use_text_with_ocr():
    text, status, warnings, _, _, _ = read('gsa-part8-supplement1', 2, 2)
    normalized = ' '.join(re.sub(r'-\s*\n\s*', '-', text).split()).casefold()
    assert status == 'complete'
    assert re.search(r'ofpp[-\s]+designated\s+["“]?required use["”]?\s+contracts', normalized)
    assert 'mandatory' in normalized
    assert any('recovered with OCR' in warning for warning in warnings)
    assert any('struck-through or superseded wording' in warning for warning in warnings)


@pytest.mark.p2
def test_ordinary_pdf_text_does_not_invoke_ocr(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('ordinary extractable text must not trigger OCR')

    monkeypatch.setattr(_pdf, '_ocr_outlined_page', unexpected)
    text, status, warnings, _, _, _ = read('nasa-part39-revisiona')
    assert status == 'complete' and 'Revision A' in text
    assert not any('outlined text' in warning or 'recovered with OCR' in warning for warning in warnings)


@pytest.mark.p2
@pytest.mark.parametrize('separate_ranges', [False, True], ids=['one-range', 'repeated-single-pages'])
def test_outlined_text_recovery_shares_four_page_document_budget_and_resets_for_new_document(monkeypatch, separate_ranges):
    class Page:
        def get_contents(self):
            return None

        def extract_text(self):
            return 'Original extractable fragment'

    class Reader:
        is_encrypted = False
        pages = [Page() for _ in range(5)]

    calls = []

    def recover(body, page_number, *, timeout):
        calls.append(page_number)
        return f'Recovered text on page {page_number}'

    monkeypatch.setattr(_pdf, 'PdfReader', lambda _: Reader())
    monkeypatch.setattr(_pdf, '_has_outlined_text', lambda page, reader: True)
    monkeypatch.setattr(_pdf, '_ocr_outlined_page', recover)
    body = bytes(bytearray(b'first PDF fixture'))
    if separate_ranges:
        results = [_pdf._read_pdf(body, page_start=number, page_end=number) for number in range(1, 6)]
        assert all(result[1] == 'complete' for result in results[:4])
        text, status, warnings, _, _, _ = results[-1]
    else:
        text, status, warnings, _, _, _ = _pdf._read_pdf(body, page_start=1, page_end=5)
    assert calls == [1, 2, 3, 4]
    assert status == 'partial'
    assert '[Page 5]\nOriginal extractable fragment' in text
    assert any('Page 5 contains outlined text that could not be recovered' in warning for warning in warnings)
    new_body = bytes(bytearray(b'second PDF fixture'))
    _, status, warnings, _, _, _ = _pdf._read_pdf(new_body, page_start=5, page_end=5)
    assert calls == [1, 2, 3, 4, 5]
    assert status == 'complete'
    assert not any('could not be recovered' in warning for warning in warnings)


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


@pytest.mark.p1
@pytest.mark.parametrize('phase', ['initialization', 'inference'])
def test_missing_ocr_model_cannot_download_and_scoped_block_is_restored(monkeypatch, phase):
    import logging
    import rapidocr
    import requests
    from rapidocr.utils.download_file import DownloadFile

    attempts = []
    original_request = DownloadFile._make_http_request.__func__

    def unexpected_request(*args, **kwargs):
        raise AssertionError('OCR model initialization attempted network access')

    class LazyModel:
        def __call__(self, image):
            attempts.append('inference')
            return DownloadFile._make_http_request('https://example.invalid/missing-model.onnx', logging.getLogger(__name__))

    def missing_model(**kwargs):
        attempts.append('initialize')
        if phase == 'initialization':
            return DownloadFile._make_http_request('https://example.invalid/missing-model.onnx', logging.getLogger(__name__))
        return LazyModel()

    monkeypatch.setattr(_pdf, '_OCR_ENGINE', None)
    monkeypatch.setattr(rapidocr, 'RapidOCR', missing_model)
    monkeypatch.setattr(requests, 'get', unexpected_request)
    body = (FIXTURES / 'gsa-part8-supplement1.pdf').read_bytes()
    with pytest.raises(RuntimeError, match='downloads are disabled'):
        _pdf._ocr_outlined_page(body, 2, timeout=8)
    assert attempts == (['initialize'] if phase == 'initialization' else ['initialize', 'inference'])
    assert DownloadFile._make_http_request.__func__ is original_request
