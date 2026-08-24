FROM python:3.12-slim

# sam-gov-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir sam-gov-mcp==1.0.10

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["sam-gov-mcp"]
