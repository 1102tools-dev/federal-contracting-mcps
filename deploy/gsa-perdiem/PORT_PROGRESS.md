# GSA Per Diem Worker + D1 port: progress

Branch: `worktree-agent-a22db7e792f1d6e15`
Latest commit: see `git log -1` (pause checkpoint, 2026-10-08)
Base: `fe60f58` (main at start)

Port of the hosted GSA Per Diem MCP from Worker -> Durable Object -> Python
container to Worker + D1 (SAM.gov pattern). No push, no deploy, no Cloudflare
changes from this branch.

## Status (paused)

- [x] Study SAM.gov Worker, loader, workflows; Python server; hosted checks
- [x] `deploy/gsa-perdiem/schema.sql` (done, used by loader)
- [x] `scripts/load_gsa_perdiem.py` (done; `--local` tested twice: first load
      writes 8 parts / 326,743 data rows in <1 s, second run is a no-op
      `already_current`). Remote mode (D1 HTTP API) written, NOT exercised.
- [x] Worker source compiles (`tsc --noEmit` clean, `erasableSyntaxOnly` so
      node --test can strip types). Not yet run against data:
  - `src/py.ts` (Python compat: PyFloat, `dumps` = pydantic_core indent-2
    text, `plain`, float-preserving `loads`, `repr`, Python whitespace,
    `quote`/`quotePlus`, `title`, code-point `pyLen`/`pySlice`)
  - `src/data.ts` (Database interface incl. `batch`, `_geo.py` port
    `norm/countyKey/placeKey`, `Year` = snapshot.Year port, `Places` lookup,
    `Snapshot` per-call loader with isolate cache keyed by part id,
    `DataUnavailable`)
  - `src/upstream.ts` (`Upstream.get(path)`: Cache API 24 h, hosted key check,
    D1 hourly budget 950 in minute buckets, D1 start-slot pacing 0.6 s with
    429 cooldown, 15 s timeout, Python error texts, redaction; `ToolError`,
    `DeadlineExceeded` -> HTTP 504)
- [x] `src/args.ts` (pydantic arg validation incl. exact ValidationError text,
      pre_parse_json), `src/tools.ts` (all 7 tools + `callTool`), `src/mcp.ts`
      (JSON-RPC + HTTP edge, 55 s deadline -> 504), `src/index.ts` (Container
      class kept + default fetch -> `serve`). Split so node tests never import
      `@cloudflare/containers` (it needs `cloudflare:workers`).
- [x] `wrangler.jsonc` D1 binding (top-level + production), tsconfig,
      package.json (`type: module`, `test`), `.gitignore`
- [ ] tests (`test/*.test.ts`, node:test, node:sqlite D1 adapter with `batch`;
      build the DB by running the loader `--local` into a temp file)
- [ ] `tests/test_gsa_perdiem_loader.py` (idempotence, resume after crash,
      release not switched on bad counts, GC, remote request shape via fake urlopen)
- [x] parity harness (`parity/build_corpus.py` -> `corpus.json`, `python_side.py`,
      `run.ts`): 1,329 calls in 9 scenarios (incl. a sweep of ZIPs, states,
      M&IE, Census places by county), 56 mocked GSA API calls, 1329/1329 identical (text byte for byte, isError, structuredContent,
      upstream request log). Fixed on the way: tools/list order (Python
      registration order, contract content), infinite floats surviving the
      response cache, budget retry rounding (ceil), `-32601` carries `data`.
- [ ] workflows: `gsa-perdiem-hosted-tests.yml`, `gsa-perdiem-load.yml`, and a
      dispatch hook in `data-refresh.yml` (bot pushes with GITHUB_TOKEN do not
      trigger `on: push`)
- [ ] `scripts/configure_hosted_image.py`: add `vars.RELEASE_SHA` (optional
      `--release-sha`, default = image sha) so the Worker's /health reports it
- [ ] `src/public-docs.ts` privacy text: cache is now Cloudflare edge cache
      (24 h, per data center), budget/pacing state in D1 (no query content);
      remove "Python application logging" / "stops after 2 idle minutes"
- [ ] final report

## Key findings

- Live: `/health` = `{"status":"ok","tools":7,"release_sha":"0691651cf5513408c6c8d2abf7c6f1b75540328d","admission":{"processing":16,"waiting":32,"total":48,"deadline_seconds":55}}`.
  `initialize` result = `{"capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"protocolVersion":"2025-11-25","serverInfo":{"name":"gsa-perdiem","version":"1.2.0"}}`.
- SDK negotiation: requested version kept if in handshake set
  `2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25`, else `2025-11-25`.
  Python SDK 2.0 also serves the modern `2026-07-28` era (`server/discover`,
  `subscriptions/listen`); following SAM, the Worker answers those -32601 and
  clients fall back to `initialize` (SDK probe treats any MCPError as fallback).
  Note this in the final report.
- `scripts/verify_hosted_release.py` asserts `/health.admission` equals the
  container values above for gsa-perdiem and `init.instructions` absent, and
  waits for `/health.release_sha == --sha`. Worker /health must keep
  `status, tools, release_sha, admission`.
- `scripts/check_hosted_health.py` needs `get_data_status.live_lookup_access
  == "hosted_publisher_key"`, `lookup_zip_perdiem {"zip_code":"22201"}` without
  `error`, and a rotating `lookup_city_perdiem` with `status: resolved` and
  `source.kind == gsa_per_diem_api`.
- The task text says the SAM loader uses "the D1 HTTP API"; it actually runs
  `wrangler d1 execute`. This loader calls the D1 HTTP API directly
  (`POST /accounts/{acct}/d1/database/{id}/query`, multi-statement `sql`),
  token `CLOUDFLARE_D1_TOKEN`, id from `--database-id` or
  `GSA_PERDIEM_D1_DATABASE_ID`.
- Python env quirk: the iCloud folder marks `.venv` hidden and Python 3.12.13
  skips hidden `.pth` files, so the editable install is invisible. Run Python
  with `PYTHONPATH=src` (venv built with `uv sync --frozen --python 3.12`,
  matching the Docker image).

### SDK result serialization (mcp 2.0.0, func_metadata.py)

- Success: `content=[TextContent(text=pydantic_core.to_json(result, fallback=str, indent=2).decode())]`,
  `structured_content = RootModel(dict).model_dump(mode="json")`, isError false.
- Every exception inside a tool (ValueError, ToolError, pydantic
  ValidationError) becomes `isError: true`, text `Error executing tool <name>: <msg>`,
  no structuredContent. Unknown tool: text `Unknown tool: <name>`.
- pydantic_core text: 2-space indent, `": "`, `[]`/`{}` for empty, non-ASCII
  raw, control chars `\uXXXX` lowercase, DEL and U+2028 raw (same as
  JSON.stringify); floats keep `.0` (`51.0`), `1e16 -> 1e+16`, `1e-5 -> 0.00001`;
  lone surrogates raise. Python floats in results: `mie_first_last_day`,
  estimate `first_last_day_mie`/`mie_total`/`grand_total`, all M&IE tier
  values (bundled JSON stores `16.0`; API path uses `_safe_number`).
- TODO when the HTTP harness runs: check whether `null` values (e.g.
  `match_note: null`) survive in wire `structuredContent` (exclude_none?).

### Argument validation (pydantic lax mode + `pre_parse_json`), verified offline

- Fields in signature order, then extras in input order; extra keys ->
  `extra_forbidden`. Messages: `N validation error(s) for <tool>Arguments\n<loc>\n  <msg> [type=..., input_value=<repr, >50 chars -> repr[:25]+'...'+repr[-24:]>, input_type=...]\n    For further information visit https://errors.pydantic.dev/2.13/v/<type>`.
- int: bool -> 0/1; integral float ok, 3.5 -> `int_from_float`; strings
  stripped, `+2026`, `02026`, `2_026`, `2026.0` ok; `2026.5`, `2026.`, `.5`,
  `1e3`, `''`, Unicode digits -> `int_parsing`; list/dict/None -> `int_type`.
- str: only strings (`string_type` otherwise). list[dict[str,str]]:
  `list_type`, `dict_type` at `locations.i`, `string_type` at `locations.i.key`.
- pre_parse_json: for params whose annotation is not exactly `str`
  (fiscal_year, county, travel_month, num_nights, locations), a string value
  that JSON-parses to null/list/dict replaces it (`county: "null"` -> None);
  str/number/bool results are ignored.
- Tool-level ValueErrors keep exact Python text (see server.py); `{value!r}`
  uses Python repr (implemented in py.ts `repr`).

## D1 design (implemented in schema.sql + loader)

- `release` (1 row): release hash, manifest JSON, `parts` {"fy2021".., "places"},
  `previous_parts`, loaded_at. Flipped by one UPSERT after all parts verified.
- `parts`: bookkeeping (expected_rows, complete).
- `years` (7 rows, 54-58 KB JSON each: year file minus zips, plus `source`).
- `zips` (283,064 rows, WITHOUT ROWID PK (part, zip)).
- `places` (43,665 rows, WITHOUT ROWID PK (part, key)).
- `upstream_calls` (minute buckets), `upstream_state` (next_start, cooldown_until).
- Local SQLite file: 14.5 MB. Part id = sha256(layout + file bytes)[:16].
- Expected rows read: year blob 2 (release + years); ZIP 2 more; places 1 + hits;
  get_data_status 1. To measure for real, run the handlers on Miniflare D1.

## Next: `src/tools.ts` plan (port of server.py, hosted mode)

- Imports `../tools-contract.json` (`with {type: "json"}`) as TOOLS, unchanged.
- `ValueError` class; dispatcher wraps ValueError/ToolError as
  `Error executing tool X: msg`; DataUnavailable/other -> isError with
  "temporarily unavailable"; DeadlineExceeded propagates to index.ts -> 504
  `{"error":"Request deadline exceeded while waiting or processing; retry later."}`.
- Signatures for arg validation:
  city/state str; fiscal_year int?; county str?; zip_code str; num_nights int;
  travel_month str?; locations list[dict[str,str]]. Order per Python signature.
- Port helpers: `_safe_dict/_as_list/_safe_int/_safe_number` (Python int()/float()
  string rules; inf -> "cannot convert float infinity to integer"),
  `_validate_*` (exact messages, `\p{Nd}` for ZIP digits, code-point lengths,
  Python whitespace), `_parse_rate_entry`, `_normalize_for_match`,
  `_normalize_city_for_url` (py `quote`), `_from_area_record`,
  `_parsed_entries`, `_rate_signature`, `_candidate_summary`, `_api_source`,
  `_area_id_for`, `_is_full_state_list`, `_census_suggestion` (py `title`),
  `_resolve_city`, `_resolve_city_by_county`, `_lookup_city`,
  `_unresolved_payload`, `_match_note` (repr of list), `_no_rates_hint`,
  `_format_lodging_range`, `_fiscal_year_for_month`, round2 (Python
  half-even on exact halves), then the 7 tools in Python key order with
  `null` kept (not undefined) and floats wrapped with `float()`.
- `compare_locations`: catch ToolError only, `pySlice(msg, 200)`; stable
  descending sort on `max_daily_total ?? 0`.
- Current FY / next-month FY from UTC date (`now` injectable for tests and
  boundary-date parity).

## Parity harness plan

- `deploy/gsa-perdiem/parity/`: `corpus.json` (scenarios: optional fixed
  `today`, `hourly_cap`, upstream fixture map path -> status/headers/body),
  `python_side.py` (runs `gsa_perdiem_mcp.http.create_app()` in-process via
  `httpx.ASGITransport` inside `app.app.router.lifespan_context`, patches
  `server._date`, `_get_client` with `httpx.MockTransport`, resets
  `_response_cache`/`_upstream_starts`, env PERDIEM_HOSTED=1,
  MCP_RESPONSE_CACHE_SECONDS=86400, PERDIEM_API_KEY=test key,
  FEDERAL_API_MIN_INTERVAL_SECONDS=0), `run.ts` (loader -> sqlite, TS side
  with mocked fetch/cache, diff: structuredContent + parsed text JSON-equal,
  isError equal, byte-equal text counted; validation errors compare first line).
- Fixtures: reuse `servers/gsa-perdiem-mcp/tests/fixtures/gsa_city/*.json`
  (9 real FY2027 city responses); a few DEMO_KEY recordings >=4 s apart
  (e.g. Boston MA, Washington DC, Arlington VA, conus/mie/2020,
  state/VA/year/2020, zip/22201/year/2020); synthetic 403/404/429/500/HTML/
  non-JSON/malformed-month/redaction cases. Do not make unmocked calls from
  probes: one earlier probe accidentally reached api.gsa.gov once with a fake
  key (403).

## Resume

```
# Python side (parity, loader tests)
cd servers/gsa-perdiem-mcp && uv sync --frozen --python 3.12
PYTHONPATH=src .venv/bin/python -c "import gsa_perdiem_mcp.server"
# Loader
python3 scripts/load_gsa_perdiem.py --local /tmp/perdiem.sqlite
# Worker (after tools.ts/index.ts exist)
cd deploy/gsa-perdiem && npm ci --ignore-scripts && npm run check && npm test
```
