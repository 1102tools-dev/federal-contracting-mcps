"""Bounded, stateless HTTP deployment of the existing Federal Register tools."""
from __future__ import annotations

import asyncio
import os

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .server import mcp


def create_app():
    hosts = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",")
    origins = os.environ.get("MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",")
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=65536,
        transport_security=TransportSecuritySettings(
            allowed_hosts=hosts, allowed_origins=origins,
        ),
    )
    return AdmissionControl(app)


class AdmissionControl:
    """Keep the single paced backend's queue and request lifetime bounded."""
    def __init__(self, app):
        self.app = app
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/health":
            return await JSONResponse({"status": "ok", "tools": len(await mcp.list_tools())})(scope, receive, send)
        if self.active >= 4:
            return await JSONResponse({"error": "Server busy; retry later."}, status_code=429, headers={"Retry-After": "5"})(scope, receive, send)
        self.active += 1
        started = False
        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)
        try:
            async with asyncio.timeout(55):
                await self.app(scope, receive, tracked_send)
        except TimeoutError:
            if not started:
                await JSONResponse({"error": "Upstream request timed out; retry later."}, status_code=504)(scope, receive, send)
            else:
                raise
        finally:
            self.active -= 1


def main():
    import logging
    import uvicorn
    logging.disable(logging.CRITICAL)  # SDK errors may include raw tool arguments.
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
