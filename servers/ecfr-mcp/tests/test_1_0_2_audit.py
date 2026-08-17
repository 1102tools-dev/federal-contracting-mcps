# SPDX-License-Identifier: MIT
"""Round 6 external-audit regressions (shipped in 1.0.2).

The audit probed three blind spots the first five rounds never covered:
constants were validated against themselves rather than the live API, the
XML parser was tested for crash-robustness but never for content recall on
real section archetypes, and documented claims (params, env vars) were never
executed. Findings covered here:

- TITLE_48_CHAPTERS was missing nine live chapters (30=HSAR among them);
  the validator rejected real agency FAR supplements with a false error.
- Table content (FAR 1.106's 562-cell OMB table) was silently discarded.
- HD1-HD3, FP, and EDNOTE text was silently dropped.
- The documented appendix filter was not exposed on any tool.
- search_cfr hid the API's order and agency_slugs params and its docstring
  denied they existed.
- list_agencies summary_only stripped child agencies whose cfr_references
  are the only carriers of chapters 2/30/34/52/54/61.
- Trailing paragraph cites (section='15.305(a)') were forwarded verbatim
  and 404'd.
- compare_versions accepted dates before the 2017-01-03 history floor.
- USER_AGENT was pinned at a stale version string.

Tiers:
  1. Validation tests (offline, validators raise before any HTTP call)
  2. Mock tests (offline, swap _get_json/_get_xml to capture wire params)
  3. Live tests (MCP_LIVE_TESTS=1 or ECFR_LIVE_TESTS=1, hit production eCFR)
"""

from __future__ import annotations

import asyncio
import os

import pytest

import ecfr_mcp.server as srv
from ecfr_mcp.server import mcp
from ecfr_mcp.constants import SEARCH_ORDERS, TITLE_48_CHAPTERS

LIVE = os.environ.get("MCP_LIVE_TESTS") == "1" or os.environ.get("ECFR_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


async def _call_expect_error(name: str, match: str, **kwargs):
    try:
        await mcp.call_tool(name, kwargs)
    except Exception as e:
        assert match.lower() in str(e).lower(), f"expected {match!r}, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    if hasattr(result, "structured_content"):
        return result.structured_content
    return result[1] if isinstance(result, tuple) else result


class _CaptureJson:
    """Swap _get_json for a canned response, recording every call."""

    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None, timeout=15):
        self.calls.append((path, dict(params or {})))
        return self.response


class _CaptureXml:
    def __init__(self, response="<DIV8><HEAD>h</HEAD><P>p</P></DIV8>"):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.response


# ===========================================================================
# TIER 1: VALIDATION (offline)
# ===========================================================================

# The nine chapters round 6 found live in eCFR but missing from the map.
_ROUND6_CHAPTERS = ("17", "19", "21", "30", "34", "52", "54", "57", "61")


@pytest.mark.parametrize("ch", _ROUND6_CHAPTERS)
def test_restored_title48_chapters_accepted(ch):
    assert srv._validate_chapter(ch, title_number=48) == ch
    assert ch in TITLE_48_CHAPTERS


@pytest.mark.parametrize("ch", ["0", "11", "27", "62", "100"])
def test_nonexistent_title48_chapters_still_rejected(ch):
    with pytest.raises(ValueError, match="not a valid Title 48 chapter"):
        srv._validate_chapter(ch, title_number=48)


def test_chapter_16_label_is_fehbar_not_opmar():
    assert "FEHBAR" in TITLE_48_CHAPTERS["16"]
    assert "OPMAR" not in TITLE_48_CHAPTERS["16"]


@pytest.mark.parametrize("raw,expected", [
    ("15.305(a)", "15.305"),
    ("15.305(a)(2)(ii)", "15.305"),
    ("FAR 15.305(a)", "15.305"),
    ("52.212-4(c)", "52.212-4"),
    ("15.305", "15.305"),
])
def test_trailing_paragraph_cites_stripped(raw, expected):
    got = srv._coerce_cfr_str(raw, field="section", strip_prefixes=True, strip_cites=True)
    assert got == expected


def test_paren_cite_only_strips_trailing():
    # A paren mid-string is not a cite; leave it alone.
    got = srv._coerce_cfr_str("15.3(a)x", field="section", strip_cites=True)
    assert got == "15.3(a)x"


def test_cite_with_no_base_section_becomes_none():
    assert srv._coerce_cfr_str("(a)(2)", field="section", strip_cites=True) is None


def test_compare_versions_rejects_pre_2017_dates():
    asyncio.run(_call_expect_error(
        "compare_versions", "2017-01-03",
        section_id="52.212-4", date_before="2016-06-01", date_after="2026-01-01",
    ))


def test_search_order_rejects_unknown_value():
    asyncio.run(_call_expect_error(
        "search_cfr", "order must be one of", query="audit", order="best_match",
    ))


def test_search_order_known_values_pass_validation():
    # Every advertised order must survive validation (mocked wire).
    for order in sorted(SEARCH_ORDERS):
        mock = _CaptureJson({"results": [], "meta": {}})
        orig, srv._get_json = srv._get_json, mock
        try:
            asyncio.run(_call("search_cfr", query="audit", order=order))
            assert mock.calls[0][1]["order"] == order
        finally:
            srv._get_json = orig


def test_agency_slugs_rejects_invalid_slug():
    asyncio.run(_call_expect_error(
        "search_cfr", "not a valid agency slug",
        query="audit", agency_slugs="Not A Slug!",
    ))


def test_404_guidance_mentions_cites_and_history_floor():
    msg = srv._format_error(404, "not found")
    assert "15.305(a)" in msg
    assert "2017-01-03" in msg


def test_user_agent_matches_installed_version():
    from importlib.metadata import version
    assert srv.USER_AGENT == f"ecfr-mcp/{version('ecfr-mcp')}"


def test_appendix_param_typed_on_all_three_tools():
    async def _run():
        expecting = {"get_cfr_content", "get_cfr_structure", "get_ancestry"}
        seen = set()
        for tool in await mcp.list_tools():
            schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
            spec = (schema.get("properties") or {}).get("appendix")
            if spec is None:
                continue
            seen.add(tool.name)
            types = (
                {spec["type"]} if "type" in spec
                else {o.get("type") for o in spec.get("anyOf", [])}
            )
            types.discard("null")
            assert types and types <= {"string", "integer"}, f"{tool.name}.appendix -> {types}"
        assert expecting <= seen, f"appendix missing from: {expecting - seen}"
    asyncio.run(_run())


# --- parser content recall (pure offline, no mock needed) ------------------

def test_parser_extracts_html_style_table():
    xml = (
        "<DIV8><HEAD>1.106 OMB approval.</HEAD>"
        "<table><thead><tr><th>FAR segment</th><th>OMB Control Number</th></tr></thead>"
        "<tbody><tr><td>15.305(a)(2)(ii)</td><td>9000-0142.</td></tr></tbody></table>"
        "</DIV8>"
    )
    r = srv._parse_xml_to_text(xml)
    assert r["tables"] == [[["FAR segment", "OMB Control Number"],
                            ["15.305(a)(2)(ii)", "9000-0142."]]]
    assert "table_note" in r
    # Cell text must not leak into paragraphs.
    assert all("9000-0142" not in p for p in r["paragraphs"])


def test_parser_extracts_gpo_style_table():
    xml = "<GPOTABLE><ROW><ENT>a</ENT><ENT>b</ENT></ROW></GPOTABLE>"
    r = srv._parse_xml_to_text(xml)
    assert r["tables"] == [[["a", "b"]]]


def test_parser_warns_on_unparseable_table():
    xml = "<P>intro</P><table>loose text with no row markup</table>"
    r = srv._parse_xml_to_text(xml)
    assert "tables" not in r
    assert "1 table(s)" in r["warning"]
    assert r["paragraphs"] == ["intro"]


def test_parser_empty_table_is_not_a_warning():
    r = srv._parse_xml_to_text("<table>   </table><P>x</P>")
    assert "warning" not in r


def test_parser_captures_hd_headings_in_order():
    xml = "<P>body text</P><HD3>(End of clause)</HD3>"
    r = srv._parse_xml_to_text(xml)
    assert r["paragraphs"] == ["body text", "(End of clause)"]


def test_parser_captures_fp_blocks():
    r = srv._parse_xml_to_text("<FP>flush paragraph</FP>")
    assert r["paragraphs"] == ["flush paragraph"]


def test_parser_extracts_editorial_notes():
    xml = (
        "<P>real text</P>"
        "<EDNOTE><HED>Editorial Note:</HED>"
        "<PSPACE>For Federal Register citations, see the List of CFR Sections Affected.</PSPACE>"
        "</EDNOTE>"
    )
    r = srv._parse_xml_to_text(xml)
    assert r["paragraphs"] == ["real text"]
    assert len(r["editorial_notes"]) == 1
    assert "Editorial Note:" in r["editorial_notes"][0]
    assert "Sections Affected" in r["editorial_notes"][0]


def test_parser_plain_p_only_output_unchanged():
    # The pre-1.0.2 contract for simple sections must not shift.
    r = srv._parse_xml_to_text("<HEAD>15.305 Proposal evaluation.</HEAD><P>a</P><P>b</P>")
    assert r["heading"] == "15.305 Proposal evaluation."
    assert r["paragraphs"] == ["a", "b"]
    assert "tables" not in r and "editorial_notes" not in r and "warning" not in r


# ===========================================================================
# TIER 2: MOCK (offline, capture wire params)
# ===========================================================================

def test_search_sends_order_and_repeated_agency_slugs():
    mock = _CaptureJson({"results": [], "meta": {}})
    orig, srv._get_json = srv._get_json, mock
    try:
        asyncio.run(_call(
            "search_cfr", query="cyber", order="Newest_First",
            agency_slugs=["defense-acquisition-regulations-system", "federal-acquisition-regulation"],
        ))
        _, params = mock.calls[0]
        assert params["order"] == "newest_first"
        assert params["agency_slugs[]"] == [
            "defense-acquisition-regulations-system", "federal-acquisition-regulation",
        ]
    finally:
        srv._get_json = orig


def test_search_single_slug_string_becomes_list():
    mock = _CaptureJson({"results": [], "meta": {}})
    orig, srv._get_json = srv._get_json, mock
    try:
        asyncio.run(_call("search_cfr", query="cyber", agency_slugs="general-services-administration"))
        assert mock.calls[0][1]["agency_slugs[]"] == ["general-services-administration"]
    finally:
        srv._get_json = orig


def test_find_recent_changes_orders_newest_first():
    mock = _CaptureJson({"results": [], "meta": {}})
    orig, srv._get_json = srv._get_json, mock
    try:
        asyncio.run(_call("find_recent_changes", since_date="2026-05-01", title=48))
        _, params = mock.calls[0]
        assert params["order"] == "newest_first"
        assert params["last_modified_on_or_after"] == "2026-05-01"
        assert params["query"] == "*"
    finally:
        srv._get_json = orig


def test_content_sends_appendix_on_wire():
    mock = _CaptureXml()
    orig, srv._get_xml = srv._get_xml, mock
    try:
        r = _payload(asyncio.run(_call(
            "get_cfr_content", title_number=48, date="2026-08-13",
            chapter="2", appendix="Appendix A to Chapter 2",
        )))
        path, params = mock.calls[0]
        assert params["appendix"] == "Appendix A to Chapter 2"
        assert params["chapter"] == "2"
        assert r["appendix"] == "Appendix A to Chapter 2"
    finally:
        srv._get_xml = orig


def test_appendix_alone_satisfies_content_filter_check():
    mock = _CaptureXml()
    orig, srv._get_xml = srv._get_xml, mock
    try:
        asyncio.run(_call(
            "get_cfr_content", title_number=48, date="2026-08-13",
            appendix="Appendix A to Chapter 2",
        ))
        assert mock.calls[0][1] == {"appendix": "Appendix A to Chapter 2"}
    finally:
        srv._get_xml = orig


def test_structure_and_ancestry_send_appendix_on_wire():
    mock = _CaptureJson({"ancestors": []})
    orig, srv._get_json = srv._get_json, mock
    try:
        asyncio.run(_call(
            "get_cfr_structure", title_number=48, date="2026-08-13",
            chapter="2", appendix="Appendix A to Chapter 2",
        ))
        asyncio.run(_call(
            "get_ancestry", title_number=48, date="2026-08-13",
            appendix="Appendix A to Chapter 2",
        ))
        for _path, params in mock.calls:
            assert params["appendix"] == "Appendix A to Chapter 2"
    finally:
        srv._get_json = orig


def test_section_cite_stripped_on_wire():
    mock = _CaptureXml()
    orig, srv._get_xml = srv._get_xml, mock
    try:
        asyncio.run(_call(
            "get_cfr_content", title_number=48, date="2026-08-13",
            section="15.305(a)(2)",
        ))
        assert mock.calls[0][1]["section"] == "15.305"
    finally:
        srv._get_xml = orig


def test_summary_agencies_merge_child_refs():
    payload = {"agencies": [
        {
            "name": "Department of Defense", "short_name": "DOD",
            "slug": "department-of-defense",
            "cfr_references": [{"title": 32, "chapter": "I"}],
            "children": [
                {
                    "name": "Defense Acquisition Regulations System",
                    "slug": "defense-acquisition-regulations-system",
                    "cfr_references": [{"title": 48, "chapter": "2"}],
                    "children": [],
                },
            ],
        },
    ]}
    mock = _CaptureJson(payload)
    orig, srv._get_json = srv._get_json, mock
    try:
        r = _payload(asyncio.run(_call("list_agencies", summary_only=True)))
        dod = r["agencies"][0]
        assert {"title": 48, "chapter": "2"} in dod["cfr_references"]
        assert {"title": 32, "chapter": "I"} in dod["cfr_references"]
        assert dod["child_count"] == 1
    finally:
        srv._get_json = orig


def test_summary_agencies_dedupe_repeated_refs():
    payload = {"agencies": [
        {
            "name": "A", "slug": "a",
            "cfr_references": [{"title": 48, "chapter": "1"}],
            "children": [
                {"cfr_references": [{"title": 48, "chapter": "1"}], "children": []},
            ],
        },
    ]}
    mock = _CaptureJson(payload)
    orig, srv._get_json = srv._get_json, mock
    try:
        r = _payload(asyncio.run(_call("list_agencies", summary_only=True)))
        assert r["agencies"][0]["cfr_references"] == [{"title": 48, "chapter": "1"}]
    finally:
        srv._get_json = orig


# ===========================================================================
# TIER 3: LIVE (production eCFR, no API key required)
# ===========================================================================

_live_date_cache: dict[str, str] = {}


def _live_date() -> str:
    """Resolve title 48's latest date once per test session.

    Resets the shared client afterward: asyncio.run closes its event loop,
    and an httpx client bound to a closed loop poisons the next call in the
    same test.
    """
    if "d" not in _live_date_cache:
        _live_date_cache["d"] = asyncio.run(srv._resolve_date(48))
        srv._client = None
    return _live_date_cache["d"]


@live
def test_live_title48_chapter_map_matches_agencies_endpoint():
    """The drift guard: every title-48 chapter the eCFR agencies endpoint
    references must be a key of TITLE_48_CHAPTERS. This is the test that
    would have caught the nine missing chapters five rounds earlier."""
    async def _run():
        data = await srv._get_json("/api/admin/v1/agencies.json")
        chapters: set[str] = set()

        def _walk(a):
            for r in srv._as_list(a.get("cfr_references")):
                r = srv._safe_dict(r)
                if r.get("title") == 48 and r.get("chapter") is not None:
                    chapters.add(str(r.get("chapter")))
            for c in srv._as_list(a.get("children")):
                _walk(srv._safe_dict(c))

        for a in srv._as_list(srv._safe_dict(data).get("agencies")):
            _walk(srv._safe_dict(a))

        assert chapters, "agencies.json returned no title-48 references"
        missing = chapters - set(TITLE_48_CHAPTERS)
        assert not missing, (
            f"TITLE_48_CHAPTERS is missing live chapters {sorted(missing)}; "
            f"update the constant in constants.py"
        )
    asyncio.run(_run())


@live
def test_live_hsar_chapter_30_structure_reachable():
    r = _payload(asyncio.run(_call(
        "get_cfr_structure", title_number=48, chapter="30", date=_live_date(),
    )))
    assert "Homeland Security" in str(r)


@live
def test_live_far_1_106_table_content_recovered():
    r = _payload(asyncio.run(_call(
        "get_cfr_content", title_number=48, section="1.106", date=_live_date(),
    )))
    assert r.get("tables"), "FAR 1.106 should parse into tables"
    flat = [cell for table in r["tables"] for row in table for cell in row]
    assert any("9000-0142" in c for c in flat), "OMB control numbers missing from table cells"


@live
def test_live_dfars_appendix_a_fetchable():
    r = _payload(asyncio.run(_call(
        "get_cfr_content", title_number=48, chapter="2",
        appendix="Appendix A to Chapter 2", date=_live_date(),
    )))
    assert "Armed Services Board" in (r.get("heading", "") + " ".join(r.get("paragraphs", [])))


@live
def test_live_search_newest_first_ordering():
    r = _payload(asyncio.run(_call(
        "search_cfr", query="commercial item", title=48,
        order="newest_first", per_page=5,
    )))
    dates = [x.get("starts_on") for x in r.get("results", []) if x.get("starts_on")]
    assert dates == sorted(dates, reverse=True), f"not newest-first: {dates}"


@live
def test_live_paragraph_cite_resolves_to_base_section():
    r = _payload(asyncio.run(_call(
        "lookup_far_clause", section_id="15.305(a)", date=_live_date(),
    )))
    assert "15.305" in r.get("heading", "")


@live
def test_live_summary_agencies_contain_dfars_chapter():
    r = _payload(asyncio.run(_call("list_agencies", summary_only=True)))
    has_ch2 = any(
        str(ref.get("chapter")) == "2" and ref.get("title") == 48
        for a in r.get("agencies", [])
        for ref in a.get("cfr_references", [])
    )
    assert has_ch2, "summary lost the DFARS chapter-2 mapping again"
