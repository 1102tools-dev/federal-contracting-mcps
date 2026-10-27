# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.1.6

Shares the clearer error-message helper used by the other 1102tools servers. Limits, tools and answers are unchanged.

## 1.1.5

The PyPI page now links to this server's 1102tools page, and the MCP registry entry lists the hosted endpoint. Tools and answers are unchanged.

## 1.1.4

When BLS publishes no number for a wage measure, answers quote the actual BLS footnote and keep published top-coded wage floors. Teacher hourly and performer annual requests point to the wage measure BLS does publish instead of implying the occupation is missing.

## 1.1.3

Input mistakes, such as asking for national employment ratios, again return a specific message saying how to fix the request in installed clients using MCP SDK 2.3, instead of a generic error. Wage values and tools are unchanged.

## 1.1.2

Hourly-only occupations such as actors and musicians keep their published hourly wages and burdened hourly benchmarks, flagged `hourly_only`, with no made-up annual salary. National requests for employment per 1,000 jobs or location quotient now say to ask by state or metro instead of implying the occupation has no data.

## 1.1.1

Content fixes (BLS-1 to BLS-9) with the same May 2025 data. `igce_wage_benchmark` now states the wage month with an escalation note, uses BLS's published hourly wages, adds 25th and 75th percentiles, flags estimates with high relative standard errors, and quotes BLS footnotes for top-coded or unreleased cells. Starter metro and SOC lists use BLS names and add Huntsville, Virginia Beach-Norfolk, San Antonio, Colorado Springs, Dayton and SOCs 15-1299, 15-1243, 17-2141, 13-1081 and 13-1161; comparisons return `data_year`; employment per 1,000 jobs keeps three decimals. A weekly check now detects new BLS releases.

## 1.1.0

Every tool answers from the bundled May 2025 OEWS release, built from BLS's published flat files, so there is no API key, no network call and no daily limit, locally or hosted. `get_access_status` is replaced by `get_data_status`, and every result cites the BLS release, publication and retrieval dates, and source file.

## 1.0.10

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.9

HTTP debug logging no longer records request URLs that carry credentials. Tools and results are unchanged.

## 1.0.8

Adds `get_access_status`, which says whether a v2 key is configured or the server is using the keyless v1 fallback and its published 25-request-per-day limit. Rate, authentication and network failures stay visible to the AI as clear tool errors.

## 1.0.7

Published under the MCP Registry name `com.1102tools/bls-oews-mcp`. No tool changes.

## 1.0.6

The BLS registration key is redacted from upstream responses, messages and tool errors, so it never appears in chat transcripts.

## 1.0.5

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.4

Safety release: every BLS request waits at least 3 seconds after the last one, including keyless traffic, and `Retry-After` is honored without automatic retries.

## 1.0.3

Added optional pacing for keyed BLS traffic, superseded by 1.0.4.

## 1.0.2

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.1

Fixes 13 problems, including a money bug: hourly percentile labels were shifted one slot, so the Hourly Median returned the 75th percentile (26% high for Software Developers). Also stops inventing hourly rates for annual-only occupations, labels employment per 1,000 jobs and location quotient correctly, and validates state and metro codes.

## 1.0.0

Requires MCP Python SDK 2 (`mcp>=2.0.0,<3`). Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip`, or Docker. Fixes empty wage results after BLS withdrew the 2024 series: the default year is now 2025, so wage figures pulled from 0.2.x after April 2026 should be re-checked.

## 0.2.6

Wider live testing across 30 SOC codes, 15 metros and all datatypes found no new bugs. No behavior changes.

## 0.2.2

Dashed SOC codes such as `15-1252` now work. Fake SOC codes, areas and industries, and unavailable years, are flagged as no data instead of looking like privacy-suppressed cells. Single-digit state FIPS codes are padded automatically.

## 0.2.1

Misspelled parameter names now return an error instead of being silently ignored.

## 0.2.0

Hardening release: fixes crashes on unusual BLS response shapes and wrong-data bugs from loose code validation, and adds input checks across every tool.

## 0.1.0

Initial release with 7 tools covering the BLS OEWS API.
