# Federal contracting MCPs

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![regression tests: 5,571](https://img.shields.io/badge/regression%20tests-5%2C571-007a59)](#testing-and-maintenance) [![Claude directory: 9 servers](https://img.shields.io/badge/Claude%20directory-9%20servers-172f2a)](#run-on-your-computer-or-in-one-click) [![ChatGPT directory: 4 servers](https://img.shields.io/badge/ChatGPT%20directory-4%20servers-172f2a)](#run-on-your-computer-or-in-one-click) [![hosting: Cloudflare + self-hosted](https://img.shields.io/badge/hosting-Cloudflare%20%2B%20self--hosted-172f2a?logo=cloudflare&logoColor=white)](#)

Free, open-source, read-only source tools for federal contracting research: opportunities, awards, company records, labor pricing, travel rates, regulations, and rulemaking.

[Explore 1102tools](https://1102tools.com) · [Find a matching prompt](https://github.com/1102tools-dev/federal-contracting-prompts) · [Download the MCP prompt guide](https://github.com/1102tools-dev/federal-contracting-prompts/blob/main/docs/1102tools-mcp-prompt-guide.pdf)

## Why these MCPs

- **Free.** MIT-licensed, with no subscription and no credits. Directory installs need no account or API key.
- **Tested.** 5,571 collected regression tests, including live-API tests, across 9 servers and 133 tools, with up to ten audit rounds per server against the live government APIs. Published testing records document each bug fixed and the tests added.
- **Listed, no keys.** All 9 servers are in the Claude directory and 4 are in the ChatGPT directory, with the rest in review for ChatGPT. Directory installs need no user API key.
- **One of a kind.** The only known MCP server for Acquisition.gov FAR Overhaul model text and agency class deviations.

See [how 1102tools compares](https://1102tools.com/compare) with paid GovCon platforms and other MCP servers.

<a id="available-in-claude-and-chatgpt"></a>

## Run on your computer or in one click

All nine MCPs run on your computer, and that is the setup we recommend for daily work. All nine are also in the Claude directory and four are in ChatGPT for one-click installs with no user API key. The rest are in review for ChatGPT.

| MCP | On your computer (recommended) | Claude | ChatGPT |
|---|---|---|---|
| SAM.gov | [Setup guide](servers/sam-gov-mcp#installation) (full 20-tool edition, free key) | [Add to Claude](https://claude.ai/directory/sam-gov-by-1102tools) (4-tool edition, no key) | In review |
| USAspending | [Setup guide](servers/usaspending-gov-mcp#installation) | [Add to Claude](https://claude.ai/directory/usaspending-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ee668cc248191a0bdb9911b546799) |
| GSA CALC+ | [Setup guide](servers/gsa-calc-mcp#installation) | [Add to Claude](https://claude.ai/directory/gsa-calc-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9eeeebfa8c81918945df0945276cb1) |
| BLS OEWS | [Setup guide](servers/bls-oews-mcp#installation) | [Add to Claude](https://claude.ai/directory/bls-oews-by-1102tools) | In review |
| GSA Per Diem | [Setup guide](servers/gsa-perdiem-mcp#installation) (free key) | [Add to Claude](https://claude.ai/directory/gsa-perdiem-by-1102tools) | In review |
| eCFR | [Setup guide](servers/ecfr-mcp#installation) | [Add to Claude](https://claude.ai/directory/ecfr-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ef0341b04819192935fd4e5cd9b34) |
| Acquisition.gov | [Setup guide](servers/acquisition-gov-mcp#install) | [Add to Claude](https://claude.ai/directory/acquisition-gov-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab2757102e08191887f75cc506c2333) |
| Federal Register | [Setup guide](servers/federal-register-mcp#installation) | [Add to Claude](https://claude.ai/directory/federal-register-by-1102tools) | In review |
| Regulations.gov | [Setup guide](servers/regulations-gov-mcp#installation) (free key) | [Add to Claude](https://claude.ai/directory/regulations-gov-by-1102tools) | In review |

| | On your computer (recommended) | One click in Claude or ChatGPT |
|---|---|---|
| **Setup** | About 5 minutes: install uv, then add a few lines to your app's settings | One click from the directory. Nothing to install |
| **Works in** | Claude and ChatGPT desktop apps, Claude Code, Codex, Cursor, and other MCP apps on a desktop or laptop | Claude and ChatGPT on the web, desktop, and phone |
| **Request budget** | Yours alone | Shared with everyone using that server |
| **API keys** | Your own free key for GSA Per Diem and Regulations.gov: 1,000 requests an hour, yours alone. Six servers need no key | None needed. The server's keys are shared by all users |
| **Relies on** | Your computer and the agency's site | Cloudflare and that 1102tools server being up |
| **Your lookups** | Go straight from your computer to the agency | Pass through Cloudflare. 1102tools doesn't store or log them |
| **SAM.gov** | Full edition, 20 tools: adds entity registrations, exclusions, and SBA certifications. Needs a free SAM.gov key, which has a daily limit | 4 tools for opportunities, award notices, and justifications. No key and no daily limit |

**Use one click if** you're on your phone, your work computer won't let you install software, or you want SAM.gov opportunity search without a key.

- **SAM.gov comes in two editions.** The directory version (in the Claude directory) has 4 keyless tools for contract opportunities, award notices, and justifications. The full version has 20 tools and adds entity registrations, SBA certifications, exclusions, and contract award records. It needs a free SAM.gov key and a local install; there is no one-click directory install for it. [Compare the editions](servers/sam-gov-mcp#two-editions-hosted-or-full).
- **Hosted privacy.** The hosted servers don't store your queries, results, or conversations, and request logging is turned off. Their code and Cloudflare setup are public in [federal-contracting-mcps](deploy). Cloudflare still handles connection data such as IP addresses, and Claude or ChatGPT handles your conversation under its own privacy policy.

### Set up on your computer

1. **Install uv**, the free tool that downloads and runs the servers ([uv install guide](https://docs.astral.sh/uv/getting-started/installation/)).

   macOS or Linux:

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   Windows (PowerShell):

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. **Add the server to your app.** Each server's setup guide has the exact command.
   - **Claude desktop app:** Settings → Developer → Edit Config. Paste the server's block from its setup guide into `claude_desktop_config.json`, save, and restart Claude.
   - **ChatGPT desktop app:** Settings → MCP servers → Add server. Choose STDIO, enter `uvx` and the arguments from the setup guide, save, and restart.
   - **Claude Code or Codex:** one command. For example, USAspending:

     ```sh
     claude mcp add usaspending -- uvx --from usaspending-gov-mcp usaspending-mcp
     codex mcp add usaspending -- uvx --from usaspending-gov-mcp usaspending-mcp
     ```

3. **Add a key if the server needs one.** SAM.gov, GSA Per Diem, and Regulations.gov take a free key from the agency. The setup guide shows where to get it and which setting to use.

If your app says it can't find `uvx`, use its full path instead: run `which uvx` on macOS or `where uvx` on Windows.

After connecting, choose a [matching prompt](https://github.com/1102tools-dev/federal-contracting-prompts) and replace the bracketed details. If a prompt lists multiple MCPs, connect every one it requires. For other sources or compatible MCP clients, use the server setup instructions below.

## Server catalog

Choose the sources your work needs. Each server directory contains its own README, code, configuration, tests, and release notes. SAM.gov comes in two editions: installing it from Claude or ChatGPT gives you the 4-tool directory edition, and the 20-tool full edition is a separate local install with your own free key. The directory edition's 27 tests (hosted service and nightly data load) are not in the 5,571 package total.

| MCP | Source coverage | Tools | Tests | Access |
|---|---|---|---|---|
| [SAM.gov, directory edition](servers/sam-gov-mcp#hosted-edition-4-tools-no-key) | Contract opportunities, award notices, and justifications only, from SAM.gov's daily public file. This is what you get when you install SAM.gov from Claude or ChatGPT. | 4 | 27 | No key. [Claude directory](https://claude.ai/directory/sam-gov-by-1102tools); ChatGPT in review |
| [SAM.gov, full edition](servers/sam-gov-mcp) | Opportunities plus entity registrations, SBA certifications, exclusions, reps and certs, integrity records, contract-award records, the federal hierarchy, and subawards. | 20 | 1,155 | Free SAM.gov key. Local install only; not in the directories |
| [USAspending](servers/usaspending-gov-mcp) | Awards, obligations, recipients, agencies, and reported subawards. | 55 | 2,174 | No key |
| [GSA CALC+](servers/gsa-calc-mcp) | Awarded labor-category ceiling rates and comparison data. | 8 | 379 | No key |
| [BLS OEWS](servers/bls-oews-mcp) | Occupational wages by geography, industry, and occupation (current OEWS release). | 8 | 276 | No key (BLS data ships with the package since v1.1.0); hosted edition in the Claude directory |
| [GSA Per Diem](servers/gsa-perdiem-mcp) | Lodging and meals-and-incidental-expense rates by locality. | 7 | 544 | Local: free key for city lookups (ZIP, state, and M&IE work without one). Hosted: no key |
| [eCFR](servers/ecfr-mcp) | Codified regulatory text, dates, and version comparisons. | 13 | 320 | No key |
| [Acquisition.gov](servers/acquisition-gov-mcp) | FAR Overhaul model text, posted agency deviations, and guidance. | 5 | 239 | No key |
| [Federal Register](servers/federal-register-mcp) | Published rules, notices, comment periods, and FAR cases. | 8 | 243 | No key |
| [Regulations.gov](servers/regulations-gov-mcp) | Rulemaking dockets, documents, and public comments. | 9 | 241 | Local: free key. Hosted: no key |

## Install

1. To run a server on your computer, follow [Set up on your computer](#set-up-on-your-computer) and the server's README. For one-click installs in Claude or ChatGPT, use the [directory links above](#run-on-your-computer-or-in-one-click).
2. Configure any required API keys outside chat. The server README identifies the exact environment variables and access limits.
3. Restart or reconnect the client as needed, and confirm the server's tools are visible. Where provided, `get_access_status` reports local credential readiness; it does not validate the key with the upstream provider.
4. Choose a [prompt](https://github.com/1102tools-dev/federal-contracting-prompts), connect every MCP named beneath it, and replace the bracketed details.

A prompt does not install a server. Local command configuration and remote endpoint configuration differ; use the supported setup documented for the selected server. The directory links above identify the published Claude and ChatGPT listings; other servers use their documented setup instructions.

**USAspending package naming:** its package is `usaspending-gov-mcp` and its executable is `usaspending-mcp`. Use the exact configuration in [its README](servers/usaspending-gov-mcp); do not substitute a similarly named package.

## Use the sources together

- **Competitors and teaming:** combine USAspending award records with SAM.gov entity and exclusion evidence from the full local edition.
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
| Cloudflare entrance limit | Does not apply | **600 HTTP requests per 60 seconds** for Claude and ChatGPT addresses (Anthropic's and OpenAI's published ranges), **120** for every other address; per incoming IP and Cloudflare location |
| Hosted backend admission | Does not apply | **16 processing + 32 FIFO waiting = 48 accepted requests total**, shared across this service's users |
| Hosted total request deadline | Local/client timeouts apply | **55 seconds including upload, queue wait and processing**; startup and network latency may add time |

**Shared IPs and shared service capacity are separate limits.** People using the same calling IP can share its entrance counter. With a cloud AI client, that IP may belong to the AI provider rather than your computer. Cloudflare's counter is approximate and location-specific. Different incoming IPs still share the hosted MCP's upstream budget. For example, ten hosted USAspending users share **500 upstream attempts per five minutes**, not 500 each. The four services above have separate budgets; USAspending use does not consume eCFR, CALC+ or Federal Register capacity.

Queued requests enter processing in arrival order when a slot opens. Disconnects, cancellations and deadlines free their slots. A full 48-request admission queue returns HTTP 429 with `Retry-After: 5`; requests exceeding the deadline return HTTP 504 if no response has started. The upstream limits above remain unchanged, so 16 processing slots do not mean 16 simultaneous agency API calls.

HTTP requests include connection setup, tool discovery and tool calls. They are not equivalent to upstream data requests. Government providers can apply additional limits, including to a shared outbound IP or API key. The 500-per-hour CALC+ policy supports short batches at 0.6-second starts; it does not permit continuous 500-per-five-minute use.

For all nine servers' exact defaults, retry intervals, cache rules, shared-IP behavior and budget persistence, see the [complete pacing reference](docs/pacing.md). Acquisition.gov's hosted endpoint answers from a daily copy stored in Cloudflare D1 and uses the same entrance limits. The other servers retain their documented three- or four-second completion delays. [Cloudflare rate-limit behavior](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).

## Testing and maintenance

Acquisition.gov has [236 offline tests and recorded live checks across all five tools](servers/acquisition-gov-mcp/testing.md), including P0–P3 coverage for HTML/PDF parsing and transport boundaries.

Current source-specific evidence is in each server's `testing.md` or `TESTING.md`, with changes in its changelog. Packages version independently. The shared request-pacing code reduces bursts and handles provider errors; it does not create additional provider quota.

This September 2026 documentation refresh changes the public entry points and removes retired setup links. It does not change MCP runtime behavior or claim a new live test of the entire suite. Earlier release narrative is preserved in [historical documentation](docs/readme-before-mcp-reboot.md).

## License and author

MIT licensed. Built by James Jenrette. Independently developed and not affiliated with or endorsed by any federal agency.
