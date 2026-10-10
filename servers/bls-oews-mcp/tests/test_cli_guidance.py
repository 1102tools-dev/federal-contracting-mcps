"""A real CLI client needs an actionable answer to an unsupported wage question."""
import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_installed_cli_preserves_national_ratio_guidance_and_state_followup():
    async def check():
        command = str(Path(sys.executable).with_name("bls-oews-mcp"))
        async with stdio_client(StdioServerParameters(command=command)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for name, arguments in (
                    ("get_wage_data", {"occ_code": "151252", "datatypes": ["16", "17"]}),
                    ("compare_occupations", {"occ_codes": ["151252", "151212"], "datatype": "17"}),
                ):
                    result = await session.call_tool(name, arguments)
                    text = result.content[0].text
                    assert "state/metro" in text, text
                    assert "BLS does not publish national ratios" in text
                # Follow the returned guidance and complete the user's task.
                result = await session.call_tool("get_wage_data", {
                    "occ_code": "151252", "scope": "state", "area_code": "51", "datatypes": ["16", "17"],
                })
                assert result.structured_content["wages"]["Location Quotient"]["numeric"] == 1.98
    asyncio.run(check())
