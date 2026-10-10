"""Real captured deadline metadata must not establish a controlling legal date."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import pytest
import regulationsgov_mcp.server as srv

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/deadline_conflict_2026_10.json').read_text())


def replay(monkeypatch, tool, record):
    async def fake(path, params=None):
        if path.startswith('dockets/'):
            return {'data': {'attributes': {'title': 'Captured audit docket'}}}
        if path == 'comments':
            return {'data': [], 'meta': {'totalElements': 0}}
        if path.startswith('documents/'):
            return {'data': deepcopy(record)}
        return {'data': [deepcopy(record)], 'meta': {'totalElements': 1}}
    monkeypatch.setattr(srv, '_get', fake)
    args = {'get_document_detail': {'document_id': record['id']},
            'search_documents': {'docket_id': record['attributes']['docketId']},
            'far_case_history': {'docket_id': record['attributes']['docketId']},
            'open_comment_periods': {'agency_ids': [record['attributes'].get('agencyId', 'OSHA')]}}
    result = asyncio.run(srv.mcp.call_tool(tool, args[tool])).structured_content
    if tool in ('far_case_history', 'open_comment_periods'):
        row = result['documents'][0]
        return row['comment_deadline'], row['comment_end_date_utc'], row.get('comment_deadline_verification')
    row = result['data'][0] if tool == 'search_documents' else result['data']
    attrs = row['attributes']
    return attrs['commentDeadlineEastern'], attrs['commentEndDateUtc'], attrs.get('commentDeadlineVerification')


@pytest.mark.parametrize('tool', ['search_documents', 'get_document_detail', 'far_case_history', 'open_comment_periods'])
def test_conflicting_provider_date_cannot_establish_controlling_deadline(monkeypatch, tool):
    display, raw, verification = replay(monkeypatch, tool, FIXTURE['conflict'])
    # Preserve real provider data. A hard-coded October30 substitution is wrong too.
    assert display == 'Oct 2, 2025 11:59 PM ET'
    assert raw == FIXTURE['conflict']['attributes']['commentEndDate']
    assert verification is not None
    assert verification['status'] == 'source_metadata_only'
    assert verification['controlling_deadline_established'] is False
    assert verification['federal_register_notice_url'].endswith('/2025-18670.json')
    assert verification['docket_url'].endswith('/OSHA-2021-0009')
    # The linked primary fixture establishes the conditional answer, not metadata.
    dates = FIXTURE['provenance']['primary_dates_text']
    assert 'October 30, 2025' in dates and 'timely NOITA' in dates


@pytest.mark.parametrize('tool', ['search_documents', 'get_document_detail', 'far_case_history', 'open_comment_periods'])
def test_matching_normal_deadline_keeps_provider_date_and_notice_provenance(monkeypatch, tool):
    display, raw, verification = replay(monkeypatch, tool, FIXTURE['normal'])
    assert display == FIXTURE['normal_expected']
    assert raw == FIXTURE['normal']['attributes']['commentEndDate']
    assert verification is not None
    assert verification['controlling_deadline_established'] is False
    assert verification['federal_register_notice_url'].endswith('/2026-16311.json')


def test_undated_records_do_not_invent_deadline_or_verification():
    result = srv._compact_record({'id': 'OSHA-2021-0009-0001', 'attributes': {'title': 'No provider date'}})
    assert not any(key.startswith('commentDeadline') for key in result['attributes'])
