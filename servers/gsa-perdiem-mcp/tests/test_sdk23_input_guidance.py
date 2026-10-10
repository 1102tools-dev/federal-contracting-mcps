"""Visible ordinary travel recovery and the anticipated/unexpected error boundary."""
import asyncio
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver import exceptions as mcp_errors

_UNEXPECTED_TOOL_ERROR = getattr(mcp_errors, "UnexpectedToolError", ())
import gsa_perdiem_mcp.server as srv


@pytest.mark.parametrize('tool,bad,hint,recovery', [
    ('lookup_city_perdiem', {'city':'Boston','state':'Massachusetts','county':'Suffolk','fiscal_year':2027}, 'USPS', {'city':'Boston','state':'MA','county':'Suffolk','fiscal_year':2027}),
    ('estimate_travel_cost', {'city':'Boston','state':'MA','county':'Suffolk','fiscal_year':2027,'num_nights':3,'travel_month':'May 2027'}, 'exact month', {'city':'Boston','state':'MA','county':'Suffolk','fiscal_year':2027,'num_nights':3,'travel_month':'May'}),
])
def test_visible_guidance_and_bundled_trip_recovery(monkeypatch, tool, bad, hint, recovery):
    requests=[]
    async def no_provider(*args, **kwargs):
        requests.append((args,kwargs))
        raise AssertionError('Local input/recovery must not request provider data')
    monkeypatch.setattr(srv, '_get', no_provider)
    monkeypatch.delenv('PERDIEM_API_KEY', raising=False)
    with pytest.raises(ToolError) as exc:
        asyncio.run(srv.mcp.call_tool(tool, bad))
    assert not isinstance(exc.value, _UNEXPECTED_TOOL_ERROR)
    assert hint.lower() in str(exc.value).lower()
    result=asyncio.run(srv.mcp.call_tool(tool, recovery)).structured_content
    if tool=='estimate_travel_cost':
        assert result['lodging_total']==915
        assert result['mie_total']==322
        assert result['grand_total']==1237
    else:
        assert result['query']['fiscal_year']==2027
        assert result['mie_daily']==92
    assert requests==[]


@pytest.mark.parametrize('fault', [ValueError, RuntimeError])
def test_unexpected_handler_fault_stays_masked(monkeypatch, fault):
    async def broken(*args, **kwargs):
        raise fault('private implementation detail')
    monkeypatch.setattr(srv, '_lookup_city', broken)
    with pytest.raises(ToolError) as exc:
        asyncio.run(srv.mcp.call_tool('lookup_city_perdiem', {'city':'Boston','state':'MA','county':'Suffolk','fiscal_year':2027}))
    if _UNEXPECTED_TOOL_ERROR:
        assert isinstance(exc.value, _UNEXPECTED_TOOL_ERROR)
        assert 'private implementation detail' not in str(exc.value)
    else:
        # SDK 2.0 precedes crash masking; retain its causal failure semantics.
        assert 'private implementation detail' in str(exc.value)
    assert isinstance(exc.value.__cause__, fault)


def test_expected_input_error_keeps_valueerror_helper_compatibility():
    with pytest.raises(ValueError, match='USPS') as exc:
        srv._validate_state('Massachusetts')
    assert isinstance(exc.value, ToolError)
    assert not isinstance(exc.value, _UNEXPECTED_TOOL_ERROR)
