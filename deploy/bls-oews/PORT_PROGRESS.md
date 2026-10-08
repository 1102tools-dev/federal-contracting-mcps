# BLS OEWS port to Worker + D1: progress

Branch: `worktree-agent-ae5aa281380a9a786`
Latest commit: see `git log -1` (updated at each milestone below)

No push, no deploy, no Cloudflare changes. Parent reviews and deploys.

## Status

- [x] Analysis (this file)
- [ ] schema.sql + scripts/load_bls_oews.py (local + remote)
- [ ] Worker src/index.ts + src/tools.ts
- [ ] node:test suite + package.json scripts + `npm run check`
- [ ] Parity harness + results
- [ ] CI workflow + load workflow

## Key findings (analysis)

Python hosted behavior (servers/bls-oews-mcp, mcp SDK 2.0.0, pydantic 2.13):
- `BLS_HOSTED=1` only makes startup refuse a broken bundled DB; tool behavior is identical to local.
- tools/call success: `{"content":[{"type":"text","text":T}],"structuredContent":R,"isError":false}`;
  T = `pydantic_core.to_json(R, fallback=str, indent=2)` (2-space indent, `": "`, insertion key order,
  raw UTF-8, floats always with a fraction or exponent, e.g. `1000.0`).
- Tool exceptions: `{"content":[{"type":"text","text":"Error executing tool <name>: <msg>"}],"isError":true}`, no structuredContent.
  Pydantic validation errors take the same path (message = pydantic's ValidationError text).
  Unknown tool: text `Unknown tool: <name>`, isError true.
- `_forbid_extra_params_on_all_tools()` sets extra='forbid' on every arg model, though the published
  inputSchema does not say `additionalProperties: false`. Port forbids extras too.
- `pre_parse_json`: a string argument for a non-`str` field is JSON-parsed when it parses to
  a list/dict/null (not str/int/float/bool), e.g. `metro_codes: "[\"47900\"]"`, `year: "null"`.
- JS object key order differs for integer-like keys ("47900"), so tool results use `Map` where keys
  can be numeric (compare_metros metros/metro_names, list_common_soc_codes) and a custom Python-style
  serializer writes both `text` and the response body.
- Floats in results: `numeric` for hourly/RSE/ratio datatypes and `numeric_hourly`; everything else int.
- Python `round()`/`:.2f` are half-even on the exact binary value; JS toFixed is half-up. Port detects
  exact ties.
- verify_hosted_release.py asserts `/health.admission == {processing:16, waiting:32, total:48, deadline_seconds:55}`
  for bls-oews, plus `initialize.serverInfo.version == pyproject version`, no `instructions`,
  tools/list == tools-contract.json, get_data_status status=='bundled' and api_key_required False,
  get_wage_data source.kind == 'bundled_bls_oews_files'. check_hosted_health.py reads /health status,
  release_sha, init serverInfo.version, get_wage_data source.kind/release.
- configure_hosted_image.py parses wrangler.jsonc with json.loads: keep it comment-free.
- Release workflow redeploys the Worker on every bls-oews release, so the Worker reads its
  version from servers/bls-oews-mcp/server.json (validate_versions.py keeps it equal to pyproject).

Bundled DB (oews-2025.sqlite, 52 MB): cell 370,172 rows (key = series id minus 2-char datatype;
v01..v17 values, f01..f17 footnote codes), area 583, occupation 1,104, footnote 6. Values are plain
decimals or "-"; footnote codes are single codes 4/5/8.

## Design decisions

- D1 tables keyed by `version` (release generation): `cell(version, key, ...)`, `occupation`, `area`,
  plus `release(version, active, manifest JSON, footnotes JSON, ...)`. Loader inserts a new version,
  verifies counts, flips `active` in one UPDATE, then deletes old versions. Readers always filter by
  `(SELECT version FROM release WHERE active = 1)` inside one D1 batch, so they never see a half load.
- Loader remote mode runs SQL through wrangler (same path as load_sam_opportunities.py) with a
  generated temporary config so the database id comes from `--database-id`/`BLS_OEWS_D1_DATABASE_ID`.

## Resume

```
cd servers/bls-oews-mcp && uv sync --frozen
```
