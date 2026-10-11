"""Regressions for the confirmed Acquisition.gov content-round failures."""
import pytest

import acquisition_gov_mcp.server as s


@pytest.mark.p1
@pytest.mark.parametrize("query", ["FAR 10.001", "far 10.001", "Section 10.001", "§ 10.001", "10.001"])
def test_numbered_section_accepts_canonical_prefixes(query):
    node = s._main_content(b"<main><h2>10.001 Policy</h2><p>Market research requirement.</p><h2>10.002 Procedures</h2><p>Excluded.</p></main>")
    result = s._extract_section(node, query)
    assert "Market research requirement." in result
    assert "Excluded." not in result


@pytest.mark.p1
@pytest.mark.parametrize("query", ["FAR 10.001", "Section 10.001", "§ 10.001"])
def test_numbered_section_cannot_match_longer_number_or_wrong_part(query):
    node = s._main_content(b"<main><h2>10.0010 Other</h2><p>Wrong suffix.</p><h2>11.001 Other</h2><p>Wrong part.</p></main>")
    with pytest.raises(ValueError, match="was not found"):
        s._extract_section(node, query)


@pytest.mark.p2
def test_descriptive_section_heading_is_not_reinterpreted():
    node = s._main_content(b"<main><h2>FAR 10.001 overview</h2><p>Overview.</p><h2>10.001 Policy</h2><p>Policy.</p></main>")
    result = s._extract_section(node, "FAR 10.001 overview")
    assert "Overview." in result and "Policy." not in result


def agency_parts():
    names = ["Department of State (DOS)", "DOS", "United States Department of the Treasury (Treasury)", "United States Department of Agriculture (USDA)", "Department of Defense (DOD)", "DOD", "Department of Homeland Security (DHS)"]
    return [{"agency_deviations": [{"agency": name} for name in names]}]


@pytest.mark.p1
def test_state_filter_excludes_united_states_agencies():
    assert s._matching_agency_names(agency_parts(), "State") == {"Department of State (DOS)", "DOS"}


@pytest.mark.p1
@pytest.mark.parametrize("query,expected", [
    ("DoD", {"Department of Defense (DOD)", "DOD"}),
    ("Defense", {"Department of Defense (DOD)", "DOD"}),
    ("Department of Defense", {"Department of Defense (DOD)", "DOD"}),
    ("Homeland Security", {"Department of Homeland Security (DHS)"}),
    ("USDA", {"United States Department of Agriculture (USDA)"}),
    ("Sta", set()),
])
def test_agency_whole_phrase_and_explicit_alias_matching(query, expected):
    assert s._matching_agency_names(agency_parts(), query) == expected
