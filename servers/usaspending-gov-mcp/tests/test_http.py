"""Real ASGI transport tests, without external API traffic."""
import pytest
from starlette.testclient import TestClient
from usaspending_gov_mcp.http import create_app

HEADERS = {"host": "localhost:8080", "accept": "application/json, text/event-stream"}

def test_full_tool_catalog_and_reject_extra_inputs():
    with TestClient(create_app()) as client:
        def rpc(method, params=None):
            return client.post('/mcp', headers=HEADERS, json={"jsonrpc":"2.0", "id":1, "method":method, "params":params or {}})
        init = rpc('initialize', {"protocolVersion":"2025-11-25", "capabilities":{}, "clientInfo":{"name":"test","version":"1"}})
        assert init.status_code == 200
        tools = rpc('tools/list').json()['result']['tools']
        assert len(tools) == 55
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
        assert client.get('/health').json()['admission'] == {'processing':16,'waiting':32,'total':48,'deadline_seconds':55}
        assert client.get('/health').json()['tools'] == 55

