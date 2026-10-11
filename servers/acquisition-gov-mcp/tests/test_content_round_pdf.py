"""Confirmed content audit regressions on three saved official PDF excerpts."""
from pathlib import Path
import importlib.util
import pytest
from acquisition_gov_mcp import _pdf

FIXTURES = Path(__file__).parent / 'fixtures/content-round'
ROOT = Path(__file__).resolve().parents[3]


def read(name, start=1, end=3):
    return _pdf._read_pdf((FIXTURES / f'{name}.pdf').read_bytes(), page_start=start, page_end=end)


@pytest.mark.p1
def test_doe_unresolved_glyphs_are_not_claimed_as_complete():
    text, status, warnings, fields, _, _ = read('doe-part19')
    assert status == 'unextractable'
    assert '/i255' not in text
    assert any('unreadable font encoding' in w for w in warnings)
    assert fields['effective_date'] is None


@pytest.mark.p1
def test_hhs_current_immediate_date_and_full_scope():
    fields = read('hhs-amendment3')[3]
    assert fields['issuance_date'] == fields['effective_date'] == '2026-08-14'
    assert 'apply to all HHS Divisions' in fields['applicability_text']
    assert 'orders.' in fields['applicability_text']
    assert 'ROLES AND RESPONSIBILITIES' not in fields['applicability_text']


@pytest.mark.p1
def test_nasa_effective_as_dated_uses_selected_letterhead():
    assert read('nasa-part13')[3]['effective_date'] == '2025-12-19'
    assert read('nasa-part13', 2, 2)[3]['effective_date'] is None


@pytest.mark.p2
@pytest.mark.parametrize('text', [
    'Trade threshold rules became effective March 13, 2026.',
    'Final Rule, effective March 13, 2026.',
    'Prior memo says EFFECTIVE DATE: March 13, 2026.',
    'EFFECTIVE DATE: Immediately',
    'EFFECTIVE DATE: This PCD is effective as dated',
])
def test_historical_or_unanchored_effective_dates_stay_unknown(text):
    assert _pdf._extract_document_fields([(3, text)])['effective_date'] is None


@pytest.mark.p2
def test_numbered_explicit_effective_label():
    assert _pdf._extract_document_fields([(1, '1. EFFECTIVE DATE: March 13, 2026')])['effective_date'] == '2026-03-13'


@pytest.mark.p2
def test_numbered_paths_and_policy_numbers_are_readable(monkeypatch):
    class Page:
        def get_contents(self): return None
        def extract_text(self): return 'Paths: ' + '/1/2/3/4' * 30
    class Reader:
        is_encrypted = False
        pages = [Page()]
    monkeypatch.setattr(_pdf, 'PdfReader', lambda _: Reader())
    assert _pdf._read_pdf(b'x', page_start=1, page_end=1)[1] == 'complete'


@pytest.mark.p1
def test_loader_fields_match_selected_python_page_ranges():
    spec = importlib.util.spec_from_file_location('content_loader', ROOT / 'scripts/load_acquisition_gov.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    for name in ('doe-part19', 'hhs-amendment3', 'nasa-part13'):
        parsed = loader.parse_pdf((FIXTURES / f'{name}.pdf').read_bytes())
        for start, end in ((1, 3), (1, 1), (2, 2), (3, 3)):
            pages = [(p['page'], p['text']) for p in parsed['pages'] if start <= p['page'] <= end]
            assert _pdf._extract_document_fields(pages) == read(name, start, end)[3]

@pytest.mark.p2
def test_loader_retains_labeled_date_at_selected_page_boundary():
    spec = importlib.util.spec_from_file_location('boundary_loader', ROOT / 'scripts/load_acquisition_gov.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    text = 'First page\n\nIssued: March 13, 2026'
    start = text.index('Issued:')
    assert any(a >= start and date == '2026-03-13' for a, _, date in loader.labeled_dates(text)['Issued'])
    numbered = 'First page\n1. EFFECTIVE DATE: March 13, 2026'
    assert loader.labeled_dates(numbered)['Effective'][0][2] == '2026-03-13'
