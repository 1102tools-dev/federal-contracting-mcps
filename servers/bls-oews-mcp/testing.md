# BLS OEWS MCP: Testing

298 regression tests: 297 run offline on every release, and 1 optional parity check compares the bundled data with the live BLS API when you turn it on.

## What is tested

All 8 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly.

- **Right wages, not just valid answers.** Tests assert exact values from the bundled May 2025 release for national, state, metro and industry estimates. A cross-foot check (each hourly percentile x 2080 must equal its annual counterpart) guards against the percentile-label shift that once returned the 75th percentile as the hourly median.
- **Bundled data integrity.** Manifest and database hashes, source provenance, golden values, BLS footnotes, and the `source` block on every tool answer. The database builder is tested on synthetic BLS files for repeatable output and for failing loudly on schema drift.
- **Missing and limited wages.** Annual-only occupations (such as postsecondary teachers) and hourly-only occupations (such as musicians and performers) keep the published measure, explain the gap with the BLS footnote, and point to the alternate measure. Top-coded wages keep BLS's published lower bound. Unreleased cells keep employment and footnotes.
- **IGCE benchmarks.** Burden multiplier arithmetic, the release month and escalation note, published hourly values where BLS has them, and warnings for high relative standard errors.
- **Input checks.** SOC codes, area codes, state FIPS padding, unsupported years, and national requests for ratios that BLS publishes only for states and metros. Bad input gets a specific message saying how to fix it.
- **Hosted service.** Tool catalog, host/origin/size guards, `/health`, and the hosted startup check.

Realistic contracting wage questions (IT, engineering, trades, social services, education, transportation and more) were also checked against BLS source values before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/bls-oews-mcp`:

```sh
uv run pytest                                              # offline suite (network blocked)
BLS_LIVE_TESTS=1 uv run pytest tests/test_live_parity.py   # live BLS API parity check (no key, one request)
```

`conftest.py` blocks all network access except the one parity check, and unpacks the bundled database into a temporary `BLS_OEWS_DATA_DIR` for the test session. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **One release is bundled.** Answers come from the May 2025 estimates. Other years return an error pointing to the historical tables at [bls.gov/oes/tables.htm](https://www.bls.gov/oes/tables.htm).
- **The next BLS release.** A new release (expected spring 2027) is detected by the weekly source watch and ships as a reviewed package release; the rebuild, golden values and parity check are repeated then.
- **Parity beyond the sample.** The live comparison covers a fixed 25-series sample; the rest of the release relies on the builder's one-to-one copy of BLS's published values.
- **Some wages are not published.** BLS publishes only annual wages for some occupations and only hourly wages for others. The server shows the published measure and the BLS footnote; it does not invent the missing one.
- **Ratios by scope.** Employment per 1,000 jobs and location quotient are available for states and metros, not nationally.
- **Base wages, not prices.** OEWS wages exclude fringe, overhead, G&A and profit. Burden multipliers are the caller's assumptions, and May 2025 wages need escalation to the period of performance.
- **BLS footnote file.** Direct download of BLS's flat footnote file returned HTTP 403 during October 2026 checks; footnotes were confirmed through the BLS API instead.

## History

Earlier audit rounds, fixes and release checks are in this file's git history and in [changelog.md](changelog.md).
