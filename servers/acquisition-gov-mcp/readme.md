# Acquisition.gov MCP

<!-- mcp-name: com.1102tools/acquisition-gov-mcp -->

Read-only, deterministic MCP access to the official Acquisition.gov FAR Overhaul (RFO) model-part pages, the posted agency-deviation index, official deviation PDFs, and a small allowlist of RFO guidance resources.

This server reports source content and metadata. It does **not** decide which rule governs a procurement. In particular, model deviation text is not treated as operative for an agency without that agency's posted deviation.

## Install

```bash
uvx acquisition-gov-mcp==1.0.6
```

The server uses stdio, requires no credentials, and defaults to a three-second cross-process interval between Acquisition.gov requests. `FEDERAL_API_MIN_INTERVAL_SECONDS` may increase or decrease that interval for controlled testing; production clients should retain three seconds.

## Request pacing

| Default setting | Value |
| --- | --- |
| Wait after each upstream request completes | **3 seconds** |
| Maximum upstream requests in flight per pacing identity | **1** |
| Rolling attempt counter in this pacer | **None**; provider quotas still apply |

The next request starts after the previous request's duration **plus 3 seconds**. This is a completion delay, not a 3-second start interval. Local processes sharing the same pacing directory and identity share this gate; a separate local counter does not create additional provider quota.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, shared credentials/IPs, configuration and hosting differences.

The hosted Acquisition.gov endpoint retains **60 HTTP requests per 60 seconds per incoming IP and Cloudflare location**, **4 active MCP HTTP requests**, a **55-second backend processing timeout**, and **64 KiB request bodies**. Its one-upstream-request-at-a-time gate is shared by all hosted users.

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
- Downloads are bounded to **5 MiB HTML / 25 MiB PDF**. HTML complexity, redirects, page selection and output length are also bounded.
- PDF extraction runs in one isolated parser subprocess at a time, with a **30-second deadline**, **2 MiB decoded page-stream limit**, and **160 MiB address-space / 8-second CPU limits on Linux**. macOS and Windows retain process isolation and explicit content/output limits without the Linux resource caps.
- HTTP 429 is not burst-retried. `Retry-After` is retained in the shared pacing state.
- If the Python TLS transport stalls against Acquisition.gov's CDN, the server may use an installed system `curl` for the same prevalidated URL; redirects remain disabled and revalidated by the server.
- Duplicate and conflicting index entries are returned with warnings instead of silently resolved.
- Scanned, encrypted, and malformed PDFs return explicit extraction status and metadata where possible.

Version 1.0.6 passed **181 offline tests**, including P0–P3 coverage and real stdio/HTTP smoke checks, plus **12 serialized live MCP calls across all five tools**. See [testing.md](testing.md) for evidence, exact limits, known scope and reproducible commands.
