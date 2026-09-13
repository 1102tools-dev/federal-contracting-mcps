FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
ARG RELEASE_SHA=development
ENV RELEASE_SHA=$RELEASE_SHA
WORKDIR /app
COPY servers/acquisition-gov-mcp/pyproject.toml servers/acquisition-gov-mcp/uv.lock servers/acquisition-gov-mcp/readme.md servers/acquisition-gov-mcp/license ./
COPY servers/acquisition-gov-mcp/src ./src
RUN uv sync --frozen --no-dev
RUN useradd --create-home mcp
USER mcp
ENV MCP_ALLOWED_HOSTS=container.internal MCP_ALLOWED_ORIGINS=https://acquisition-gov.1102tools.com FEDERAL_API_MIN_INTERVAL_SECONDS=3
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "acquisition_gov_mcp.http"]
