"""Ordinary user recovery through the actual stdio transport, without network."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Only upstream data is replaced. The real installed server, tool registry,
# schema validation, SDK error serialization and stdio client are exercised.
DRIVER = '''
import ecfr_mcp.server as srv
async def latest(title):
    return "2026-10-07"
async def xml(path, params=None):
    return '<DIV8 N="15.305" TYPE="SECTION"><HEAD>15.305 Proposal evaluation.</HEAD><P>Evaluate proposals.</P></DIV8>'
async def structure(*args, **kwargs):
    return {"type":"title","identifier":"2","children":[
        {"type":"part","identifier":"200","children":[
            {"type":"section","identifier":"200.320","label":"200.320 Methods of procurement."}
        ]}
    ]}
srv._resolve_date = latest
srv._get_xml = xml
srv._get_json = structure
srv.main()
'''


def _data(result):
    return result.structured_content or json.loads(result.content[0].text)


def test_stdio_preserves_guidance_and_corrected_question_completes():
    async def workflow():
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-c", DRIVER])) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("compare_versions", {
                    "section_id": "15.305", "date_before": "2026-10-01", "date_after": "2026-10-10",
                })
                assert result.is_error
                assert "latest available" in result.content[0].text
                assert "2026-10-07" in result.content[0].text
                corrected = await session.call_tool("compare_versions", {
                    "section_id": "15.305", "date_before": "2026-10-01", "date_after": "2026-10-07",
                })
                assert not corrected.is_error and _data(corrected)["identical"] is True
                result = await session.call_tool("list_sections_in_part", {"part_number": "2 CFR 200"})
                assert result.is_error and "title_number=2" in result.content[0].text
                corrected = await session.call_tool("list_sections_in_part", {
                    "part_number": "2 CFR 200", "title_number": 2,
                })
                assert not corrected.is_error
                data = _data(corrected)
                assert data["title"] == 2 and data["sections"][0]["identifier"] == "200.320"
    asyncio.run(workflow())
