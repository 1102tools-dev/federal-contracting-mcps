import os

import pytest

import acquisition_gov_mcp.server as server


pytestmark = pytest.mark.skipif(
    os.getenv("ACQUISITION_GOV_LIVE_TESTS") != "1",
    reason="set ACQUISITION_GOV_LIVE_TESTS=1 for serialized upstream checks",
)


@pytest.mark.asyncio
async def test_serialized_live_index_part_pdf_and_guidance():
    parts = await server.list_rfo_parts(part=10)
    assert parts["results"] and len(parts["content_sha256"]) == 64
    model = await server.get_rfo_part(10, max_characters=2000)
    assert model["content"] and model["source_url"].startswith("https://www.acquisition.gov/")
    deviations = await server.list_rfo_agency_deviations(part=10, limit=10)
    assert deviations["results"]
    document = await server.get_rfo_agency_deviation(
        deviations["results"][0]["source_id"], page_start=1, page_end=1
    )
    assert document["content_sha256"] and document["total_pages"] >= 1
    guidance = await server.get_rfo_guidance("faq")
    assert guidance["content"]

