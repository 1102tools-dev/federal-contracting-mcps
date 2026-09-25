"""Bounded FIFO admission for one hosted MCP backend (single event loop)."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress

from starlette.responses import JSONResponse


class AdmissionQueue:
    """Limits HTTP work independently of the provider's upstream pacing.

    Reserve before reading the body, so slow uploads also consume a bounded
    slot. All queue mutations run without an await on the same event loop.
    """

    processing_limit = 16
    waiting_limit = 32
    request_timeout = 55
    body_limit = 65536

    def __init__(self, app):
        self.app = app
        self.active = 0
        self._waiting = deque()

    @property
    def waiting(self):
        return len(self._waiting)

    @property
    def admission_limits(self):
        return {"processing": self.processing_limit, "waiting": self.waiting_limit,
                "total": self.processing_limit + self.waiting_limit,
                "deadline_seconds": self.request_timeout}

    def _reserve(self):
        ticket = asyncio.get_running_loop().create_future()
        if self.active < self.processing_limit and not self._waiting:
            self.active += 1
            ticket.set_result(None)
        elif len(self._waiting) < self.waiting_limit:
            self._waiting.append(ticket)
        else:
            return None
        return ticket

    def _release(self, ticket):
        if ticket in self._waiting:
            self._waiting.remove(ticket)
        else:
            # A granted ticket owns a slot even if cancelled before it resumes.
            self.active -= 1
        while self._waiting and self.active < self.processing_limit:
            next_ticket = self._waiting.popleft()
            self.active += 1
            next_ticket.set_result(None)

    async def response_start(self, message):
        return message

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        ticket = self._reserve()
        if ticket is None:
            return await JSONResponse(
                {"error": "Server busy: processing and waiting slots are full; retry later."},
                status_code=429, headers={"Retry-After": "5"},
            )(scope, receive, send)

        started = False
        tasks = []

        async def stop_tasks():
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                message = await self.response_start(message)
                started = True
            await send(message)

        try:
            async with asyncio.timeout(self.request_timeout):
                # At most 64 KiB per accepted request, including queued uploads.
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.body_limit:
                        return await JSONResponse({"error": "Request body too large."},
                            status_code=413)(scope, receive, send)
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
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            disconnected.set()
                            return

                async def process():
                    # Shield keeps cancellation from cancelling a queued ticket.
                    await asyncio.shield(ticket)
                    await self.app(scope, replay_receive, tracked_send)

                work = asyncio.create_task(process())
                disconnect = asyncio.create_task(watch_disconnect())
                tasks = [work, disconnect]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if work in done:
                    await work  # propagate application failures
                else:
                    await disconnect  # propagate receive failures
        except TimeoutError:
            await stop_tasks()
            if not started:
                await JSONResponse(
                    {"error": "Request deadline exceeded while waiting or processing; retry later."},
                    status_code=504,
                )(scope, receive, send)
            else:
                raise
        finally:
            await stop_tasks()
            self._release(ticket)
