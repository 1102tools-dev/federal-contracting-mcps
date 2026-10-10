"""Ordinary corrective guidance stays visible; unrelated faults stay unexpected."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
import mcp.server.mcpserver.exceptions as sdk_errors
import federal_register_mcp.server as srv
from .test_round_6 import _call, _payload, _qs

FIXTURE = json.loads((Path(__file__).parent / "fixtures/sdk23_recovery_published15.json").read_text())

@pytest.mark.parametrize("bad,hint,recovery_index", [
    ({"cfr_part": "52", "pub_date_gte": "2026-01-01", "per_page": 5}, "requires cfr_title", 0),
    ({"cfr_title": 48, "cfr_part": "52.212-4", "term": "commercial", "per_page": 5}, "pass the part ('52')", 1),
    ({"agencies": ["federal-motor-carrier-safety-administration"], "pub_date_gte": "2024-01-01", "page": 51, "per_page": 5}, "50-page limit", 2),
])
def test_visible_guidance_then_valid_recovery(monkeypatch, bad, hint, recovery_index):
    seen = []
    recovery = FIXTURE[recovery_index]
    async def source(url):
        seen.append(url)
        return copy.deepcopy(recovery["response"])
    monkeypatch.setattr(srv, "_get", source)
    with pytest.raises(ToolError) as failure:
        asyncio.run(_call("search_documents", **bad))
    assert hint in str(failure.value)
    assert type(failure.value) is ToolError
    assert seen == []
    data = _payload(asyncio.run(_call("search_documents", **recovery["arguments"])))
    assert data["count"] == recovery["response"]["count"] > 0
    assert [x["document_number"] for x in data["results"]] == [x["document_number"] for x in recovery["response"]["results"]]
    assert len(seen) == 1
    wire = _qs(seen[0])
    if recovery_index < 2:
        assert wire["conditions[cfr][title]"] == ["48"]
        assert wire["conditions[cfr][part]"] == ["52"]
    else:
        assert wire["conditions[publication_date][gte]"] == ["2026-10-01"]
        assert wire["conditions[publication_date][lte]"] == ["2026-10-10"]
        assert wire["per_page"] == ["100"]


def test_direct_validator_keeps_valueerror_compatibility():
    with pytest.raises(ValueError, match="requires cfr_title"):
        srv._validate_cfr(None, "52")


@pytest.mark.parametrize("fault", [ValueError("untrusted parser detail"), RuntimeError("untrusted source detail")])
def test_unknown_source_fault_not_anticipated(monkeypatch, fault):
    async def source(url):
        raise fault
    monkeypatch.setattr(srv, "_get", source)
    with pytest.raises(ToolError) as failure:
        asyncio.run(_call("search_documents", term="commercial"))
    assert failure.value.__cause__ is fault
    # SDK2.0 predates crash masking; keep its existing behavior, and enforce
    # the SDK2.3 client contract wherever UnexpectedToolError is available.
    if hasattr(sdk_errors, "UnexpectedToolError"):
        assert type(failure.value) is sdk_errors.UnexpectedToolError
        assert str(failure.value) == "Error executing tool search_documents"
        assert "untrusted" not in str(failure.value)
