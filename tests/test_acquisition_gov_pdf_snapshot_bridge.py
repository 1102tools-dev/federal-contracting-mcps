"""PDF fixes survive the loader representation consumed by the existing Worker."""
import importlib.util
import asyncio
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pdf_snapshot_bridge_loader', ROOT / 'scripts/load_acquisition_gov.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
FIXTURES = ROOT / 'servers/acquisition-gov-mcp/tests/fixtures/content-round'


def test_saved_nasa_revision_is_first_standalone_date_in_hosted_snapshot():
    parsed = loader.parse_pdf((FIXTURES / 'nasa-part39-revisiona.pdf').read_bytes())
    dates = parsed['info']['dates']['Standalone']
    assert dates[0][2] == '2026-03-13', 'the hosted Worker selects the first stored standalone date'
    first_page = parsed['pages'][0]
    assert 'July 11, 2025' in first_page['text'], 'the old date remains source text rather than current metadata'
    assert first_page['text'][dates[0][0]:dates[0][1]].strip() == 'March 13, 2026'


def test_snapshot_date_clusters_do_not_cross_a_page_boundary():
    cover = 'Original letterhead\nJuly 11, 2025'
    attachment = 'March 13, 2026\nAttachment date'
    pages = [{'start': 0, 'text': cover}, {'start': len(cover) + 1, 'text': attachment}]
    dates = loader.labeled_dates(cover + '\n' + attachment, pages)['Standalone']
    assert [date for _, _, date in dates] == ['2025-07-11', '2026-03-13']
    assert dates[1][0] == len(cover) + 1


def test_snapshot_adjacent_dates_choose_latest_value_before_worker_first_match_selection():
    text = 'PCD Revision A\nMarch 13, 2026\nJuly 11, 2025\nAugust 20, 2025\nPURPOSE: Revised deviation.'
    dates = loader.labeled_dates(text, [{'start': 0, 'text': text}])['Standalone']
    assert len(dates) == 1
    start, end, date = dates[0]
    assert date == '2026-03-13'
    assert text[start:end].strip() == 'March 13, 2026'


def test_saved_gsa_incomplete_rules_are_replaced_with_explanation_and_official_link():
    source_url = 'https://www.acquisition.gov/sites/default/files/page_file_uploads/GSA_RFO_Deviation_Part-8_Supplement-1.pdf'
    parsed = loader.parse_pdf((FIXTURES / 'gsa-part8-supplement1.pdf').read_bytes(), source_url=source_url)
    assert len(parsed['pages']) == 2
    assert parsed['pages'][1]['failure'], 'the audited Required Use replacement words are missing on page 2'
    for page in (page for page in parsed['pages'] if page['failure']):
        assert 'Important words drawn as outlines could not be extracted' in page['failure']
        assert f'Read the official PDF: {source_url}' in page['failure']
        assert page['text'] == '', 'empty extraction makes the existing Worker report an incomplete status'


@pytest.mark.parametrize('source_url', [None, 'https://www.acquisition.gov/sites/default/files/page_file_uploads/GSA_RFO_Deviation_Part-8_Supplement-1.pdf'])
def test_snapshot_missing_outlined_words_explain_failure_and_link_to_official_pdf(monkeypatch, source_url):
    warning = 'Page 1 contains outlined text that could not be recovered; important words may be missing. Consult the official PDF.'

    def missing(body, start, end):
        return ['[Page 1]\nMakes the use of OFPP-\ncontracts mandatory.', 'partial', [warning], {}, 1, 1]

    monkeypatch.setattr(loader, 'read_pdf', missing)
    page = loader.parse_pdf(b'saved fixture', source_url=source_url)['pages'][0]
    assert 'Important words drawn as outlines could not be extracted' in page['failure']
    assert 'rules may be missing' in page['failure']
    assert page['text'] == '', 'the malformed rule fragment must not be served'
    if source_url:
        assert f'Read the official PDF: {source_url}' in page['failure']
    else:
        assert 'source_url link in this tool response' in page['failure']


def test_snapshot_storage_supplies_final_pdf_url_to_failure_notice(tmp_path, monkeypatch):
    final_url = 'https://www.acquisition.gov/sites/default/files/page_file_uploads/GSA_RFO_Deviation_Part-8_Supplement-1.pdf'
    warning = 'Page 1 contains outlined text that could not be recovered; important words may be missing. Consult the official PDF.'

    def missing(body, start, end):
        return ['[Page 1]\nIncomplete contract rule.', 'partial', [warning], {}, 1, 1]

    async def parse(kind, body, **arguments):
        assert kind == 'pdf'
        assert arguments == {'source_url': final_url}
        return loader.parse_pdf(body, **arguments)

    monkeypatch.setattr(loader, 'read_pdf', missing)
    monkeypatch.setattr(loader, 'parse', parse)
    db = loader.LocalD1(tmp_path / 'snapshot.sqlite')
    instance = loader.Loader(db, loader.Fetcher(), log=lambda _: None)
    _, snapshot = instance.setup()
    fetched = {'url': 'https://www.acquisition.gov/sites/default/files/page_file_uploads/posted-link.pdf',
               'final_url': final_url, 'fetched_at': '2026-10-11T00:00:00+00:00',
               'sha256': 'a' * 64, 'body': b'saved fixture'}
    row = asyncio.run(instance.store(snapshot, 'pdf:posted-link', fetched, 'agency-deviation', 'pdf'))
    page = db.query('SELECT body,failure FROM pages WHERE doc=?', [row['doc']])[0]
    assert row['doc'] == loader.doc_id('pdf', fetched['sha256']), 'the explanatory URL must not change content identity'
    assert 'Important words drawn as outlines could not be extracted' in page['failure']
    assert f'Read the official PDF: {final_url}' in page['failure']
    assert page['body'] == '', 'only the explanatory failure warning may reach the hosted response'
