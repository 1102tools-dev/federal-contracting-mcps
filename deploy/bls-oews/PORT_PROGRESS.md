# BLS OEWS port to Worker + D1: progress

Branch: `worktree-agent-ae5aa281380a9a786`
See `git log` for the latest checkpoint.

No push, no deploy, no Cloudflare changes. Parent reviews and deploys.

## Status (resumed 2026-10-08)

- [x] Analysis. Commit a366817.
- [x] `schema.sql` + `scripts/load_bls_oews.py`. Local full load 3.4 s, 1,000 INSERTs (<= 90 KB, no
      bound params), 58 MB SQLite. Re-run is a no-op that also removes versions an interrupted run
      left; `--force` loads a new version, switches, deletes the old one. Remote mode (D1 HTTP API
      `/query`, one statement per request, retries 429/5xx with Retry-After) is unit-tested with a
      fake urlopen only; no Cloudflare calls were made.
- [x] Worker + 8 tools (`src/worker.ts`, `src/tools.ts`, `src/pyjson.ts`), `npm run check` passes.
- [x] Parity harness `scripts/parity.py` + `test/parity-cases.json` (145 cases), Python side in
      hosted mode on Python 3.12 (the container's). Result: 137 identical, 8 documented, 0 unexpected.
      Fixes it drove: result key order (content[text,type], isError, structuredContent), pydantic's
      exact validation text (per-branch union errors, input_value repr/truncation, input_type,
      signature field order, docs URL), floats/big ints kept from the request JSON, pydantic float
      parsing, SDK message classification (bad id -> notification 202, client responses 202,
      invalid envelopes 400 with the SDK's code), initialize needs clientInfo.version,
      prompts/get code 0.
- [x] `test/tools.test.ts` (15 node:test cases). `npm test` passes.
- [x] `tests/test_bls_loader.py` (13 cases). Passes in 3 s.
- [ ] Workflows: `bls-oews-hosted-tests.yml`, `bls-oews-load.yml`.
- [ ] Release-pipeline notes for the parent (RELEASE_SHA, data-refresh dispatch).
- [ ] Rows-read report.
- [ ] Final report.

## Key findings (analysis)

Python hosted behavior (servers/bls-oews-mcp, mcp SDK 2.0.0, pydantic 2.13):
- `BLS_HOSTED=1` only makes startup refuse a broken bundled DB; tool behavior is identical to local.
- tools/call success: `{"content":[{"type":"text","text":T}],"structuredContent":R,"isError":false}`;
  T = `pydantic_core.to_json(R, fallback=str, indent=2)` (2-space indent, `": "`, insertion key order,
  raw UTF-8, floats always with a fraction: `1000.0`; 1e-05 prints as `0.00001`, 1.5e-07 as `1.5e-7`,
  1e16 as `1e+16`).
- Tool exceptions: `{"content":[{"type":"text","text":"Error executing tool <name>: <msg>"}],"isError":true}`,
  no structuredContent. Pydantic validation errors take the same path. Unknown tool: `Unknown tool: <name>`.
- `_forbid_extra_params_on_all_tools()` forbids extra args although inputSchema lacks
  `additionalProperties: false`. The port forbids extras too.
- pydantic coercions observed: Union[str,int] takes True as 1 and 151252.0 as 151252, rejects 151252.5;
  float fields turn 2 into 2.0 ("2.0x"), accept " 2.5 ", "1e1", "1_000", "inf", "nan", True.
- `pre_parse_json`: a string argument is JSON-parsed when it yields a list/dict/null.
- initialize: unknown/2026-07-28 protocolVersion -> "2025-11-25"; missing params -> -32602
  "Invalid request parameters". server/discover over plain POST -> -32601 (same as SAM).
  resources/read -> -32602 "Unknown resource: <uri>" data {uri}; prompts/get -> code 0 "Unknown prompt"
  (port uses -32602 with the same message).
- JS objects reorder integer-like keys ("47900"), so results use `Map` and the custom serializer
  writes both `text` and the response body.
- Python round()/format are half-even on the exact binary value; JS toFixed rounds ties up. Handled.
- verify_hosted_release.py asserts `/health.admission == {processing:16, waiting:32, total:48,
  deadline_seconds:55}` for bls-oews (kept as a fixed value), serverInfo.version == pyproject version
  (Worker reads servers/bls-oews-mcp/server.json, kept equal by validate_versions.py), no
  `instructions`, tools/list == contract, get_data_status bundled/no key, get_wage_data source kind.
- Python 3.14 in this iCloud worktree skips the editable `.pth` (UF_HIDDEN flag), so run Python with
  `PYTHONPATH=servers/bls-oews-mcp/src`.

Bundled DB (oews-2025.sqlite, 52 MB): cell 370,172 rows (key = series id minus 2-char datatype;
v01..v17 values, f01..f17 footnote codes), area 583, occupation 1,104, footnote 6. Values are plain
decimals or "-"; footnote codes are single codes 4/5/8; v16/v17 NULL at national scope.

## Design decisions

- D1 tables keyed by `version`: `cell(version, key, ...)`, `occupation`, `area` (all WITHOUT ROWID,
  PK (version, code/key)), `release(version, database_sha256, manifest, footnotes, loaded_at)`, and
  `active_release(id=1, version)`. Loader cleans unfinished versions, inserts a new version
  (INSERT OR REPLACE, so retried requests are harmless), verifies counts against the manifest,
  switches `active_release` in one statement, then deletes the old version in key ranges.
  Readers filter by `(SELECT version FROM active_release WHERE id = 1)` inside one D1 batch.
- Static constants (DATATYPE_LABELS, STATE_FIPS, COMMON_*) are duplicated in tools.ts; the parity
  harness (list_common_* and error-message cases) is meant to catch drift from constants.py.
- Infrastructure failures return `Error executing tool <name>: BLS OEWS data is temporarily
  unavailable. Try again shortly.` (isError) and log `tool_failed` without arguments.

## Resume

```
# Python env (the iCloud path needs PYTHONPATH, see above)
uv sync --frozen --project servers/bls-oews-mcp
# Local D1 copy
python3 scripts/load_bls_oews.py --local "$SCRATCH/d1.sqlite"
# Worker deps, typecheck
npm ci --prefix deploy/bls-oews --ignore-scripts && npm run check --prefix deploy/bls-oews
# TS side of a parity case file ({name, tool, arguments} or {name, method, params})
node deploy/bls-oews/scripts/parity-run.ts "$SCRATCH/d1.sqlite" cases.json
# Python side: POST the same cases to starlette TestClient(bls_oews_mcp.http.create_app()) with
# headers {"host": "localhost:8080", "accept": "application/json, text/event-stream"}, BLS_HOSTED=1,
# BLS_OEWS_DATA_DIR=<tmp>, run via:
PYTHONPATH=servers/bls-oews-mcp/src uv run --frozen --project servers/bls-oews-mcp python <script>
```

Next steps in order: parity.py + cases (40+, diff = zero or documented); test/tools.test.ts;
tests/test_bls_loader.py; the two workflows; release glue (configure_hosted_image.py RELEASE_SHA,
data-refresh dispatch); rows-read report; final report with deploy steps.
