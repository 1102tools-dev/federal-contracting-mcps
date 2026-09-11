# Federal contracting MCPs

Read-only source tools for federal contracting research: opportunities, awards, company records, labor pricing, travel rates, regulations, and rulemaking.

[Explore 1102tools](https://1102tools.com) · [Find a matching prompt](https://github.com/1102tools-dev/federal-contracting-prompts) · [Download the MCP prompt guide](https://github.com/1102tools-dev/federal-contracting-prompts/blob/main/docs/1102tools-mcp-prompt-guide.pdf)

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

1. Open the selected server's README above. Follow its installation and configuration instructions for your MCP client.
2. Configure any required API keys outside chat. The server README identifies the exact environment variables and access limits.
3. Restart or reconnect the client as needed, and confirm the server's tools are visible. Where provided, `get_access_status` reports local credential readiness; it does not validate the key with the upstream provider.
4. Choose a [prompt](https://github.com/1102tools-dev/federal-contracting-prompts), connect every MCP named beneath it, and replace the bracketed details.

A prompt does not install a server. Local command configuration and remote endpoint configuration differ; use the supported setup documented for the selected server. Do not assume a server is available in a platform directory simply because its source is published here.

**USASpending package naming:** its package is `usaspending-gov-mcp` and its executable is `usaspending-mcp`. Use the exact configuration in [its README](servers/usaspending-gov-mcp); do not substitute a similarly named package.

## Use the sources together

- **Competitors and teaming:** combine USASpending award records with SAM.gov entity and exclusion evidence.
- **Pricing inputs:** compare BLS wages, CALC+ ceiling rates, and GSA travel rates while keeping their different pricing bases clear.
- **Regulations and policy:** use eCFR for codified text, Federal Register and Regulations.gov for rulemaking, and Acquisition.gov for FAR Overhaul model text and posted deviations.

Results reflect upstream data and retrieval time. Check dates, completeness, identity matches, and reported limitations. The MCPs provide evidence; they do not make a contracting or procurement-specific applicability decision.

## Testing and maintenance

Current source-specific evidence is in each server's `testing.md` or `TESTING.md`, with changes in its changelog. Packages version independently. The shared request-pacing code reduces bursts and handles provider errors; it does not create additional provider quota.

This September 2026 documentation refresh changes the public entry points and removes retired setup links. It does not change MCP runtime behavior or claim a new live test of the entire suite. Earlier release narrative is preserved in [historical documentation](docs/readme-before-mcp-reboot.md).

## License and author

MIT licensed. Built by James Jenrette. Independently developed and not affiliated with or endorsed by any federal agency.
