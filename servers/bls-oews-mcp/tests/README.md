# Test suite map

276 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

Since 1.1.0 every tool answers from the bundled OEWS release, so the suites
written against the live API (rounds 6 and 8) run offline on every test run.
`conftest.py` blocks all network access except for the one `live_parity` test.

| File | Origin and purpose | Tests |
|---|---|---|
| `test_validation.py` | Foundational input validation: SOC codes, area codes, series construction | 58 |
| `test_audit_r6.py` | Round 6 audit (written all-live): every tool across states, metros, occupations, datatypes, industries, and the year guard | 154 |
| `test_audit_r7.py` | Round 7 fix-wave regressions: THE percentile-shift money bug (hourly labels shifted one slot, Hourly Median returned 75th percentile, 26% high) and its cross-foot canary | 19 |
| `test_audit_r8.py` | Round 8 anchors: hourly x 2080 cross-foot vs annual median, bad-SOC clarity, latest-year sanity | 3 |
| `test_snapshot.py` | 1.1.0 bundled release: manifest and database hashes, provenance, golden values, footnotes, the `source` block on every tool | 25 |
| `test_builder.py` | 1.1.0 `scripts/build_oews_db.py` on synthetic BLS files: pivot, determinism, schema-drift failures | 10 |
| `test_directory_contract.py` | Directory rules: annotations, no instructions, no key language | 3 |
| `test_http.py` | Hosted HTTP app: tool catalog, host/origin/size guards, `/health`, hosted startup check | 3 |
| `test_live_parity.py` | Bundled values vs the live BLS v1 API on a fixed 25-series sample (`BLS_LIVE_TESTS=1`, no key, one request) | 1 |

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
