"""Runs the Regulations.gov release image with its key supplied per request.

The api.data.gov key is a Worker secret that can't be read back, so the Worker
sends it to the Dell origin as X-Regulations-Key (over the tunnel, after the
gateway's secret check). This sets it for the tools, which read
REGULATIONS_GOV_API_KEY at call time, and drops the header before the app.
"""
import os

import uvicorn

from regulationsgov_mcp import http

HEADER = b"x-regulations-key"


def create_app():
    inner = http.create_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            key = next((v for k, v in scope["headers"] if k == HEADER), b"").decode("latin-1").strip()
            if key and os.environ.get("REGULATIONS_GOV_API_KEY") != key:
                os.environ["REGULATIONS_GOV_API_KEY"] = key
            scope = dict(scope, headers=[(k, v) for k, v in scope["headers"] if k != HEADER])
        await inner(scope, receive, send)

    return app


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)  # SDK errors may include raw tool arguments.
    uvicorn.run(create_app(), host="0.0.0.0", port=8080, access_log=False, log_level="critical")
