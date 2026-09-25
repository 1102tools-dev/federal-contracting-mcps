FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=uv /uv /usr/local/bin/uv
ARG RELEASE_SHA=development
ENV RELEASE_SHA=$RELEASE_SHA
WORKDIR /app
COPY servers/gsa-perdiem-mcp/pyproject.toml servers/gsa-perdiem-mcp/uv.lock servers/gsa-perdiem-mcp/readme.md servers/gsa-perdiem-mcp/license ./
COPY servers/gsa-perdiem-mcp/src ./src
RUN uv sync --frozen --no-dev
RUN useradd --create-home mcp
USER mcp
ENV MCP_ALLOWED_HOSTS=container.internal MCP_ALLOWED_ORIGINS=https://gsa-perdiem.1102tools.com
ENV MCP_RESPONSE_CACHE_SECONDS=86400
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "gsa_perdiem_mcp.http"]
