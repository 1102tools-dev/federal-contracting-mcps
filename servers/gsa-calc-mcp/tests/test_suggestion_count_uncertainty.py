"""Suggestion counts keep the uncertainty reported by GSA's aggregation."""
import asyncio

import pytest
import gsa_calc_mcp.server as srv


@pytest.mark.parametrize('bound,approximate', [(5, True), (0, False), (-1, True), (None, True)])
def test_suggestion_counts_expose_source_uncertainty(monkeypatch, bound, approximate):
    aggregation = {'buckets': [{'key': 'Help Desk Specialist V', 'doc_count': 15}],
                   'sum_other_doc_count': 7}
    if bound is not None:
        aggregation['doc_count_error_upper_bound'] = bound

    async def source(*args, **kwargs):
        return {'aggregations': {'labor_category': aggregation},
                'hits': {'total': {'value': 160, 'relation': 'eq'}}}

    monkeypatch.setattr(srv, '_get', source)
    result = asyncio.run(srv.suggest_contains('labor_category', 'help desk'))
    assert result['suggestions'][0]['count'] == 15
    assert result['suggestions'][0]['count_is_approximate'] is approximate
    assert result['counts_are_approximate'] is approximate
    assert result['doc_count_error_upper_bound'] == bound
    assert result['truncated'] is True and result['other_records'] == 7
    if bound == 5:
        assert 'approximate' in result['_count_note'] and '5' in result['_count_note']
    if bound == 0:
        assert 'approximate' not in result.get('_count_note', '')


def test_bucket_uncertainty_does_not_hide_lower_bound_total(monkeypatch):
    async def source(*args, **kwargs):
        return {'aggregations': {'vendor_name': {'buckets': [],
                'doc_count_error_upper_bound': 5, 'sum_other_doc_count': 0}},
                'hits': {'total': {'value': 10000, 'relation': 'gte'}}}

    monkeypatch.setattr(srv, '_get', source)
    result = asyncio.run(srv.suggest_contains('vendor_name', 'systems'))
    assert result['total_matching_records_is_lower_bound']
    assert 'at least 10000' in result['_count_note']
    assert 'approximate' in result['_count_note']
