"""Ordinary cross-tool research mistakes must retain repair guidance."""
import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from sam_gov_mcp import server as srv


@pytest.mark.parametrize(
    "name, arguments, guidance",
    [
        (
            "search_contract_awards",
            {"piid": "N0001925G0003", "date_signed": "2026-10-05"},
            ["date_signed", "MM/DD/YYYY"],
        ),
        (
            "search_assistance_subawards",
            {"agency_code": "075"},
            ["four-digit", "CGAC"],
        ),
    ],
)
def test_registered_research_recovery_before_network(monkeypatch, name, arguments, guidance):
    async def no_network(*args, **kwargs):
        pytest.fail("Anticipated input recovery must precede the API request")

    monkeypatch.setattr(srv, "_get", no_network)
    # Opportunity dates are ISO; award dates are MM/DD/YYYY. Organization
    # hierarchy CGAC codes are not the four-digit assistance agency codes.
    with pytest.raises(ToolError) as error:
        asyncio.run(srv.mcp.call_tool(name, arguments))
    assert all(hint in str(error.value) for hint in guidance)


def test_unexpected_source_failure_is_not_classified_as_user_input(monkeypatch):
    async def broken_source(*args, **kwargs):
        raise ValueError("source response decode failed")

    monkeypatch.setattr(srv, "_get", broken_source)
    with pytest.raises(ToolError) as error:
        asyncio.run(srv.mcp.call_tool("lookup_psc_code", {"code": "R425"}))
    causes = []
    cause = error.value
    while cause is not None:
        causes.append(cause)
        cause = cause.__cause__
    assert any(type(cause) is ValueError for cause in causes)
    assert not any(isinstance(cause, srv.UserInputError) for cause in causes)
