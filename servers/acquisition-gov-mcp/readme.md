# Acquisition.gov MCP

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 5](https://img.shields.io/badge/tools-5-007a59)](#) [![regression tests: 239](https://img.shields.io/badge/regression%20tests-239-007a59)](testing.md)

<!-- mcp-name: com.1102tools/acquisition-gov-mcp -->

Free, open-source, read-only, deterministic MCP access to the official Acquisition.gov FAR Overhaul (RFO) model-part pages, the posted agency-deviation index, official deviation PDFs, and a small allowlist of RFO guidance resources.

This server reports source content and metadata. It does **not** decide which rule governs a procurement. In particular, model deviation text is not treated as operative for an agency without that agency's posted deviation.

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#install) | [Install](https://claude.ai/directory/acquisition-gov-by-1102tools) | [Install](https://chatgpt.com/plugins/plugin_asdk_app_6ab2757102e08191887f75cc506c2333) |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#far-overhaul-and-agency-deviations)

## Install

```bash
uvx acquisition-gov-mcp==1.0.8
```

The server uses stdio and requires no credentials.

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

Version 1.0.8 passed **236 offline tests**, including **55 independent-review regressions**, real stdio/HTTP smoke checks, parser isolation, cancellation and per-tool correctness cases. See [testing.md](testing.md) for evidence, exact limits, known scope and reproducible commands.
