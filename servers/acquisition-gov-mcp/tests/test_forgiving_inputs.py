"""get_rfo_part corrects slightly-off inputs instead of failing: max_characters
outside its range, section citations with prefixes or paragraph cites, a
section from another part, and a part with no page. Real misses stay errors."""
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import acquisition_gov_mcp.server as s
from acquisition_gov_mcp._errors import GovernmentApiError
from test_tool_paths import call, sources  # noqa: F401  (pytest fixture)

POLICY = "10.001 Policy\nThis is fixture model text, not codified FAR text."


async def error_text(name, args):
    """The tool error the user sees, however the SDK reports it."""
    try:
        result = await s.mcp.call_tool(name, args)
    except ToolError as exc:
        return str(exc)
    assert result.is_error, "tool incorrectly reported success"
    return result.content[0].text


@pytest.mark.p2
@pytest.mark.parametrize("value,used", [(300, 1000), (999, 1000), (40001, 40000), (100000, 40000), (-5, 1000)])
async def test_max_characters_outside_range_is_clamped_with_warning(sources, value, used):
    result = await call("get_rfo_part", {"part": 10, "max_characters": value})
    assert 0 < len(result["content"]) <= used
    assert f"max_characters {value} is outside 1000 through 40000; {used} was used." in result["warnings"]


@pytest.mark.p2
@pytest.mark.parametrize("value", [1000, 20000, 40000])
async def test_max_characters_in_range_has_no_warning(sources, value):
    result = await call("get_rfo_part", {"part": 10, "max_characters": value})
    assert not any("max_characters" in w for w in result["warnings"])


@pytest.mark.p1
@pytest.mark.parametrize("query", [
    "10.001(a)(2)", "10.001 (a)", "FAR 10.001(b)(1)(i)", "far part 10.001", "48 CFR 10.001",
    "48 C.F.R. § 10.001(c)", "§10.001(a)", "§§ 10.001", "Section 10.001.", "FAR §10.001",
])
async def test_section_citation_resolves_its_base_section(sources, query):
    result = await call("get_rfo_part", {"part": 10, "section": query})
    assert result["content"] == POLICY
    assert result["section"] == query
    assert not any("was read instead" in w for w in result["warnings"])


@pytest.mark.p2
@pytest.mark.parametrize("query,number", [
    ("15.305(a)(2)", "15.305"), ("52.212-4(c)", "52.212-4"), ("FAR 19.1505(b)", "19.1505"),
    ("  48  cfr   52.204-27 ", "52.204-27"), ("15.305 Proposal evaluation", None), ("Subpart 15.3", None),
    ("15.30", None), ("FAR Part 15", None),
])
def test_section_number_parses_citations_only(query, number):
    assert s._section_number(query) == number


@pytest.mark.p1
async def test_section_from_another_part_reads_that_part(sources):
    result = await call("get_rfo_part", {"part": 15, "section": "FAR 10.001(a)"})
    assert sources[-1].endswith("/far-overhaul-part-10")
    assert result["far_parts"] == [10] and result["content"] == POLICY
    assert "Section 10.001 is in FAR part 10, so part 10 was read instead of part 15." in result["warnings"]


@pytest.mark.p1
async def test_real_section_miss_stays_an_error(sources):
    assert (await error_text("get_rfo_part", {"part": 10, "section": "10.999(a)"})).endswith(
        "section '10.999(a)' was not found in the official source (searched for section 10.999).")
    # A part number outside 1-53 is not followed; the requested part is searched.
    assert (await error_text("get_rfo_part", {"part": 10, "section": "99.101"})).endswith(
        "section '99.101' was not found in the official source.")
    assert all(url.endswith("/far-overhaul-part-10") for url in sources)


def missing_part_fetch(fixtures, calls, index_ok=True):
    async def fetch(url, **kw):
        calls.append(url)
        if url == s.RFO_INDEX_URL and index_ok:
            return (fixtures / "rfo-index.html").read_bytes(), "text/html", url
        raise GovernmentApiError("Acquisition.gov returned HTTP 404 for this page.")
    return fetch


@pytest.mark.p1
async def test_part_without_page_names_the_parts_that_exist(monkeypatch, fixtures):
    calls = []
    monkeypatch.setattr(s, "_fetch_bytes", missing_part_fetch(fixtures, calls))
    assert (await error_text("get_rfo_part", {"part": 21})).endswith(
        "FAR part 21 has no RFO model page on Acquisition.gov. "
        "Parts with model pages in the official RFO index: 10, 12.")
    assert calls == [f"{s.RFO_INDEX_URL}/far-overhaul-part-21", s.RFO_INDEX_URL]


@pytest.mark.p2
async def test_part_without_page_keeps_original_error_when_index_is_unavailable(monkeypatch, fixtures):
    calls = []
    monkeypatch.setattr(s, "_fetch_bytes", missing_part_fetch(fixtures, calls, index_ok=False))
    assert (await error_text("get_rfo_part", {"part": 21})).endswith("Acquisition.gov returned HTTP 404 for this page.")


@pytest.mark.p2
def test_part_ranges():
    assert s._part_ranges([1, 2, 3, 5, 7, 8]) == "1-3, 5, 7-8"
    assert s._part_ranges(list(range(1, 20)) + list(range(22, 54))) == "1-19, 22-53"
    assert s._part_ranges([10, 12]) == "10, 12"
