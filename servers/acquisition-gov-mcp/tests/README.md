# Acquisition.gov tests

Run from the repository root. Offline tests use captured HTML, generated PDFs and mocked transports. They do not call government services.

```bash
FEDERAL_API_MIN_INTERVAL_SECONDS=0 ACQUISITION_GOV_LIVE_TESTS=0 uv run --project servers/acquisition-gov-mcp pytest -q servers/acquisition-gov-mcp/tests
```

Select a priority with `-m p0`, `-m p1`, `-m p2` or `-m p3`. The 23 original tests remain unranked and are included in the full run. P3 uses the real MCP stdio client and HTTP application locally; mock transport replaces government access.

The new live suite covers every tool and the actual cached-curl path. It is opt-in and serialized. Retain the three-second delay; do not run live tests in parallel.

```bash
ACQUISITION_GOV_LIVE_TESTS=1 FEDERAL_API_MIN_INTERVAL_SECONDS=3 ACQUISITION_GOV_EVIDENCE_PATH=/tmp/acquisition-gov-live.json uv run --project servers/acquisition-gov-mcp pytest -q -s servers/acquisition-gov-mcp/tests/test_live_hardening.py
```

The evidence option writes observations to the selected path and a separate `-curl.json` file for the second test. The older `test_live.py` is also opt-in; it is unnecessary to repeat it when the broader live suite has already covered its sources.

```bash
uv run --project servers/acquisition-gov-mcp python scripts/check_hosted_contract.py acquisition-gov
uv build servers/acquisition-gov-mcp
```

See [the test record](../testing.md) for results, resource-limit differences between platforms and the limits of sampled live coverage. Captured source text is test data, not a policy determination.
