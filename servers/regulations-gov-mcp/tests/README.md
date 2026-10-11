# Test suite map

298 tests (179 offline, 119 live). Files are named by the audit round or fix
release that produced them, so each test traces back to its fix in git history.
[../testing.md](../testing.md) explains how to run them.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_access_status.py` | Credential presence, setup guidance, tool-only output | 9 | 0 |
| `test_audit_r7.py` | Round 7: ascending deadlines, pagination, API limits, and validation | 27 | 4 |
| `test_audit_r8.py` | Round 8: one-call-per-test live anchors | 4 | 4 live_smoke |
| `test_content_fixes.py` | 2.0.3: Eastern deadlines, posted counts, organizations, subtypes, page ceiling, facets, type filter, comment text, and hints | 35 | 0 |
| `test_credential_redaction.py` | Credential and error-payload redaction | 6 | 0 |
| `test_hosted_directory.py` | Compact output, hosted publisher configuration, and tool contracts | 14 | 0 |
| `test_hosted_throughput.py` | Hosted pacing, budget, and throughput contract | 8 | 0 |
| `test_round_4.py` | Round 4 property validation and live source audit | 125 | 106 |
| `test_validation.py` | Foundational input validation and source checks | 51 | 5 |
| `test_ordinary_recovery_guidance.py` | 2.0.6: filter and date fix-it guidance; unexpected errors stay unexpected | 3 | 0 |
| `test_deadline_source_guidance.py` | 2.0.5: deadlines labeled as source metadata, with notice links for verification | 9 | 0 |
| `test_workflow_content_audit.py` | 2.0.4: workflow recovery guidance and unknown organizations | 7 | 0 |
| **Total** | | **298** | **119** |

Live tests need `REGULATIONS_LIVE_TESTS=1` and `REGULATIONS_GOV_API_KEY`.
`conftest.py` paces them and resets the shared HTTP client between tests. Run
the small one-call-per-test live set with `pytest -m live_smoke`.

- `fixtures/` holds saved API responses used by the offline content tests;
  `test_content_fixes.py` labels the few synthetic cases.
- `scenarios/` holds standalone scenario scripts from early rounds (not pytest).
