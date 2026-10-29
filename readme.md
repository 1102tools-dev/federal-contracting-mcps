# Federal contracting MCPs

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![regression tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/1102tools-dev/federal-contracting-mcps/main/badges/tests-total.json)](#testing) [![prompts](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2F1102tools.com%2Fprompts.json&query=%24.prompts.length&label=prompts&color=007a59)](https://1102tools.com/#prompts)

[![Cloudflare Workers](https://img.shields.io/badge/hosted%20on-Cloudflare%20Workers-F38020?logo=cloudflare&logoColor=white)](https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/deploy)

### Ask Claude or ChatGPT about federal contracts. Get answers from the government's own records.

Free MCP servers that plug your AI into SAM.gov, USAspending, GSA CALC+, BLS wage data, GSA Per Diem, the FAR, the Federal Register, Regulations.gov and Acquisition.gov. Find opportunities, size up the incumbent, price labor and travel, and check the rules without leaving the chat.

**[Install in Claude or ChatGPT](#local-or-hosted)** · [Watch a demo](https://www.youtube.com/watch?v=2CnYSrNIuWU) · [Find a ready-made prompt](https://github.com/1102tools-dev/federal-contracting-prompts) · [1102tools.com](https://1102tools.com)

<a href="https://www.youtube.com/watch?v=2CnYSrNIuWU"><img src="https://img.youtube.com/vi/2CnYSrNIuWU/maxresdefault.jpg" alt="Watch: You don't have to pay for AI on SAM.gov" width="560"></a>

## Why people use it

| Instead of | You get |
|---|---|
| Paying hundreds to thousands of dollars a year for a GovCon platform | $0. No subscription, no credits, no 1102tools account |
| Clicking through agency websites and spreadsheet exports | One question in the AI you already use |
| An AI guessing at award amounts, labor rates and FAR text | Answers pulled from the government source, with the record and the date |
| Waiting on IT to install software | Hosted versions in the Claude and ChatGPT directories. No key |

- **Built by a federal contracting officer.** It's made by someone who sits on the buying side, so it looks where the buyer looks.
- **Checked against the source.** Every server is tested against its government source, and thousands of regression tests run before each release. [How it's tested](#testing)
- **One of a kind.** The only known MCP server for Acquisition.gov FAR Overhaul model text and agency class deviations.
- **Private.** No tracking. Searches aren't logged and IP addresses aren't kept. Run it locally and nothing passes through 1102tools at all.

[See how 1102tools compares](https://1102tools.com/compare) with paid GovCon platforms and other MCP servers.

<a href="https://www.youtube.com/watch?v=TlPaQOu2fgY"><img src="https://img.youtube.com/vi/TlPaQOu2fgY/maxresdefault.jpg" alt="Watch: USAspending vs SAM.gov, same contract data without the 1,000-a-day limit" width="560"></a>

## What you can ask

| MCP | Best for | Try asking | Demo |
|---|---|---|---|
| [SAM.gov](https://1102tools.com/mcp/sam-gov) | Finding opportunities to bid on. The full version looks up awards too. | "Find open small business set-aside solicitations for NAICS 541512 that close in the next 30 days." | [Watch](https://www.youtube.com/watch?v=2CnYSrNIuWU) |
| [USAspending](https://1102tools.com/mcp/usaspending) | Looking up past awards: who won, how much, and from which agency. | "Who holds the incumbent contract for this requirement, and when does it expire?" | [Watch](https://www.youtube.com/watch?v=j8rK_l_7u5Y) |
| [GSA CALC+](https://1102tools.com/mcp/gsa-calc) | Pricing labor in proposals and IGCEs against rates GSA has already awarded. | "Is my proposed labor rate competitive with awarded GSA rates?" | [Watch](https://www.youtube.com/watch?v=AYJNeIwnEjM) |
| [BLS OEWS](https://1102tools.com/mcp/bls-oews) | Pricing labor in proposals and IGCEs with market wage data. | "Build a fully burdened labor rate from BLS wages for my price proposal." | [Watch](https://www.youtube.com/watch?v=s8KXOP0GE_E) |
| [GSA Per Diem](https://1102tools.com/mcp/gsa-per-diem) | Pricing travel in proposals and IGCEs. | "What travel costs should I include for a three-day site visit to Denver?" | [Watch](https://www.youtube.com/watch?v=lQxSMRltO-w) |
| [eCFR](https://1102tools.com/mcp/ecfr) | A FAR answer when there's no contracting officer to ask. | "What does FAR Part 19 say about small business set-asides?" | [Watch](https://www.youtube.com/watch?v=MPmbY_7JOrQ) |
| [Federal Register](https://1102tools.com/mcp/federal-register) | Seeing which FAR rules are coming and when comments close. | "Which proposed FAR rules could affect small contractors, and when do comments close?" | [Watch](https://www.youtube.com/watch?v=uVpZIWXz5j4) |
| [Regulations.gov](https://1102tools.com/mcp/regulations-gov) | Reading what contractors said about a rule before you comment. | "What did other contractors say in their comments on this FAR rule?" | [Watch](https://www.youtube.com/watch?v=5tLd2EobUaw) |
| [Acquisition.gov](https://1102tools.com/mcp/acquisition-gov) | Seeing which FAR Overhaul changes an agency has adopted. | "Has this agency issued a class deviation that affects my proposal?" | [Watch](https://www.youtube.com/watch?v=FyFrYhKA7h8) |

Want a stronger starting point? The [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts) has ready-made requests for capture, pricing, competitor research and FAR questions. Each one names the MCPs it needs.

<a id="available-in-claude-and-chatgpt"></a>

## Local or hosted

Every MCP works in Claude or ChatGPT two ways. **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. **Hosted** runs it on Cloudflare, so it works anywhere you use Claude or ChatGPT. Local is the better setup for daily work, and you don't have to set it up by hand: give your AI the [local setup guide](#local-setup) and ask it to set it up or walk you through it.

The table shows where each server is listed as a hosted install. Each name links to that server's page.

| MCP | Local setup (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|---|
| [SAM.gov](https://1102tools.com/mcp/sam-gov) | [Setup guide](servers/sam-gov-mcp#installation) (full 20-tool edition, free key) | [Add to Claude](https://claude.ai/directory/sam-gov-by-1102tools) (6-tool edition, no key) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ad986ea765081919a8856a5b5233f40) (6-tool edition, no key) |
| [USAspending](https://1102tools.com/mcp/usaspending) | [Setup guide](servers/usaspending-gov-mcp#installation) | [Add to Claude](https://claude.ai/directory/usaspending-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ee668cc248191a0bdb9911b546799) |
| [GSA CALC+](https://1102tools.com/mcp/gsa-calc) | [Setup guide](servers/gsa-calc-mcp#installation) | [Add to Claude](https://claude.ai/directory/gsa-calc-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9eeeebfa8c81918945df0945276cb1) |
| [BLS OEWS](https://1102tools.com/mcp/bls-oews) | [Setup guide](servers/bls-oews-mcp#installation) | [Add to Claude](https://claude.ai/directory/bls-oews-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab872bf5360819186af0917c923e57e) |
| [GSA Per Diem](https://1102tools.com/mcp/gsa-per-diem) | [Setup guide](servers/gsa-perdiem-mcp#installation) (free key) | [Add to Claude](https://claude.ai/directory/gsa-perdiem-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab85f56d4ec8191970ab75fdeddd2f9) |
| [eCFR](https://1102tools.com/mcp/ecfr) | [Setup guide](servers/ecfr-mcp#installation) | [Add to Claude](https://claude.ai/directory/ecfr-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ef0341b04819192935fd4e5cd9b34) |
| [Federal Register](https://1102tools.com/mcp/federal-register) | [Setup guide](servers/federal-register-mcp#installation) | [Add to Claude](https://claude.ai/directory/federal-register-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ad989cff4d4819187ca95781427b399) |
| [Regulations.gov](https://1102tools.com/mcp/regulations-gov) | [Setup guide](servers/regulations-gov-mcp#installation) (free key) | [Add to Claude](https://claude.ai/directory/regulations-gov-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ad988bee41c8191a72c0b0e94d84eb9) |
| [Acquisition.gov](https://1102tools.com/mcp/acquisition-gov) | [Setup guide](servers/acquisition-gov-mcp#install) | [Add to Claude](https://claude.ai/directory/acquisition-gov-by-1102tools) | [Add to ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6ab2757102e08191887f75cc506c2333) |

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
     claude mcp add usaspending -- uvx --refresh-package usaspending-gov-mcp --from usaspending-gov-mcp usaspending-mcp
     codex mcp add usaspending -- uvx --refresh-package usaspending-gov-mcp --from usaspending-gov-mcp usaspending-mcp
     ```

3. **Add a key if the server needs one.** SAM.gov, Regulations.gov, and GSA Per Diem take a free key from the agency. The setup guide shows where to get it and which setting to use.

**Updating.** Local installs don't update themselves. To get the latest version, ask your AI to update the server, or run it with `--refresh-package` (for example `uvx --refresh-package usaspending-gov-mcp --from usaspending-gov-mcp usaspending-mcp`).

If your app says it can't find `uvx`, use its full path instead: run `which uvx` on macOS or `where uvx` on Windows.


## Start with a question

1. Pick a request from the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts), or start from one of the questions in [What you can ask](#what-you-can-ask).
2. Connect the MCPs it needs, local or hosted, from the [install table](#local-or-hosted).
3. Fill in the bracketed details, such as `[AGENCY]` or `[COMPANY]`, and send it. Ask for source links and dates.

Results reflect government-source data and retrieval time or the bundled snapshot release. Check source and as-of metadata; bundled data does not make a fresh upstream request on every lookup. Check dates, completeness, identity matches, and reported limitations. The MCPs provide evidence; they do not make a contracting or procurement-specific applicability decision.

## Testing

- **Checked against the source.** Realistic contracting questions run against each server, and the answers are compared with the government source: the numbers, the dates, the citations.
- **Worst problems first.** Every problem is ranked by how much it could mislead you, from a wrong answer you might act on down to a minor wording issue. Wrong answers are fixed first.
- **Reviewed by more than one AI.** Audits run with both Claude Code and Codex, and every finding is checked by a second reviewer before a fix ships.
- **Fixed for good.** Every fix gets a regression test so the problem can't come back, and thousands of these tests run before each release.

Each server keeps its own testing record: [SAM.gov](servers/sam-gov-mcp/testing.md) · [USAspending](servers/usaspending-gov-mcp/testing.md) · [GSA CALC+](servers/gsa-calc-mcp/testing.md) · [BLS OEWS](servers/bls-oews-mcp/testing.md) · [GSA Per Diem](servers/gsa-perdiem-mcp/testing.md) · [eCFR](servers/ecfr-mcp/testing.md) · [Federal Register](servers/federal-register-mcp/testing.md) · [Regulations.gov](servers/regulations-gov-mcp/testing.md) · [Acquisition.gov](servers/acquisition-gov-mcp/testing.md)

Release details are in the [October 10, 2026 release record](docs/releases/2026-10-10-content-audit.md).

## License and author

MIT licensed. Built by a federal contracting officer. Independently developed and not affiliated with or endorsed by any federal agency.
