# Federal contracting MCPs

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![regression tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/1102tools-dev/federal-contracting-mcps/main/badges/tests-total.json)](#testing) [![prompts](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2F1102tools.com%2Fprompts.json&query=%24.prompts.length&label=prompts&color=007a59)](https://1102tools.com/#prompts)

[![Cloudflare Workers](https://img.shields.io/badge/hosted%20on-Cloudflare%20Workers-F38020?logo=cloudflare&logoColor=white)](https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/deploy)

Free, open-source, read-only source tools for federal contracting research: opportunities, awards, company records, labor pricing, travel rates, regulations, and rulemaking.

[Explore 1102tools](https://1102tools.com) · [Find a matching prompt](https://github.com/1102tools-dev/federal-contracting-prompts) · [Download the MCP prompt guide](https://github.com/1102tools-dev/federal-contracting-prompts/blob/main/docs/1102tools-mcp-prompt-guide.pdf) · [Demo videos on YouTube](https://www.youtube.com/@1102tools)

## Why these MCPs

- **Free.** MIT-licensed, with no subscription and no credits. Hosted installs need no account or API key.
- **Tested.** Checked against the government sources, reviewed by Claude Code and Codex, and backed by thousands of regression tests. [How it's tested](#testing).
- **Listed.** Hosted installs are in the Claude and ChatGPT directories and need no user API key. [See where each server is listed](#local-or-hosted).
- **One of a kind.** The only known MCP server for Acquisition.gov FAR Overhaul model text and agency class deviations.

## Testing

- **Checked against the source.** Realistic contracting questions run against each server, and the answers are compared with the government source: the numbers, the dates, the citations.
- **Worst problems first.** Every problem is ranked by how much it could mislead you, from a wrong answer you might act on down to a minor wording issue. Wrong answers are fixed first.
- **Reviewed by more than one AI.** Audits run with both Claude Code and Codex, and every finding is checked by a second reviewer before a fix ships.
- **Fixed for good.** Every fix gets a regression test so the problem can't come back, and thousands of these tests run before each release.

| Server | Testing record |
|---|---|
| SAM.gov | [Testing](servers/sam-gov-mcp/testing.md) |
| USAspending | [Testing](servers/usaspending-gov-mcp/testing.md) |
| GSA CALC+ | [Testing](servers/gsa-calc-mcp/testing.md) |
| BLS OEWS | [Testing](servers/bls-oews-mcp/testing.md) |
| GSA Per Diem | [Testing](servers/gsa-perdiem-mcp/testing.md) |
| eCFR | [Testing](servers/ecfr-mcp/testing.md) |
| Federal Register | [Testing](servers/federal-register-mcp/testing.md) |
| Regulations.gov | [Testing](servers/regulations-gov-mcp/testing.md) |
| Acquisition.gov | [Testing](servers/acquisition-gov-mcp/testing.md) |

Release details are in the [October 10, 2026 release record](docs/releases/2026-10-10-content-audit.md).

See [how 1102tools compares](https://1102tools.com/compare) with paid GovCon platforms and other MCP servers.

<a id="available-in-claude-and-chatgpt"></a>

## Local or hosted

Every MCP works in Claude or ChatGPT two ways. **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. **Hosted** runs it on Cloudflare, so it works anywhere you use Claude or ChatGPT. Local is the better setup for daily work, and you don't have to set it up by hand: give your AI the [local setup guide](#local-setup) and ask it to set it up or walk you through it.

The table shows where each server is listed as a hosted install.

| MCP | Local setup (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|---|
| SAM.gov | [Setup guide](servers/sam-gov-mcp#installation) (full 20-tool edition, free key) | [Add to Claude](https://claude.ai/directory/sam-gov-by-1102tools) (6-tool edition, no key) | In review |
| USAspending | [Setup guide](servers/usaspending-gov-mcp#installation) | [Add to Claude](https://claude.ai/directory/usaspending-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ee668cc248191a0bdb9911b546799) |
| GSA CALC+ | [Setup guide](servers/gsa-calc-mcp#installation) | [Add to Claude](https://claude.ai/directory/gsa-calc-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9eeeebfa8c81918945df0945276cb1) |
| BLS OEWS | [Setup guide](servers/bls-oews-mcp#installation) | [Add to Claude](https://claude.ai/directory/bls-oews-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab872bf5360819186af0917c923e57e) |
| GSA Per Diem | [Setup guide](servers/gsa-perdiem-mcp#installation) (free key) | [Add to Claude](https://claude.ai/directory/gsa-perdiem-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab85f56d4ec8191970ab75fdeddd2f9) |
| eCFR | [Setup guide](servers/ecfr-mcp#installation) | [Add to Claude](https://claude.ai/directory/ecfr-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ef0341b04819192935fd4e5cd9b34) |
| Federal Register | [Setup guide](servers/federal-register-mcp#installation) | [Add to Claude](https://claude.ai/directory/federal-register-by-1102tools) | In review |
| Regulations.gov | [Setup guide](servers/regulations-gov-mcp#installation) (free key) | [Add to Claude](https://claude.ai/directory/regulations-gov-by-1102tools) | In review |
| Acquisition.gov | [Setup guide](servers/acquisition-gov-mcp#install) | [Add to Claude](https://claude.ai/directory/acquisition-gov-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab2757102e08191887f75cc506c2333) |

| | Local | Hosted |
|---|---|---|
| **Why use it** | Your own full rate limits, so you skip any congestion on hosted | Always up to date. No setup or keys, and it works in Claude or ChatGPT anywhere |
| **Works in** | Claude or ChatGPT desktop apps and other AI apps, on a desktop or laptop | Claude or ChatGPT on web, desktop, and phone |
| **Setup** | Ask your AI to set it up or walk you through it, using the setup guide. Free keys for SAM.gov, Regulations.gov, and GSA Per Diem | Add it from the Claude or ChatGPT directory. No keys |
| **Rate limits** | Your own, in full | Pooled across all users. Your lookups stay private |
| **Relies on** | Government sources | Government sources and Cloudflare |
| **Privacy** | Runs on your computer. Nothing passes through 1102tools | No tracking. Searches aren't logged and IP addresses aren't kept. [Details](https://1102tools.com/privacy) |
| **Updates** | Manual. Local installs don't update themselves. Ask your AI to update them | Automatic. Always runs the latest release |
| **SAM.gov** | Full edition: 20 tools, free key | 6 tools, no key |

**Use hosted if** you're on your phone, your work computer blocks installs, or you want SAM.gov opportunity, registration and exclusion search without a key.

- **SAM.gov comes in two editions.** Hosted has 6 keyless tools for contract opportunities, public entity registrations, and exclusions, built from SAM.gov's public files. Local is the full edition: 20 tools that add live API lookups, detailed SBA certification dates, reps and certs, integrity records, and contract award records, with a free SAM.gov key. [Compare the editions](servers/sam-gov-mcp#two-editions-hosted-or-full).
- **Hosted privacy.** Hosted services cache some public government responses temporarily in bounded memory to reduce repeated source requests. No conversations or query/result logs are retained. Public data snapshots are maintained separately. Their code and Cloudflare setup are public in [federal-contracting-mcps](deploy). Cloudflare still handles connection data such as IP addresses, and Claude or ChatGPT handles your conversation under its own privacy policy.

### Local setup

**You don't have to do this by hand.** Give this page's link to Claude or ChatGPT and ask it to set up the MCP you want, or to walk you through it. The steps:

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

3. **Add a key if the server needs one.** SAM.gov, Regulations.gov, and GSA Per Diem take a free key from the agency. The setup guide shows where to get it and which setting to use.

**Updating.** Local installs don't update themselves. To get the latest version, ask your AI to update the server, or run it with `@latest` (for example `uvx usaspending-gov-mcp@latest`).

If your app says it can't find `uvx`, use its full path instead: run `which uvx` on macOS or `where uvx` on Windows.

## Start with a question

1. Pick a request from the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts). Each one names the MCPs it needs.
2. Connect those MCPs, local or hosted, from the table above.
3. Fill in the bracketed details, such as `[AGENCY]` or `[COMPANY]`, and send it. Ask for source links and dates.

| What you want to do | MCP to connect | Matching prompts |
|---|---|---|
| Find solicitations and check company registrations | [SAM.gov](servers/sam-gov-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#catching-opportunities) |
| Research contracts, grants, competitors, agencies, and recompetes | [USAspending](servers/usaspending-gov-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#competitor-intelligence) |
| Compare awarded labor-rate ceilings | [GSA CALC+](servers/gsa-calc-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#gsa-calc) |
| Look up occupation and location wage data | [BLS OEWS](servers/bls-oews-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#bls-oews) |
| Estimate lodging and meals for travel | [GSA Per Diem](servers/gsa-perdiem-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#gsa-per-diem) |
| Read and compare codified FAR, DFARS, and CFR text | [eCFR](servers/ecfr-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#ecfr) |
| Follow proposed rules, final rules, and FAR cases | [Federal Register](servers/federal-register-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#federal-register) |
| Explore rulemaking dockets and public comments | [Regulations.gov](servers/regulations-gov-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#regulationsgov) |
| Research FAR Overhaul model text and posted agency deviations | [Acquisition.gov](servers/acquisition-gov-mcp) | [Open prompts](https://github.com/1102tools-dev/federal-contracting-prompts#far-overhaul-and-agency-deviations) |

Results reflect government-source data and retrieval time or the bundled snapshot release. Check source and as-of metadata; bundled data does not make a fresh upstream request on every lookup. Check dates, completeness, identity matches, and reported limitations. The MCPs provide evidence; they do not make a contracting or procurement-specific applicability decision.

## License and author

MIT licensed. Independently developed and not affiliated with or endorsed by any federal agency.
