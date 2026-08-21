# federal-contracting-mcps

Eight free and open source MCP servers for federal contracting data and policy tracking. SAM.gov, USASpending, GSA CALC+, BLS OEWS, per diem, eCFR, Federal Register, and Regulations.gov, exposed as 124 deterministic tool calls.

Your assistant queries the real APIs instead of recalling what it thinks the FAR says. Same input, same output, every time.

Website: [1102tools.com](https://1102tools.com)

## The fastest install: hand this PDF to your AI

[![The 1102tools universal setup guide: one PDF for two agent plugins, eight MCP servers, and six standalone skills. Repository-marketplace instructions cover Codex, Claude Code, and Copilot CLI; standalone setup covers major clients with tested surfaces and open limits stated. August 2026.](docs/setup-guide-promo.png?v=2)](https://1102tools.com/downloads/1102tools-universal-setup.pdf)

**[Download the universal setup guide (PDF)](https://1102tools.com/downloads/1102tools-universal-setup.pdf)**, then drop it into Claude, ChatGPT (Codex), Gemini (Antigravity), Copilot, DeepSeek Harness, Grok, Cursor, opencode, or LibreChat and say what you want installed. The AI reads the guide and walks you through agent marketplace installation, free API keys, exact standalone configuration, restart, verification, updates, and removal. If 39 pages is more than your chat will accept, paste in just the section for your platform; every option is written to stand alone. The guide distinguishes tested surfaces from pending ones, and Part 9 is troubleshooting built from errors I actually encountered.

[![The 1102tools prompt guide: installed, now know what to ask. Copy-paste prompts for competitor intelligence, bid decisions, recompete timing, and pricing. Covers when SAM.gov is the answer, when USASpending beats it, and the combination plays that use both, including the DoD reporting delay. Every pattern was run against the live servers before publishing. August 2026.](docs/prompt-guide-promo.png?v=3)](https://1102tools.com/downloads/1102tools-prompt-guide.pdf)

**[Download the prompt guide (PDF)](https://1102tools.com/downloads/1102tools-prompt-guide.pdf)**: what to ask once the servers are in. Competitor intelligence, bid decisions, recompete timing, and pricing, centered on when SAM.gov is the answer and when USASpending beats it. Every prompt pattern was run against the live servers before publishing. The library also lives as a repo now, and that is its canonical home: [federal-contracting-prompts](https://github.com/1102tools-dev/federal-contracting-prompts), all 60 prompts as browsable markdown with a copy button on every one; the PDF is rebuilt from it.

![Architecture diagram showing how a question travels: your AI client (any of the eleven supported clients), to an MCP server launched by uvx on your own machine, to the official federal API using your own free key, back to a deterministic result. Coverage is grouped in three domains. Awards and entities: SAM.gov (19 tools, key) and USASpending (55 tools). Labor and pricing: BLS OEWS (7 tools, key), GSA CALC+ (8 tools), GSA Per Diem (6 tools, key). Regulation and rulemaking: eCFR (13 tools), Federal Register (8 tools), Regulations.gov (8 tools, key).](docs/architecture.png)

---

## Safety release v1.0.9 (August 2026)

All eight packages now enforce a provisional, cross-process anti-burst gate
before every upstream request. SAM.gov, BLS OEWS, USASpending, GSA CALC+,
eCFR, and Federal Register default to one request every 3 seconds. GSA Per
Diem and Regulations.gov default to 4 seconds and share one `api.data.gov`
bucket when they use the same key.

This is a 1102tools safety safeguard, not a statement that every provider
requires that exact interval. It protects independently launched MCP and agent
processes on the same computer, honors `Retry-After` without automatically
retrying, and never writes a raw credential to pacing state. It cannot
coordinate the same key running on another computer or create additional
daily quota.

Set `FEDERAL_API_MIN_INTERVAL_SECONDS` to a different finite, non-negative
number when you have a documented reason. Setting it to `0` deliberately
disables the local gate. `FEDERAL_API_PACING_DIR` overrides the per-user state
directory for managed or temporary environments.

The release also makes PyPI publication depend on the complete offline test
matrix and wheel inspection. Current package versions are listed in each
server's changelog and the universal setup guide.

## 1.0.0 stable baseline (August 2026)

**All eight servers first reached 1.0.0 together.** That was the first stable
suite release and the largest update since launch. Packages now version
independently so a correction to one server does not force no-op releases of
the other seven.

### Rebuilt on v2 of the MCP Python SDK

The MCP Python SDK, the library every one of these servers is built on, released version 2.0 in July. It renamed its high-level server class from `FastMCP` to `MCPServer` and removed the old module entirely. All eight servers have been migrated and re-verified against it.

Nothing changed for you as a user. Same 124 tools, same parameters, same responses. The dependency is now bounded at `mcp>=2.0.0,<3`, so the next major SDK release produces a clean error at install time instead of a crash at startup.

### Two problems this release fixes, and both were affecting people

**BLS wage lookups were returning empty results.** When BLS published its May 2025 OEWS estimates this spring, it withdrew the 2024 series. `bls-oews-mcp` still defaulted to 2024, so any wage query that did not pass an explicit year came back with no values, which is indistinguishable from a privacy-suppressed cell. There was no error and no warning. The default is now 2025, and `detect_latest_year()` will confirm the current year at any time.

If you pulled wage figures for an IGCE between roughly April and August 2026, re-check them.

**Fresh installs were failing outright.** Every 0.x package declared `mcp>=1.0.0` with no upper limit. When SDK 2.0.0 published on July 28, new installs resolved to it and died immediately with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. Existing installs were unaffected, but anyone installing for the first time in that window hit a wall. Bounding the requirement fixes it permanently.

Apologies to anyone who lost time to either one.

### Claude Desktop `.mcpb` bundles are discontinued

The double-click bundles are gone. They could not be signed in a way Claude Desktop recognizes, so every install showed an untrusted-developer prompt with no way to clear it, and the bundle re-resolved its dependencies on every launch rather than pinning them, which made it the install path most exposed to the failure above. The config block in [Install](#install) does the same job with fewer moving parts. Existing bundle installs keep working until removed, but will not receive updates.

### Verified before shipping

5,078 collected regression tests across the eight servers: 3,464 offline tests
passed and 1,614 live tests remained correctly gated during the v1.0.9 safety
validation. Per-server detail is in each `testing.md` and `changelog.md`.

---

## The eight MCPs

All source lives under `servers/<name>/`. Each server is self-contained: code, tests, per-server README with a copy-paste config block.

**Procurement data**
- [sam-gov-mcp](servers/sam-gov-mcp): SAM.gov entity registration, exclusions, opportunities, contract awards (FPDS replacement), federal hierarchy, FFATA subawards
- [usaspending-gov-mcp](servers/usaspending-gov-mcp): federal contract, award, FFATA subaward, recipient, agency, and Treasury federal account data
- [gsa-calc-mcp](servers/gsa-calc-mcp): GSA CALC+ awarded NTE hourly rates from MAS contracts (230K+ records)
- [bls-oews-mcp](servers/bls-oews-mcp): BLS OEWS market wage data across ~830 occupations and 530+ metros
- [gsa-perdiem-mcp](servers/gsa-perdiem-mcp): federal travel lodging and M&IE rates for all CONUS

**Regulatory and policy tracking**
- [ecfr-mcp](servers/ecfr-mcp): current CFR text updated daily, FAR / DFARS / agency supplement lookups
- [federal-register-mcp](servers/federal-register-mcp): proposed rules, final rules, notices, executive orders, FAR cases
- [regulations-gov-mcp](servers/regulations-gov-mcp): federal rulemaking dockets, public comments, comment period tracking

Combined: 124 deterministic tool calls, 5,078 regression tests, 8 audit programs, roughly 350 bugs fixed during hardening.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/). MCP is an open standard: these servers run in any MCP client, not just Claude. Every install path was executed and verified in August 2026 on eleven platforms: Claude Desktop, Claude Code, Codex Desktop and CLI, Gemini via Antigravity, GitHub Copilot CLI, DeepSeek Harness, Grok Build, Cursor, opencode, and LibreChat.

**1. Register the free API keys you need.** [BLS](https://data.bls.gov/registrationEngine/), [api.data.gov](https://api.data.gov/signup/) (covers Per Diem and Regulations.gov), [SAM.gov](https://sam.gov/). USASpending, GSA CALC+, eCFR, and Federal Register need no key.

**2. Add the servers you want to your client config.** Most clients take the same `mcpServers` JSON block and differ only in where the config file lives (for Claude Desktop it is `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows). The [universal setup guide](https://1102tools.com/downloads/1102tools-universal-setup.pdf) has the exact file path and format for all eleven platforms, including the Codex TOML form.

```json
{
  "mcpServers": {
    "ecfr": {
      "command": "uvx",
      "args": ["--refresh-package", "ecfr-mcp", "--from", "ecfr-mcp", "ecfr-mcp"]
    },
    "sam-gov": {
      "command": "uvx",
      "args": ["--refresh-package", "sam-gov-mcp", "--from", "sam-gov-mcp", "sam-gov-mcp"],
      "env": { "SAM_API_KEY": "your-key-here" }
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes and new tools arrive automatically. Without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup; if your platform enforces a short MCP startup timeout, raise it (the setup guide covers this per platform).

**3. Restart the client.** Each server's README has its own block with the correct package name and environment variable.

Docker images and a [Smithery](https://smithery.ai) config ship with each server for hosted or containerized setups.

If you are pinned to `mcp` 1.x and cannot move, stay on the 0.x line of each package.

## Repo layout

```
federal-contracting-mcps/
├── servers/
│   ├── bls-oews-mcp/
│   ├── ecfr-mcp/
│   ├── federal-register-mcp/
│   ├── gsa-calc-mcp/
│   ├── gsa-perdiem-mcp/
│   ├── regulations-gov-mcp/
│   ├── sam-gov-mcp/
│   └── usaspending-gov-mcp/
├── license
└── readme.md
```

Each server directory ships its own `pyproject.toml`, source, regression tests, Dockerfile, and testing record.

## Companion repo

[federal-contracting-skills](https://github.com/1102tools-dev/federal-contracting-skills): Claude Skills that orchestrate these MCPs into complete acquisition deliverables: SOW/PWS Builder, three IGCE Builders (FFP, LH/T&M, Cost-Reimbursement), OT Project Description Builder, OT Cost Analysis.

MCPs handle data. Skills handle deliverables.

## Why MCPs (and not skills for the API calls)

- **Deterministic.** MCP servers execute tested Python. Claude does not generate API-call code on the fly. Same input, same output.
- **Low context cost.** Tool schemas are ~100 tokens each. The deprecated API-data skills cost 500-1000 lines of context per run.
- **Production-hardened.** Each MCP went through 3-6 audit rounds with live testing against its production API.
- **Cross-client.** MCP is an open standard. The same servers were executed and verified on eleven platforms in August 2026, from Claude Desktop and Claude Code to Codex, Antigravity, Copilot, Cursor, opencode, and LibreChat.

## Website

[1102tools.com](https://1102tools.com)

## License

MIT

## Author

Built by [James Jenrette](https://www.linkedin.com/in/jamesjenrette/), lead systems analyst and contracting officer. Independently developed and not endorsed by any federal agency.
