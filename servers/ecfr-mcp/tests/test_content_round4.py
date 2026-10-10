"""Legacy property-reference recovery, using exact current/history/old XML proof."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.mcpserver.exceptions import ToolError
import pytest

from ecfr_mcp import server as srv

FIXTURES = Path(__file__).parent / "fixtures"


class NoWait:
    @asynccontextmanager
    async def request_slot(self):
        yield self

    def observe_response(self, response):
        pass

    def raise_if_rate_limited(self, response, **kwargs):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["xml", "json"])
async def test_not_found_guidance_is_expected_and_runtimeerror_compatible(monkeypatch, kind):
    client = httpx.AsyncClient(base_url="https://www.ecfr.gov", transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={"error": "No matching content found."})
    ))
    monkeypatch.setattr(srv, "_get_client", lambda: client)
    monkeypatch.setattr(srv, "_pacer", NoWait())
    monkeypatch.setattr(srv, "_xml_pacer", NoWait())
    try:
        with pytest.raises(RuntimeError) as exc:
            if kind == "xml":
                await srv._get_xml_uncached("/api/versioner/v1/full/2026-10-07/title-41.xml", {"section": "102-75.45"})
            else:
                await srv._fetch_json("/api/versioner/v1/structure/2026-10-07/title-41.json", {"part": "102-75"}, 1)
        assert "HTTP 404" in str(exc.value) and "get_version_history" in str(exc.value)
        assert isinstance(exc.value, ToolError)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["xml", "json"])
async def test_unexpected_server_failure_remains_ordinary_runtimeerror(monkeypatch, kind):
    client = httpx.AsyncClient(base_url="https://www.ecfr.gov", transport=httpx.MockTransport(
        lambda request: httpx.Response(503, text="upstream service unavailable")
    ))
    monkeypatch.setattr(srv, "_get_client", lambda: client)
    monkeypatch.setattr(srv, "_pacer", NoWait())
    monkeypatch.setattr(srv, "_xml_pacer", NoWait())
    try:
        with pytest.raises(RuntimeError, match="HTTP 503") as exc:
            if kind == "xml":
                await srv._get_xml_uncached("/content", {})
            else:
                await srv._fetch_json("/structure", {}, 1)
        assert not isinstance(exc.value, ToolError)
    finally:
        await client.aclose()


DRIVER = '''
from contextlib import asynccontextmanager
import json,os
from pathlib import Path
import httpx
import ecfr_mcp.server as srv
class NoWait:
 @asynccontextmanager
 async def request_slot(self):yield self
 def observe_response(self,response):pass
 def raise_if_rate_limited(self,response,**kwargs):pass
fixtures=Path(os.environ['ECFR_ROUND4_FIXTURES'])
def handle(request):
 path=request.url.path
 if path.endswith('/titles.json'):
  return httpx.Response(200,json={'titles':[{'number':41,'name':'Public Contracts and Property Management','up_to_date_as_of':'2026-10-07','latest_amended_on':'2025-12-16','latest_issue_date':'2025-12-16','reserved':False}]})
 if '/versions/' in path:
  return httpx.Response(200,json=json.loads((fixtures/'history_property_round4.json').read_text()))
 if '/structure/' in path:return httpx.Response(404,json={})
 if '/full/2025-12-15/' in path:
  return httpx.Response(200,text=(fixtures/'property-definition-2025-12-15.xml').read_text())
 return httpx.Response(404,json={'error':'No matching content found.'})
client=httpx.AsyncClient(base_url='https://www.ecfr.gov',transport=httpx.MockTransport(handle))
srv._get_client=lambda:client
srv._pacer=NoWait();srv._xml_pacer=NoWait()
srv.main()
'''


def test_stdio_legacy_reference_guidance_history_and_dated_recovery():
    """Only provider HTTP responses are captured; real tool/SDK/stdio paths run."""
    async def workflow():
        env = {**os.environ, "ECFR_ROUND4_FIXTURES": str(FIXTURES)}
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-c", DRIVER], env=env)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                missing = await session.call_tool("get_cfr_content", {"title_number": 41, "section": "102-75.45"})
                assert missing.is_error
                assert "HTTP 404" in missing.content[0].text
                assert "get_version_history" in missing.content[0].text
                assert "section=102-75.45" in missing.content[0].text
                missing_part = await session.call_tool("get_cfr_structure", {"title_number": 41, "part": "102-75"})
                assert missing_part.is_error and "HTTP 404" in missing_part.content[0].text
                assert "get_version_history" in missing_part.content[0].text
                history = await session.call_tool("get_version_history", {"title_number": 41, "section": "102-75.45"})
                assert not history.is_error
                data = history.structured_content or json.loads(history.content[0].text)
                assert any(v["removed"] and v["date"] == "2025-12-16" for v in data["content_versions"])
                recovered = await session.call_tool("get_cfr_content", {"title_number": 41, "section": "102-75.45", "date": "2025-12-15"})
                assert not recovered.is_error
                data = recovered.structured_content or json.loads(recovered.content[0].text)
                assert "Not utilized" in data["heading"] and "not occupied for current program purposes" in data["paragraphs"][0]
                removed = await session.call_tool("compare_versions", {"title_number": 41, "section_id": "102-75.45", "date_before": "2025-12-15", "date_after": "2025-12-16", "changes_only": True})
                assert not removed.is_error
                data = removed.structured_content or json.loads(removed.content[0].text)
                assert data["changes"] == [{"change": "section removed", "detail": "102-75.45 is not in the eCFR text on 2025-12-16; it is on 2025-12-15."}]
                assert data["texts_omitted"] is True
    asyncio.run(workflow())
