"""Bounded, stateless HTTP deployment of the existing Acquisition.gov tools."""
from __future__ import annotations

import asyncio
import os

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .server import mcp


def create_app():
    hosts = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",")
    origins = os.environ.get("MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",")
    return AdmissionControl(RequestScopedMCP(hosts, origins))


class RequestScopedMCP:
    """Tie the SDK's stateless connection tasks to the owning HTTP request.

    A process-wide SDK lifespan can outlive a cancelled HTTP handler. A fresh
    stateless app/lifespan per POST guarantees that its dispatcher and tool tasks
    are cancelled before the admission slot is released. Uses public SDK APIs.
    """
    def __init__(self, hosts, origins):
        self.security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        app = mcp.streamable_http_app(
            stateless_http=True, json_response=True, max_request_body_size=65536,
            transport_security=self.security,
        )
        async with app.router.lifespan_context(app):
            await app(scope, receive, send)


class AdmissionControl:
    """Bound active requests, uploads, cancellation and request lifetime."""
    request_timeout = 55

    def __init__(self, app):
        self.app = app
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/health":
            return await JSONResponse({"status": "ok", "tools": len(await mcp.list_tools()), "release_sha": os.environ.get("RELEASE_SHA", "development")})(scope, receive, send)
        if scope["path"] == "/mcp" and scope["method"] != "POST":
            return await JSONResponse({"error": "Use POST for stateless MCP requests."}, status_code=405, headers={"Allow": "POST"})(scope, receive, send)
        if self.active >= 4:
            return await JSONResponse({"error": "Server busy; retry later."}, status_code=429, headers={"Retry-After": "5"})(scope, receive, send)
        self.active += 1
        started = False
        tasks = []

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with asyncio.timeout(self.request_timeout):
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > 65536:
                        return await JSONResponse({"error": "Request body too large."}, status_code=413)(scope, receive, send)
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
                disconnected = asyncio.Event()
                delivered = False

                async def replay_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    await disconnected.wait()
                    return {"type": "http.disconnect"}

                async def watch_disconnect():
                    while True:
                        if (await receive())["type"] == "http.disconnect":
                            disconnected.set()
                            return

                app_task = asyncio.create_task(self.app(scope, replay_receive, tracked_send))
                disconnect_task = asyncio.create_task(watch_disconnect())
                tasks = [app_task, disconnect_task]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if app_task in done:
                    await app_task
        except TimeoutError:
            if not started:
                await JSONResponse({"error": "Upstream request timed out; retry later."}, status_code=504)(scope, receive, send)
            else:
                raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.active -= 1


def main():
    import logging
    import uvicorn
    logging.disable(logging.CRITICAL)  # SDK errors may include raw tool arguments.
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
