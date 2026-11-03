"""IDV tools accept the ids AI clients actually send (Nov 3, 2026).

The Claude directory showed get_idv_amounts failing on 31.7% of calls: clients
passed the numeric internal_id that lookup_piid lists first, or the bare PIID.
USAspending's IDV endpoints accept the numeric id, and a bare PIID is resolved
to its IDV. No network is used.
"""
import asyncio
import json

import pytest

import usaspending_gov_mcp.server as srv

IDV = "CONT_IDV_GS00Q14OADU131_4732"
SEARCH = "/api/v2/search/spending_by_award/"


class _Upstream:
    def __init__(self, idv_rows):
        self.idv_rows = idv_rows
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append((path, None))
        return {"award_id": 351200629}

    async def post(self, path, body):
        self.calls.append((path, body))
        if path == SEARCH:
            return {"results": self.idv_rows, "page_metadata": {"hasNext": False}}
        return {"results": [], "page_metadata": {}}

    def sent(self):
        return [(p, b) for p, b in self.calls if p != SEARCH]


def _setup(monkeypatch, idv_rows=()):
    up = _Upstream([{"generated_internal_id": g} for g in idv_rows])
    monkeypatch.setattr(srv, "_get", up.get)
    monkeypatch.setattr(srv, "_post", up.post)
    return up


def _structured(result):
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content
    if isinstance(result, tuple):
        return result[1]
    return json.loads(result.content[0].text)


def _call(tool, **kwargs):
    return asyncio.run(srv.mcp.call_tool(tool, kwargs))


def _error(tool, **kwargs):
    with pytest.raises(Exception) as caught:
        _call(tool, **kwargs)
    return str(caught.value)


def test_numeric_id_goes_upstream_unchanged(monkeypatch):
    up = _setup(monkeypatch)
    out = _structured(_call("get_idv_amounts", award_id="351200629"))
    assert up.sent() == [("/api/v2/idvs/amounts/351200629/", None)]
    assert not any(p == SEARCH for p, _ in up.calls)
    assert "award_id_note" not in out


@pytest.mark.parametrize("tool,path", [
    ("get_idv_funding", "/api/v2/idvs/funding/"),
    ("get_idv_funding_rollup", "/api/v2/idvs/funding_rollup/"),
    ("get_idv_activity", "/api/v2/idvs/activity/"),
])
def test_numeric_id_on_post_endpoints(monkeypatch, tool, path):
    up = _setup(monkeypatch)
    _call(tool, award_id=" 351200629 ")
    assert up.sent()[-1][0] == path
    assert up.sent()[-1][1]["award_id"] == "351200629"


def test_bare_piid_resolves_to_its_idv(monkeypatch):
    up = _setup(monkeypatch, [IDV])
    out = _structured(_call("get_idv_amounts", award_id="gs00q14oadu131"))
    search = [b for p, b in up.calls if p == SEARCH][0]
    assert search["filters"]["award_ids"] == ["GS00Q14OADU131", "gs00q14oadu131"]
    assert up.sent() == [(f"/api/v2/idvs/amounts/{IDV}/", None)]
    assert IDV in out["award_id_note"]


def test_bare_piid_on_children(monkeypatch):
    up = _setup(monkeypatch, [IDV])
    out = _structured(_call("get_idv_children", generated_idv_id="GS00Q14OADU131"))
    assert up.sent()[-1][1]["award_id"] == IDV
    assert IDV in out["award_id_note"]


def test_children_leaves_other_ids_alone(monkeypatch):
    up = _setup(monkeypatch)
    _call("get_idv_children", generated_idv_id=IDV)
    _call("get_idv_children", generated_idv_id="351200629")
    assert [b["award_id"] for _, b in up.sent()] == [IDV, "351200629"]
    assert not any(p == SEARCH for p, _ in up.calls)


def test_piid_matching_several_idvs_names_them(monkeypatch):
    _setup(monkeypatch, ["CONT_IDV_A1234_9700", "CONT_IDV_A1234_4732"])
    msg = _error("get_idv_amounts", award_id="A1234")
    assert "matches 2 IDVs" in msg
    assert "CONT_IDV_A1234_9700" in msg and "CONT_IDV_A1234_4732" in msg


def test_piid_with_no_idv_points_to_lookup_piid(monkeypatch):
    up = _setup(monkeypatch, [])
    msg = _error("get_idv_amounts", award_id="W912QR25C0022")
    assert "not an IDV PIID" in msg and "lookup_piid()" in msg
    assert up.sent() == []


def test_contract_id_and_words_keep_their_errors(monkeypatch):
    up = _setup(monkeypatch)
    assert "is not an IDV award id" in _error(
        "get_idv_amounts", award_id="CONT_AWD_W912QR25C0022_9700_-NONE-_-NONE-")
    assert "not a valid generated award id" in _error("get_idv_amounts", award_id="bogus")
    assert "path characters" in _error("get_idv_amounts", award_id="CONT_IDV_a/../b")
    assert up.calls == []
