"""P3 real process/HTTP smoke checks, with no external-source requests."""
import os
import sys
from importlib.resources import files

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from starlette.testclient import TestClient

from acquisition_gov_mcp import __version__
from acquisition_gov_mcp.http import create_app

pytestmark=pytest.mark.p3

async def test_real_stdio_startup_catalog_validation_and_shutdown():
    params=StdioServerParameters(command=sys.executable,args=['-m','acquisition_gov_mcp.server'])
    with open(os.devnull,'w') as errors:
        async with stdio_client(params,errlog=errors) as streams:
            async with ClientSession(*streams,read_timeout_seconds=10) as client:
                init=await client.initialize()
                assert init.server_info.name=='acquisition-gov'
                assert init.server_info.version==__version__
                result=await client.list_tools()
                assert len(result.tools)==5
                invalid=await client.call_tool('get_rfo_part',{'part':0})
                assert invalid.is_error


def test_worker_module_is_packaged():
    package=files('acquisition_gov_mcp')
    assert package.joinpath('_pdf_worker.py').is_file()
    assert package.joinpath('_pdf.py').is_file()


def test_http_protocol_methods_and_errors_are_structured():
    headers={'Host':'localhost:8080','Accept':'application/json, text/event-stream'}
    with TestClient(create_app()) as client:
        result=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_rfo_part','arguments':{'part':0}}})
        assert result.status_code==200
        assert result.json()['result']['isError'] is True
        assert client.post('/mcp',headers=headers,content='{broken json').status_code in (400,422)
        assert client.get('/health').json()['tools']==5
