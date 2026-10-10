# Test suite map

576 collected Python tests: 309 offline and 267 live-gated (2026-10-10, 1.2.3 preparation). Worker tests and parity scenarios are separate counts. Historical audit files remain append-only; see [../testing.md](../testing.md).

| File | Origin and purpose | Collected | Live-gated |
|---|---|---:|---:|
| `test_access_status.py` | Hosted key handling and bundled data status | 7 | 0 |
| `test_audit_r7.py` | Round 7 rate-area resolution and OCONUS regressions | 22 | 3 |
| `test_audit_r8.py` | Round 8 live smoke anchors | 4 | 4 |
| `test_builder.py` | Snapshot builder integrity | 13 | 0 |
| `test_city_resolution.py` | City and county resolution; round 9 whole-part composite matching | 38 | 0 |
| `test_credential_redaction.py` | Credential redaction | 6 | 0 |
| `test_directory_contract.py` | Published tool and description contract | 3 | 0 |
| `test_hosted_throughput.py` | Hosted pacing and concurrency | 5 | 0 |
| `test_live_audit_r6.py` | Round 6 production API matrix | 240 | 240 |
| `test_live_parity.py` | Live bundled-data/API parity | 12 | 12 |
| `test_pacing.py` | Shared pacing | 3 | 0 |
| `test_snapshot.py` | Bundled ZIP/state/M&IE data; round 9 notes and seasonal-month corrections | 38 | 0 |
| `test_validation.py` | Input validation and API response handling | 173 | 8 |

Live tests need `MCP_LIVE_TESTS=1 + PERDIEM_API_KEY`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
