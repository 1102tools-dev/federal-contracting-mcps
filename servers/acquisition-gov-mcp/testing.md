# Acquisition.gov MCP test record

Version: `1.0.0`

## Deterministic suite

Run:

```bash
uv sync --dev
uv run pytest -q
uv build
```

The offline suite covers:

- captured RFO index, model-part, and guidance HTML;
- duplicate and multi-part agency-deviation entries;
- invalid parts, dates, cursors, filters, and output limits;
- native-text, multi-page, blank/image-only, and malformed PDFs;
- page ranges and document-labeled issuance, effective, expiration, and applicability text;
- redirect allowlisting, SSRF targets, content type, response size, and 429 `Retry-After` behavior;
- bounded system-`curl` compatibility fallback after a Python transport failure;
- exact tool inventory and strict rejection of unknown parameters.

Local stdio startup and discovery also returned server `acquisition-gov` version `1.0.0` with exactly the five documented tools.

The fixtures are parser contracts, not current-policy evidence.

## Live gate

Run only as a serialized release check:

```bash
ACQUISITION_GOV_LIVE_TESTS=1 uv run pytest tests/test_live.py -q
```

The live gate retrieves the official deviation index, one model part, one indexed agency PDF page, and the FAQ. It records the page hashes returned by the tools, so upstream changes are observable. Live content must be reviewed before release when fixture and upstream hashes or structure diverge.

As of 2026-08-21, the index retrieval succeeds, but the linked model-part, PDF, and FAQ routes intermittently time out at the Acquisition.gov CDN before returning response headers. This is an open upstream live-release gate; the deterministic parser and safety suites remain green.

## Release boundary

Package tests establish deterministic parsing and current upstream reachability. They do not establish that a deviation applies to a particular acquisition. That determination remains outside the server.
