FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=uv /uv /usr/local/bin/uv
ARG RELEASE_SHA=development
ENV RELEASE_SHA=$RELEASE_SHA
WORKDIR /app
COPY servers/usaspending-gov-mcp/pyproject.toml servers/usaspending-gov-mcp/uv.lock servers/usaspending-gov-mcp/readme.md servers/usaspending-gov-mcp/license ./
COPY servers/usaspending-gov-mcp/src ./src
RUN uv sync --frozen --no-dev
RUN useradd --create-home mcp
USER mcp
ENV USASPENDING_TOOL_PROFILE=full MCP_ALLOWED_HOSTS=container.internal MCP_ALLOWED_ORIGINS=https://usaspending.1102tools.com FEDERAL_API_MIN_INTERVAL_SECONDS=3
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "usaspending_gov_mcp.http"]
