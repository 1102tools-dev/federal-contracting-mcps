"""Real ASGI transport tests, without external API traffic."""
import pytest
from starlette.testclient import TestClient
from ecfr_mcp.http import create_app

HEADERS = {"host": "localhost:8080", "accept": "application/json, text/event-stream"}

def test_full_tool_catalog_and_reject_extra_inputs():
    with TestClient(create_app()) as client:
        def rpc(method, params=None):
            return client.post('/mcp', headers=HEADERS, json={"jsonrpc":"2.0", "id":1, "method":method, "params":params or {}})
        init = rpc('initialize', {"protocolVersion":"2025-11-25", "capabilities":{}, "clientInfo":{"name":"test","version":"1"}})
        assert init.status_code == 200
        tools = rpc('tools/list').json()['result']['tools']
        assert len(tools) == 13
        for tool in tools:
            assert tool['annotations']['readOnlyHint'] is True
            assert tool['annotations']['destructiveHint'] is False
            assert tool['annotations']['openWorldHint'] is True
            result = rpc('tools/call', {"name":tool['name'],"arguments":{"_unexpected_parameter":True}}).json()
            assert result.get('error') or result.get('result', {}).get('isError'), tool['name']

def test_host_origin_and_size_guards():
    with TestClient(create_app()) as client:
        body = {"jsonrpc":"2.0", "id":1, "method":"tools/list"}
        assert client.post('/mcp', headers={**HEADERS, 'host':'evil.invalid'}, json=body).status_code == 421
        assert client.post('/mcp', headers={**HEADERS, 'origin':'https://evil.invalid'}, json=body).status_code == 403
        assert client.post('/mcp', headers=HEADERS, content='x'*65537).status_code == 413
        assert client.get('/health').json()['tools'] == 13

@pytest.mark.asyncio
async def test_admission_limit_does_not_queue_unbounded_work():
    import asyncio
    from ecfr_mcp.http import AdmissionControl
    release = asyncio.Event()
    async def backend(scope, receive, send):
        await release.wait()
    guard = AdmissionControl(backend)
    messages = []
    async def send(message):
        messages.append(message)
    async def receive():
        return {"type":"http.request", "body":b"", "more_body":False}
    scope = {"type":"http", "path":"/mcp", "method":"POST"}
    running = [asyncio.create_task(guard(scope, receive, send)) for _ in range(4)]
    await asyncio.sleep(0)
    try:
        await guard(scope, receive, send)
        assert messages[0]['status'] == 429
        assert guard.active == 4
    finally:
        release.set()
        await asyncio.gather(*running)
    assert guard.active == 0
