# eCFR MCP: Testing

464 regression tests: 346 run offline on every release, and 118 call the live eCFR API when you turn them on.

## What is tested

All 13 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly. That matters: an early `search_cfr` bug silently dropped every filter and only showed up through the pipeline.

- **Regulation text comes out whole.** Ten real eCFR responses are saved byte for byte (FAR 2.101, 52.212-3, 52.219-9, Subpart 15.3, 2 CFR 200 Appendix VIII, 13 CFR 121.201 and 125.6, HSAR 3052.225-71 and others). Every piece of text must come out exactly once, in order, under the right section, including tables, numbered examples, notes, footnote marks and pending-amendment notices. Long answers must reassemble exactly from their pages.
- **Definitions.** All 253 FAR 2.101 definitions are found by name, including plurals, acronyms, possessives and numbered subtypes (individual surety, corporate surety, cosurety). Terms defined elsewhere in the FAR or DFARS are found too.
- **Current text only.** Search hits that eCFR still lists but that have been superseded or removed are dropped and explained, so repealed text is not served as current.
- **History and comparisons.** Version history is complete and oldest-first, comparisons report sections added or removed, and available pre-2017 text (for example a December 2016 snapshot) can be compared.
- **Input checks and recovery.** Copied citations (`§ 15.305`, `48 C.F.R.`, `DFARS 252.204-7012`, `15.305(a)(2)`), dates, title and chapter conflicts, and agency names. Bad input or a missing snapshot gets a specific message saying how to fix the request.
- **Numbers stay right.** Footnote marks are not fused into numbers (`$34.0 [fn 9]`, not `$34.09`), and scientific notation in tables is kept (`3 × 10^−8 mg/l`).
- **Hosted service.** HTTP transport, response and XML caching, and shared request pacing across processes.

Realistic contracting questions (FAR and DFARS clauses, SBA subcontracting limits, CMMC, labor requirements, agency supplements, version history) were also checked against eCFR's own data before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/ecfr-mcp`:

```sh
uv run pytest                                    # offline suite
ECFR_LIVE_TESTS=1 uv run pytest                  # add live tests (no API key needed)
ECFR_LIVE_TESTS=1 uv run pytest -m live_smoke    # small one-call-per-test live set
```

`MCP_LIVE_TESTS=1` works the same as `ECFR_LIVE_TESTS=1`; both spellings are accepted. Live tests are paced automatically. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **Current text lags slightly.** eCFR updates daily, typically 1-2 business days after Federal Register publication. "Current" means eCFR's latest snapshot for that title, which can be a few days older than today.
- **Historical availability varies.** Version history starts in 2017, but some sections have older dated text (for example December 2016). Availability depends on title, section and date; there is no single date floor, and an unavailable snapshot returns recovery guidance.
- **Definition fallback is bounded.** When FAR 2.101 does not define a term, `find_far_definition` reads only the first three candidate sections and marks the rest as unread.
- **Images stay links.** Formulas, forms and other graphics appear as `[Image: <link>]` with a warning; they are not turned into text.
- **Large answers are paged.** Each page stays under 64,000 characters as sent. Comparisons too long to send whole keep the changes and leave out the full texts, and say how to read the dated text.
- **Search limits.** eCFR search stops at 10,000 results. Search counts reflect version hits; `current_check` explains which hits were dropped as superseded or removed.
- **Rate limits.** eCFR does not publish numeric limits. The server paces its own requests (a shared budget of 500 per rolling five minutes, at least 0.6 seconds between starts, two in flight, and a three-second gap for uncached XML) and honors `Retry-After` without automatic retries.
- **Reserved titles.** The server's reserved-title check can lag if eCFR reactivates a title.
- **Not a legal edition.** eCFR is not the official annual CFR. Pending amendment links and editorial notes do not by themselves establish legal effect, and codified text does not establish whether a rule or agency deviation applies to a particular procurement.

## History

Earlier audit rounds, bug-hunt findings and fixes are in this file's git history and in [changelog.md](changelog.md). The earlier note that this file once documented only `ECFR_LIVE_TESTS` (referenced in `tests/test_validation.py`) is also in git history.
