FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=uv /uv /usr/local/bin/uv
ARG RELEASE_SHA=development
ENV RELEASE_SHA=$RELEASE_SHA
WORKDIR /app
COPY servers/regulations-gov-mcp/pyproject.toml servers/regulations-gov-mcp/uv.lock servers/regulations-gov-mcp/readme.md servers/regulations-gov-mcp/license ./
COPY servers/regulations-gov-mcp/src ./src
RUN uv sync --frozen --no-dev
RUN useradd --create-home mcp
USER mcp
ENV MCP_ALLOWED_HOSTS=container.internal MCP_ALLOWED_ORIGINS=https://regulations-gov.1102tools.com
ENV MCP_RESPONSE_CACHE_SECONDS=900 REGULATIONS_HOSTED=1
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "regulationsgov_mcp.http"]
