"""Content regressions from the full 2026-10-10 workflow audit."""
import asyncio
import pytest
from gsa_calc_mcp import server as srv


def call(name, **kwargs):
    return asyncio.run(srv.mcp.call_tool(name, kwargs)).structured_content


@pytest.mark.parametrize('field', ['labor_category', 'vendor_name', 'idv_piid'])
def test_suggestion_count_marks_gsa_lower_bound(monkeypatch, field):
    # Live engineer suggestion body: 10,000/gte, no wage_stats, 51k+ rows.
    async def upstream(qs):
        return {'hits': {'total': {'value': 10000, 'relation': 'gte'}},
                'aggregations': {field: {'buckets': [{'key': 'Engineer', 'doc_count': 100}],
                                         'sum_other_doc_count': 50000,
                                         'doc_count_error_upper_bound': 32}}}
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('suggest_contains', field=field, term='engineer')
    assert result['total_matching_records'] == 10000
    assert result['total_matching_records_is_lower_bound'] is True
    assert 'at least' in result['_count_note']
    # Summing approximate distributed terms buckets does not yield exact count.
    assert result['total_matching_records'] != 50100


def test_suggestion_exact_count_stays_exact(monkeypatch):
    async def upstream(qs):
        return {'hits': {'total': {'value': 651, 'relation': 'eq'}},
                'aggregations': {'idv_piid': {'buckets': [{'key': 'GS00F008DA', 'doc_count': 651}],
                                             'sum_other_doc_count': 0}}}
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('suggest_contains', field='idv_piid', term='GS00F008DA')
    assert result['total_matching_records'] == 651
    assert result['total_matching_records_is_lower_bound'] is False


@pytest.mark.parametrize('std', [0, None])
@pytest.mark.parametrize('proposed', [100, 150])
def test_unavailable_z_score_does_not_claim_zero(monkeypatch, std, proposed):
    async def upstream(qs):
        return {'hits': {'total': {'value': 20}}, 'aggregations': {
            'wage_stats': {'count': 20, 'avg': 100, 'std_deviation': std},
            'labor_category': {'buckets': [{'key': 'Engineer', 'doc_count': 20}], 'sum_other_doc_count': 0},
            'histogram_percentiles': {'values': {'25.0': 100, '50.0': 100, '75.0': 100}}}}
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('price_reasonableness_check', labor_category='Engineer', proposed_rate=proposed)
    assert result['analysis']['z_score'] is None
    assert 'standard deviation' in result['analysis']['z_score_reason']
    assert result['analysis']['delta_from_avg'] == proposed - 100


def test_missing_average_does_not_invent_zero_average(monkeypatch):
    async def upstream(qs):
        return {'hits': {'total': {'value': 20}}, 'aggregations': {
            'wage_stats': {'count': 20, 'std_deviation': 20},
            'labor_category': {'buckets': [{'key': 'Engineer', 'doc_count': 20}], 'sum_other_doc_count': 0}}}
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('price_reasonableness_check', labor_category='Engineer', proposed_rate=150)
    assert result['analysis']['z_score'] is None
    assert result['analysis']['delta_from_avg'] is None
    assert result['analysis']['delta_from_avg_pct'] is None


def mixed_population():
    # Live Systems Engineering search includes every title at a matching vendor.
    return {'hits': {'total': {'value': 535}}, 'aggregations': {
        'wage_stats': {'count': 535, 'avg': 120, 'std_deviation': 30},
        'histogram_percentiles': {'values': {'25.0': 90, '50.0': 120, '75.0': 150}},
        'labor_category': {'buckets': [
            {'key': 'Admin/IT Support II', 'doc_count': 2},
            {'key': 'Computer Systems Engineering Technician - Level I', 'doc_count': 2},
        ], 'sum_other_doc_count': 0}}}


def test_igce_discloses_cross_field_population(monkeypatch):
    async def upstream(qs): return mixed_population()
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('igce_benchmark', labor_category='Systems Engineering')
    assert result['population_scope']['off_title_matches_detected'] is True
    assert result['population_scope']['off_title_examples'] == [{'title': 'Admin/IT Support II', 'count': 2}]
    assert 'vendor names and contract numbers' in result['_note']
    assert result['total_rates'] == 535  # Preserve source stats, disclose scope.


def test_price_check_refuses_noncomparable_cross_field_verdict(monkeypatch):
    async def upstream(qs): return mixed_population()
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('price_reasonableness_check', labor_category='Systems Engineering', proposed_rate=200)
    assert result['status'] == 'MIXED_SEARCH_FIELDS'
    assert all(v is None for v in result['analysis'].values())
    assert 'exact_search' in result['message']


def test_exact_title_price_population_still_produces_analysis(monkeypatch):
    body = mixed_population()
    body['aggregations']['labor_category']['buckets'] = [
        {'key': 'Senior Systems Engineer I', 'doc_count': 535}]
    async def upstream(qs): return body
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('price_reasonableness_check', labor_category='Senior Systems Engineer I', proposed_rate=180)
    assert result['population_scope']['off_title_matches_detected'] is False
    assert result['population_scope']['exact_title_population_verified'] is True
    assert result['analysis']['z_score'] == 2.0


def test_title_scope_handles_keyword_wildcard(monkeypatch):
    body = mixed_population()
    body['aggregations']['labor_category']['buckets'] = [{'key': 'Systems Software Engineer', 'doc_count': 535}]
    async def upstream(qs): return body
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('igce_benchmark', labor_category='Systems*Engineer')
    assert result['population_scope']['off_title_matches_detected'] is False


@pytest.mark.parametrize('title_agg', [None, {}, {'buckets': [], 'sum_other_doc_count': 40},
    {'buckets': [], 'sum_other_doc_count': 0},
    {'buckets': [{'key': 15, 'doc_count': 535}], 'sum_other_doc_count': 0},
    {'buckets': [{'key': 'Systems Engineer', 'doc_count': 535}], 'sum_other_doc_count': 0, 'doc_count_error_upper_bound': 1}])
def test_incomplete_title_population_cannot_prove_comparability(monkeypatch, title_agg):
    body = mixed_population()
    body['aggregations']['labor_category'] = title_agg
    async def upstream(qs): return body
    monkeypatch.setattr(srv, '_get', upstream)
    result = call('price_reasonableness_check', labor_category='Systems Engineer', proposed_rate=180)
    assert result['status'] == 'UNVERIFIED_POPULATION'
    assert result['population_scope']['title_only_population_verified'] is False
    assert all(v is None for v in result['analysis'].values())
