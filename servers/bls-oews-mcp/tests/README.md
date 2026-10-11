# Test suite map

298 tests: 297 offline and 1 optional live parity check. Files are named by the
audit round or fix release that produced them, so each test traces back to its
fix in git history. [../testing.md](../testing.md) explains how to run them.

Every tool answers from the bundled OEWS release, so suites originally written
against the live API (rounds 6 and 8) run offline. `conftest.py` blocks all
network access except the one `live_parity` test.

| File | Origin and purpose | Tests |
|---|---|---|
| `test_validation.py` | Foundational input validation: SOC codes, area codes, series construction | 58 |
| `test_audit_r6.py` | Round 6 sweep: every tool across states, metros, occupations, datatypes, industries, and the year guard | 154 |
| `test_audit_r7.py` | Round 7 regressions: the hourly percentile-shift bug (Hourly Median returned the 75th percentile) and its cross-foot check | 19 |
| `test_audit_r8.py` | Round 8 anchors: hourly x 2080 cross-foot vs annual median, bad-SOC clarity, latest-year sanity | 3 |
| `test_snapshot.py` | 1.1.0 bundled release: manifest and database hashes, provenance, golden values, footnotes, the `source` block on every tool | 25 |
| `test_builder.py` | 1.1.0 `scripts/build_oews_db.py` on synthetic BLS files: pivot, determinism, schema-drift failures | 10 |
| `test_directory_contract.py` | Directory rules: annotations, no instructions, no key language | 3 |
| `test_http.py` | Hosted HTTP app: tool catalog, host/origin/size guards, `/health`, hosted startup check | 3 |
| `test_content_r9.py` | 1.1.1 content fixes BLS-1 to BLS-9: release month and escalation, published hourly values, 25th/75th percentiles, reliability warnings, unpublished-wage reasons, starter labels, industry guidance, comparison year/order, per-1,000 precision | 15 |
| `test_content_e2e.py` | 1.1.2 hourly-only musicians/actors and unsupported national ratios | 3 |
| `test_cli_guidance.py` | 1.1.3 installed CLI: national-ratio guidance and a valid Virginia follow-up | 1 |
| `test_content_round2.py` | 1.1.4 teacher/performer alternate measures and published top-code floor | 3 |
| `test_live_parity.py` | Bundled values vs the live BLS v1 API on a fixed 25-series sample (`BLS_LIVE_TESTS=1`, no key, one request) | 1 |

- `scenarios/` holds standalone scenario scripts (not pytest; kept for
  reproducing early rounds).
