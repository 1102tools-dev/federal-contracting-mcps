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

On 2026-08-22, the serialized live gate passed. The index, Part 10 model page, an indexed four-page NSF deviation PDF, and the FAQ each returned HTTP 200 with complete text extraction. A second serialized evidence capture also passed and recorded these upstream hashes:

- deviation index: `a62f55032e15bc1a3cc1e01df6ba8a7f30fc3056f7cbec4aacb4b4cad6402989`
- Part 10 model page: `65a41a3e8235cd0ceac42a8e8aaf4027459ce201fc1237357ecbf27437046c3a`
- indexed NSF deviation PDF: `eb571869435327f78fd683212f5ebe956b6547a84dcf939f2fe7c83e84d02417`
- FAQ: `b29b815050c94f5bb205ffd915dac4a02300c3da292b1ef8b15ab7f9472c7670`

These hashes are observations, not permanent expected values. A future hash change requires source review rather than automatic rejection.

## Release boundary

Package tests establish deterministic parsing and current upstream reachability. They do not establish that a deviation applies to a particular acquisition. That determination remains outside the server.
