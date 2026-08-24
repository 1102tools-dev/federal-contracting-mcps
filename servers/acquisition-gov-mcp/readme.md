# Acquisition.gov MCP

<!-- mcp-name: com.1102tools/acquisition-gov-mcp -->

Read-only, deterministic MCP access to the official Acquisition.gov FAR Overhaul (RFO) model-part pages, the posted agency-deviation index, official deviation PDFs, and a small allowlist of RFO guidance resources.

This server reports source content and metadata. It does **not** decide which rule governs a procurement. In particular, model deviation text is not treated as operative for an agency without that agency's posted deviation.

## Install

```bash
uvx acquisition-gov-mcp==1.0.2
```

The server uses stdio, requires no credentials, and defaults to a three-second cross-process interval between Acquisition.gov requests. `FEDERAL_API_MIN_INTERVAL_SECONDS` may increase or decrease that interval for controlled testing; production clients should retain three seconds.

## Tools

| Tool | Purpose |
|---|---|
| `list_rfo_parts(part?, agency?, updated_since?)` | List RFO model parts with official source dates and matching posted-deviation counts. |
| `get_rfo_part(part, section?, cursor?, max_characters?)` | Retrieve parsed, paginated model text for one FAR part. |
| `list_rfo_agency_deviations(agency?, part?, limit?)` | Discover posted deviation documents. At least one filter is required. |
| `get_rfo_agency_deviation(source_id, page_start?, page_end?)` | Resolve only an indexed source ID and return page-numbered PDF text and document-found applicability language. |
| `get_rfo_guidance(resource, heading?, cursor?)` | Retrieve the FAQ, policy-and-guidance page, or FAR Council deviation-guidance PDF. |

Every retrieved source includes a canonical URL, UTC retrieval time, SHA-256 content hash, extraction status, and warnings. Agency PDF dates and applicability are returned only when labeled language is found inside the document; filenames are never used to infer them.

## Safety boundary

- Only `https://acquisition.gov` and `https://www.acquisition.gov` are allowed.
- Redirect targets are revalidated; credentials, explicit ports, arbitrary hosts, and private IP targets are rejected.
- Responses are limited by content type, bytes, redirects, pages, and output length.
- HTTP 429 is not burst-retried. `Retry-After` is retained in the shared pacing state.
- If the Python TLS transport stalls against Acquisition.gov's CDN, the server may use an installed system `curl` for the same prevalidated URL; redirects remain disabled and revalidated by the server.
- Duplicate and conflicting index entries are returned with warnings instead of silently resolved.
- Scanned, encrypted, and malformed PDFs return explicit extraction status and metadata where possible.

See [testing.md](testing.md) for the release evidence and live-gate instructions.
