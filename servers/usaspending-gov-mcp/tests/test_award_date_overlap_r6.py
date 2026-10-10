"""Source award envelopes do not prove individual transactions in a month."""
import asyncio
import copy
import json
from pathlib import Path

import usaspending_gov_mcp.server as s

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/award_date_overlap_r6.json').read_text())
WINDOW = dict(awarding_agency='Department of Energy', naics_codes=['541715'],
              time_period_start='2025-08-01', time_period_end='2025-08-31')


def invoke(monkeypatch, tool, **args):
    capture = FIXTURE['search' if tool == 'search_awards' else 'count']
    async def send(method, path, *, params=None, body=None):
        assert method == 'POST'
        assert path == capture['url'].removeprefix('https://api.usaspending.gov')
        return json.dumps(copy.deepcopy(capture['raw'])).encode()
    monkeypatch.setattr(s, '_send', send)
    response = asyncio.run(s.mcp.call_tool(tool, args)).structured_content
    return response['result'] if set(response) == {'result'} else response


def test_monthly_award_list_explains_interval_match_and_action_recovery(monkeypatch):
    out = invoke(monkeypatch, 'search_awards', limit=100, **WINDOW)
    assert out['results'] == FIXTURE['search']['raw']['results']
    dates = FIXTURE['counterexample_transactions']['raw']
    assert dates['page_metadata']['hasNext'] is False
    assert not any('2025-08-01' <= r['action_date'] <= '2025-08-31' for r in dates['results'])
    assert any(r['Award ID'] == '89243218CNE000001' for r in out['results'])
    note = out['time_period_note'].lower()
    assert 'latest action' in note and 'first' in note and 'not' in note
    assert '2025-08-01' in note and '2025-08-31' in note
    assert 'spending_by_transaction' in note and 'paginat' in note


def test_count_retains_source_population_and_guides_distinct_action_awards(monkeypatch):
    out = invoke(monkeypatch, 'get_award_count', **WINDOW)
    assert out['results'] == FIXTURE['count']['raw']['results']
    assert out['results']['contracts'] == 15
    dated = FIXTURE['dated_transactions']['raw']
    assert dated['page_metadata']['hasNext'] is False
    assert len({r['Award ID'] for r in dated['results']}) == 9
    assert 'spending_by_transaction' in out['time_period_note']
    assert 'distinct' in out['time_period_note'].lower()


def test_explicit_new_awards_and_no_window_do_not_gain_overlap_note(monkeypatch):
    for args in [dict(WINDOW, date_type='new_awards_only'), dict(awarding_agency='Department of Energy')]:
        out = invoke(monkeypatch, 'search_awards', **args)
        assert out == FIXTURE['search']['raw']
