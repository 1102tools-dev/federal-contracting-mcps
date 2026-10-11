# Test suite map

588 tests: 321 offline and 267 live-gated. Files are named by the audit round or
fix release that produced them, so each test traces back to its fix in git
history. [../testing.md](../testing.md) explains how to run them.

| File | Origin and purpose | Tests | Live-gated |
|---|---|---:|---:|
| `test_access_status.py` | Hosted key handling and bundled data status | 7 | 0 |
| `test_audit_r7.py` | Round 7 rate-area resolution and OCONUS regressions | 22 | 3 |
| `test_audit_r8.py` | Round 8 live smoke anchors | 4 | 4 |
| `test_builder.py` | Snapshot builder integrity | 14 | 0 |
| `test_city_resolution.py` | City and county resolution, including whole-part composite name matching | 38 | 0 |
| `test_content_e2e_20261010.py` | October 2026 content fixes: conflicting location input and split-trip totals | 12 | 0 |
| `test_credential_redaction.py` | Credential redaction | 6 | 0 |
| `test_directory_contract.py` | Published tool and description contract | 3 | 0 |
| `test_hosted_throughput.py` | Hosted pacing and concurrency | 5 | 0 |
| `test_live_audit_r6.py` | Round 6 production API matrix | 240 | 240 |
| `test_live_parity.py` | Bundled data vs the live GSA API | 12 | 12 |
| `test_pacing.py` | Shared pacing | 3 | 0 |
| `test_sdk23_input_guidance.py` | 1.2.5 input-mistake guidance under MCP SDK 2.3 | 5 | 0 |
| `test_snapshot.py` | Bundled ZIP/state/M&IE data, notes and seasonal-month corrections | 44 | 0 |
| `test_validation.py` | Input validation and API response handling | 173 | 8 |

Live tests need `MCP_LIVE_TESTS=1` and `PERDIEM_API_KEY`, and are paced
automatically by `conftest.py` (which also resets the cached HTTP client per
test so batched live runs work). The minimal one-call-per-test anchor set runs
with `pytest -m live_smoke`.

- `fixtures/` holds captured GSA city responses used as test inputs.
- `scenarios/` holds a standalone scenario script (not pytest; kept for
  reproducing early rounds).
