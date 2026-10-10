# Test suite map

295 collected tests: 176 offline and 119 live-gated (Python 3.12, 2026-10-10).
The offline release gate passed all 176; the 119 live tests were skipped.
Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_access_status.py` | Credential presence, setup guidance, tool-only output | 9 | 0 |
| `test_audit_r7.py` | Round 7: ascending deadlines, pagination, API limits, and validation | 27 | 4 |
| `test_audit_r8.py` | Round 8: one-call source contract anchors | 4 | 4 live_smoke |
| `test_content_fixes.py` | 2.0.3 R1–R11: Eastern deadlines, posted counts, organizations, subtypes, page ceiling, facets, type filter, comment text, and hints | 35 | 0 |
| `test_credential_redaction.py` | Credential and error-payload redaction | 6 | 0 |
| `test_hosted_directory.py` | Compact output, hosted publisher configuration, and tool contracts | 14 | 0 |
| `test_hosted_throughput.py` | Hosted pacing, budget, and throughput contract | 8 | 0 |
| `test_round_4.py` | Round 4 property validation and live source audit | 125 | 106 |
| `test_validation.py` | Foundational input validation and source checks | 51 | 5 |
| `test_deadline_source_guidance.py` | 2.0.5 source-attributed deadline verification and linked notice recovery | 9 | 0 |
| `test_workflow_content_audit.py` | 2.0.4 workflow recovery and unavailable organizations | 7 | 0 |
| **Total** | | **295** | **119** |

Live tests need `REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).

For this 2026-10-10 release verification, source checks use DEMO_KEY only.
DEMO_KEY returned HTTP 429, so live source checks are explicitly skipped;
do not substitute the hosted publisher key. The content tests use saved
source fixtures, with synthetic Pay Equity withdrawal/page-40 cases labeled
in `test_content_fixes.py`. Saved-source coverage is distinct from a live pass.

The 2.0.4 content audit also exercised all nine hosted tools separately (33 calls).
That hosted coverage does not replace the 119 skipped direct-source tests.

Round 3 adds `test_deadline_source_guidance.py`: nine captured-data regressions for source-attributed dates and linked controlling-deadline verification across four tools. Current candidate: 176 passed, 119 optional live skipped, 295 collected.
