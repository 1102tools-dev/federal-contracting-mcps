"""Bounded, stateless HTTP deployment of the existing GSA CALC+ tools."""
from __future__ import annotations

import os

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from ._admission import AdmissionQueue
from .server import mcp
from . import server


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


class AdmissionControl(AdmissionQueue):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/health":
            return await JSONResponse({
                "status": "ok", "tools": len(await mcp.list_tools()),
                "release_sha": os.environ.get("RELEASE_SHA", "development"),
                "admission": self.admission_limits,
            })(scope, receive, send)
        return await super().__call__(scope, receive, send)

    async def response_start(self, message):
        # Preserve the provider cooldown in the outer Durable Object.
        cooldown = await server._pacer.cooldown_remaining()
        if cooldown:
            message = dict(message)
            message["headers"] = list(message.get("headers", [])) + [
                (b"x-1102tools-provider-retry-after", str(cooldown).encode("ascii"))
            ]
        return message


def main():
    import logging
    import uvicorn
    logging.disable(logging.CRITICAL)  # SDK errors may include raw tool arguments.
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
