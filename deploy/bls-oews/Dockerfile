FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=uv /uv /usr/local/bin/uv
ARG RELEASE_SHA=development
ENV RELEASE_SHA=$RELEASE_SHA
WORKDIR /app
COPY servers/bls-oews-mcp/pyproject.toml servers/bls-oews-mcp/uv.lock servers/bls-oews-mcp/readme.md servers/bls-oews-mcp/license ./
COPY servers/bls-oews-mcp/src ./src
RUN uv sync --frozen --no-dev
# Decompress and verify the bundled OEWS database at build time so a cold
# start opens it directly (root-owned, world-readable, opened read-only).
ENV BLS_OEWS_DATA_DIR=/app/oews-data
RUN /app/.venv/bin/python -c "from bls_oews_mcp import snapshot; snapshot.verify()"
RUN useradd --create-home mcp
USER mcp
ENV MCP_ALLOWED_HOSTS=container.internal MCP_ALLOWED_ORIGINS=https://bls-oews.1102tools.com
ENV BLS_HOSTED=1
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "bls_oews_mcp.http"]
