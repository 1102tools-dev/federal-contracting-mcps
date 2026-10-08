# BLS OEWS port to Worker + D1: progress

Branch: `worktree-agent-ae5aa281380a9a786`
Last code checkpoint: PAUSE_SHA (the "pause checkpoint (WIP)" commit; `git log -1` shows the tip)

No push, no deploy, no Cloudflare changes. Parent reviews and deploys.

## Status (paused at the parent's request)

- [x] Analysis (below). Commit a366817.
- [x] `deploy/bls-oews/schema.sql` + `scripts/load_bls_oews.py`. Commit aedfa6a.
      Local mode tested: full load 3.4 s, 1,000 INSERT statements (max 90 KB each, no bound params),
      89.7 MB of SQL, resulting SQLite 58 MB; re-run is a no-op ("unchanged"); `--force` loads
      version 2, switches, deletes version 1. Remote mode (D1 HTTP API `/query`, one statement per
      request, retries on 429/5xx) is written but NOT exercised (no Cloudflare calls allowed).
- [~] Worker + tool handlers: written, typecheck passes (`npm run check`), smoke-tested.
  - `src/worker.ts`: SAM-style stateless JSON-RPC handler + fetch (publicDocs, Origin check,
    REQUEST_LIMITER, /health with status/tools/release_sha/admission, POST /mcp only, 64 KiB body).
    initialize mirrors Python exactly (checked); tools/list returns tools-contract.json as imported;
    prompts/list, resources/list, resources/templates/list return empty lists like Python;
    unknown methods -32601 "Method not found" with data=method (Python's shape).
  - `src/index.ts`: exports the unchanged `BLSOEWS` Container class + `worker` default. Logic lives
    in worker.ts because `@cloudflare/containers` cannot load under node:test.
  - `src/tools.ts`: all 8 tools ported step by step from server.py; pydantic-style argument
    validation driven by the contract inputSchema (pre_parse_json, lax coercions, extra keys
    forbidden); one D1 batch per call (release row + cells + names), plus one extra query only when
    an explicit `year` is passed (its range check needs the release).
  - `src/pyjson.ts`: Python-compatible serializer (pydantic_core.to_json indent=2), float repr,
    half-even `round`/`format`, `str.strip` whitespace set, `repr`.
  - Smoke test via `scripts/parity-run.ts` over the local D1 copy: initialize, get_wage_data,
    igce_wage_benchmark (burden ints -> "2.0x"), and a validation error all look identical to the
    Python output captured earlier. No systematic parity run yet.
  - `wrangler.jsonc`: D1 binding added top-level and in env.production (placeholder id); containers,
    durable_objects, migrations untouched; still plain JSON (configure_hosted_image.py uses json.loads).
  - `package.json`: added "type": "module" and `test` script. `tsconfig.json`: resolveJsonModule,
    allowImportingTsExtensions.
- [ ] node:test suite `deploy/bls-oews/test/*.test.ts` (adapter `test/d1.ts` exists; no tests yet).
- [ ] Parity harness `deploy/bls-oews/scripts/parity.py` (+ `test/parity-cases.json`, 40+ cases).
      TS side runner exists: `scripts/parity-run.ts`. Python side: use starlette TestClient on
      `bls_oews_mcp.http.create_app()` with BLS_HOSTED=1 (see Resume for the probe script pattern).
- [ ] Offline loader tests `tests/test_bls_loader.py` (pattern: tests/test_sam_loader.py).
- [ ] Workflows: `.github/workflows/bls-oews-hosted-tests.yml` (model: sam-gov-hosted-tests.yml) and
      `.github/workflows/bls-oews-load.yml` (env sam-data-load, secret CLOUDFLARE_D1_TOKEN,
      BLS_OEWS_D1_DATABASE_ID: REPLACE_WITH_D1_DATABASE_ID, push on data path + workflow_dispatch).
- [ ] Release-pipeline glue (decide/flag to parent):
      1. `scripts/configure_hosted_image.py` should set `vars.RELEASE_SHA` in wrangler.release.json
         for D1 configs; otherwise verify_hosted_release.py waits for release_sha and fails.
      2. data-refresh.yml commits with GITHUB_TOKEN, which does not fire `push` workflows: add a
         `gh workflow run bls-oews-load.yml --ref main` step after a bls-oews data push.
- [ ] Rows-read report (EXPLAIN QUERY PLAN; optionally miniflare local D1 meta.rows_read).
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
