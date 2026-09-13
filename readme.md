# Federal contracting MCPs

Read-only source tools for federal contracting research: opportunities, awards, company records, labor pricing, travel rates, regulations, and rulemaking.

[Explore 1102tools](https://1102tools.com) · [Find a matching prompt](https://github.com/1102tools-dev/federal-contracting-prompts) · [Download the MCP prompt guide](https://github.com/1102tools-dev/federal-contracting-prompts/blob/main/docs/1102tools-mcp-prompt-guide.pdf)

## Available in ChatGPT

USAspending, GSA CALC+, and eCFR are also available as published plugins in the ChatGPT directory. Open a listing below to install and connect it in ChatGPT. These hosted plugins require no user API key or local Python setup.

| Plugin | Install |
|---|---|
| USASpending | [Install in ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ee668cc248191a0bdb9911b546799) |
| GSA CALC+ | [Install in ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9eeeebfa8c81918945df0945276cb1) |
| eCFR | [Install in ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ef0341b04819192935fd4e5cd9b34) |

After connecting, choose a [matching prompt](https://github.com/1102tools-dev/federal-contracting-prompts) and replace the bracketed details. If a prompt lists multiple MCPs, connect every one it requires. For other sources or compatible MCP clients, use the server setup instructions below.

## Server catalog

Choose the sources your work needs. Each server directory contains its own README, code, configuration, tests, and release notes.

| MCP | Source coverage | Access |
|---|---|---|
| [SAM.gov](servers/sam-gov-mcp) | Opportunities, entity registrations, exclusions, and contract-award records. | User API key required |
| [USASpending](servers/usaspending-gov-mcp) | Awards, obligations, recipients, agencies, and reported subawards. | No user API key |
| [GSA CALC+](servers/gsa-calc-mcp) | Awarded labor-category ceiling rates and comparison data. | No user API key |
| [BLS OEWS](servers/bls-oews-mcp) | Occupational wages by geography and data year. | Optional key; limited keyless access |
| [GSA Per Diem](servers/gsa-perdiem-mcp) | Lodging and meals-and-incidental-expense rates by locality. | Personal key recommended; shared fallback |
| [eCFR](servers/ecfr-mcp) | Codified regulatory text, dates, and version comparisons. | No user API key |
| [Federal Register](servers/federal-register-mcp) | Published rules, notices, comment periods, and FAR cases. | No user API key |
| [Regulations.gov](servers/regulations-gov-mcp) | Rulemaking dockets, documents, and public comments. | Personal key recommended; shared fallback |
| [Acquisition.gov](servers/acquisition-gov-mcp) | FAR Overhaul model text, posted agency deviations, and guidance. | No user API key |

## Install

1. For the three published ChatGPT plugins, use the [directory links above](#available-in-chatgpt). For other sources or MCP clients, open the selected server's README and follow its installation and configuration instructions.
2. Configure any required API keys outside chat. The server README identifies the exact environment variables and access limits.
3. Restart or reconnect the client as needed, and confirm the server's tools are visible. Where provided, `get_access_status` reports local credential readiness; it does not validate the key with the upstream provider.
4. Choose a [prompt](https://github.com/1102tools-dev/federal-contracting-prompts), connect every MCP named beneath it, and replace the bracketed details.

A prompt does not install a server. Local command configuration and remote endpoint configuration differ; use the supported setup documented for the selected server. The ChatGPT directory links above identify the three published plugins; other servers use their documented setup instructions.

**USASpending package naming:** its package is `usaspending-gov-mcp` and its executable is `usaspending-mcp`. Use the exact configuration in [its README](servers/usaspending-gov-mcp); do not substitute a similarly named package.

## Use the sources together

- **Competitors and teaming:** combine USASpending award records with SAM.gov entity and exclusion evidence.
- **Pricing inputs:** compare BLS wages, CALC+ ceiling rates, and GSA travel rates while keeping their different pricing bases clear.
- **Regulations and policy:** use eCFR for codified text, Federal Register and Regulations.gov for rulemaking, and Acquisition.gov for FAR Overhaul model text and posted deviations.

Results reflect upstream data and retrieval time. Check dates, completeness, identity matches, and reported limitations. The MCPs provide evidence; they do not make a contracting or procurement-specific applicability decision.

## Request pacing and hosted limits

These are default MCP safeguards, measured in upstream requests to the government data source. One tool call can require multiple upstream requests. They are not agency-published quotas or guaranteed response times.

| MCP | Minimum interval between upstream starts | Maximum simultaneous upstream requests | Rolling upstream attempt budget |
| --- | --- | --- | --- |
| [USAspending](servers/usaspending-gov-mcp#request-pacing) | **0.6 seconds** | **4** | **500 per 5 minutes** |
| [GSA CALC+](servers/gsa-calc-mcp#request-pacing) | **0.6 seconds** | **2** | **500 per hour** |
| [eCFR JSON](servers/ecfr-mcp#request-pacing-and-cache) | **0.6 seconds** | **2**, shared with XML | **500 per 5 minutes**, shared with XML |
| [Federal Register](servers/federal-register-mcp#request-pacing) | **0.6 seconds** | **2** | **500 per 5 minutes** |

A **0.6-second interval** permits approximately **100 request starts per minute**, while budget and concurrency slots remain available. Two simultaneous requests means two may be awaiting responses; it does not mean two start every 0.6 seconds. A rolling window counts the immediately preceding five minutes or hour. Failed and cancelled upstream attempts remain counted.

**eCFR XML:** uncached XML is fetched one request at a time, with **three seconds after the previous XML request completes** before the next begins. Eligible XML responses are cached for **300 seconds**; a cache hit skips that XML download and its pacing wait. The cache holds **128 entries**, **32 MiB total**, and **2 MiB per entry**. Entries can be evicted earlier for capacity. Tools may still require JSON calls, such as resolving the latest date.

**Local versus hosted:** running the MCP server yourself gives you its local pacing budget. Processes using the same pacing directory and identity share that budget. Connecting any client to a 1102tools hosted endpoint uses the hosted budget, even if the client application runs on your computer.

| Limit | Local MCP process / stdio | Hosted endpoint / plugin for the four services above |
| --- | --- | --- |
| Upstream budget and concurrency | Shared by local processes using the same pacing directory and identity | **Shared by all users of that MCP**, regardless of their incoming IPs |
| Cloudflare entrance limit | Does not apply | **120 HTTP requests per 60 seconds**, per incoming IP and Cloudflare location |
| Hosted backend admission | Does not apply | **16 processing + 32 FIFO waiting = 48 accepted requests total**, shared across this service's users |
| Hosted total request deadline | Local/client timeouts apply | **55 seconds including upload, queue wait and processing**; startup and network latency may add time |

**Shared IPs and shared service capacity are separate limits.** People using the same calling IP can share the 120-per-minute entrance counter. With a cloud AI client, that IP may belong to the AI provider rather than your computer. Cloudflare's counter is approximate and location-specific. Different incoming IPs still share the hosted MCP's upstream budget. For example, ten hosted USAspending users share **500 upstream attempts per five minutes**, not 500 each. The four services above have separate budgets; USAspending use does not consume eCFR, CALC+ or Federal Register capacity.

Queued requests enter processing in arrival order when a slot opens. Disconnects, cancellations and deadlines free their slots. A full 48-request admission queue returns HTTP 429 with `Retry-After: 5`; requests exceeding the deadline return HTTP 504 if no response has started. The upstream limits above remain unchanged, so 16 processing slots do not mean 16 simultaneous agency API calls.

HTTP requests include connection setup, tool discovery and tool calls. They are not equivalent to upstream data requests. Government providers can apply additional limits, including to a shared outbound IP or API key. The 500-per-hour CALC+ policy supports short batches at 0.6-second starts; it does not permit continuous 500-per-five-minute use.

For all nine servers' exact defaults, retry intervals, cache rules, shared-IP behavior and budget persistence, see the [complete pacing reference](docs/pacing.md). Acquisition.gov's hosted entrance limit remains **60 HTTP requests per minute**. The other servers retain their documented three- or four-second completion delays. [Cloudflare rate-limit behavior](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).

## Testing and maintenance

Acquisition.gov has [181 offline tests and 47 successful live calls across all five tools](servers/acquisition-gov-mcp/testing.md), including P0–P3 coverage for HTML/PDF parsing and transport boundaries.

Current source-specific evidence is in each server's `testing.md` or `TESTING.md`, with changes in its changelog. Packages version independently. The shared request-pacing code reduces bursts and handles provider errors; it does not create additional provider quota.

This September 2026 documentation refresh changes the public entry points and removes retired setup links. It does not change MCP runtime behavior or claim a new live test of the entire suite. Earlier release narrative is preserved in [historical documentation](docs/readme-before-mcp-reboot.md).

## License and author

MIT licensed. Built by James Jenrette. Independently developed and not affiliated with or endorsed by any federal agency.
