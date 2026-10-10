"""A normal government-site research request retains recoverable source guidance."""
import asyncio
from pathlib import Path
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.parametrize("name,arguments", [
    ("keyword_search", {"keyword": "Network Engineer", "education_level": "BA", "experience_min": 5, "worksite": "Customer"}),
    ("filtered_browse", {"sin": "541330ENG", "business_size": "S", "worksite": "Customer"}),
])
def test_government_worksite_request_explains_source_limit_and_recovery(name, arguments):
    async def run():
        source = Path(__file__).resolve().parents[1] / "src"
        code = f"import sys; sys.path.insert(0, {str(source)!r}); from gsa_calc_mcp.server import main; main()"
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-c", code])) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                answer = await session.call_tool(name, arguments)
                assert answer.is_error
                text = " ".join(block.text for block in answer.content if hasattr(block, "text"))
                assert "worksite filtering is not supported" in text
                assert "Remove the worksite argument" in text
    asyncio.run(run())
