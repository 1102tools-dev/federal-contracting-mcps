# GSA Per Diem Worker + D1 port: progress

Branch: `worktree-agent-a22db7e792f1d6e15`
Latest commit: see `git log -1` (port complete, 2026-10-08)
Base: `fe60f58` (main at start)

Port of the hosted GSA Per Diem MCP from Worker -> Durable Object -> Python
container to Worker + D1 (SAM.gov pattern). No push, no deploy, no Cloudflare
changes from this branch.

## Status: complete (parent: release pipeline items below)

- [x] `schema.sql`; `scripts/load_gsa_perdiem.py` (`--local`, `--remote` via
      the D1 HTTP API; 8 parts / 326,743 rows / 14.5 MB; atomic release
      switch, idempotent, resumable, statements < 90 KB, no bound params on
      writes). `tests/test_gsa_perdiem_loader.py`: 8 tests incl. remote mode
      against a fake D1 HTTP API.
- [x] Worker: `src/py.ts` (Python value/text semantics), `src/data.ts`
      (snapshot.py + _geo.py over D1), `src/upstream.ts` (live GSA API: 24 h
      Cloudflare cache, D1 hourly budget 950 and 0.6 s start pacing with
      Retry-After cooldown, 15 s timeout, redaction), `src/args.ts` (pydantic
      argument validation with exact ValidationError text), `src/tools.ts`
      (7 tools), `src/mcp.ts` (JSON-RPC + HTTP edge, 55 s deadline -> 504),
      `src/index.ts` (keeps the `GSAPerDiem` Container export; fetch -> `serve`).
- [x] `wrangler.jsonc`: D1 binding `DB` / `gsa-perdiem` /
      `REPLACE_WITH_D1_DATABASE_ID` (top level + production); containers,
      durable_objects, migrations kept; still plain JSON.
- [x] `test/worker.test.ts`: 17 node:test tests on node:sqlite (`test/d1.ts`).
- [x] Parity: `node parity/run.ts` (corpus built per run by
      `parity/build_corpus.py`, Python side `parity/python_side.py` runs the
      package's real HTTP app in hosted mode). 1,344 calls, 56 mocked GSA API
      calls: 1,338 identical, 6 expected, 0 unexplained.
- [x] Workflows: `gsa-perdiem-hosted-tests.yml`, `gsa-perdiem-load.yml`,
      load dispatch in `data-refresh.yml`.
- [x] Privacy text updated for the Cloudflare cache and D1 budget records.
- [ ] Parent: release pipeline (see "Parent to do").

## Documented differences from the Python server

Verified identical by the harness: every tool result (text byte for byte,
isError, structuredContent), pydantic argument errors, upstream request
paths/headers, initialize, tools/list (contract content, Python order),
ping, prompts/resources lists, unknown method/tool, invalid params.

- JSON-RPC parse errors and malformed envelopes (batch, non-object, wrong
  `jsonrpc`, bad `method`): same HTTP 400, code, and id; the message is a
  short text instead of the SDK's JSON-parser text / pydantic union dump.
- 2026-07-28 era (`server/discover`, `subscriptions/listen`): -32601, as the
  SAM.gov Worker; clients fall back to `initialize`.
- Hourly budget: shared in D1 minute buckets (window 59-60 min) instead of a
  per-process exact 3600 s deque; the retry text uses the oldest bucket's
  first call, so it matches in practice.
- Response cache: Cloudflare cache per data center (24 h) instead of one
  in-memory 2,048-entry cache in the single container.
- Pacing: 0.6 s between upstream starts (D1 slot claim) instead of 0.6 s
  after the previous completion; a wait > 40 s answers 504 at once.
- 429 diagnostics order: fetch sorts headers, so `{'limit': ..,
  'remaining': ..}` is listed alphabetically, not in response order.
- Network failure text comes from fetch, not httpx (e.g. "timed out" matches;
  connection errors are worded differently).
- Integers above 2**53 inside GSA responses would lose precision (Python
  keeps them); not seen in GSA data.
- A release switch between two D1 queries of one call could pair a year
  from one release with places from the next; old parts are kept until the
  following load, so no query fails.

## Parent to do (release pipeline)

1. Create the D1 database, put its id in `wrangler.jsonc` (both places), run
   `gsa-perdiem-load.yml` (sam-data-load env, CLOUDFLARE_D1_TOKEN) before the
   Worker deploy. The token needs D1 edit on the new database.
2. `scripts/configure_hosted_image.py`: add `vars: {RELEASE_SHA: <sha>}` to
   the top level and `env.production` of wrangler.release.json (vars are not
   inherited by envs), or `/health.release_sha` stays "development" and
   `verify_hosted_release.py` waits until its deadline.
3. `scripts/verify_hosted_release.py` asserts `/health.admission` equals the
   container's queue for every slug but acquisition-gov; the Worker has no
   admission queue and does not report one. Exempt gsa-perdiem.
4. `publish-pypi.yml` hosted job: also run `npm test` (and optionally
   `node parity/run.ts`, needs `uv sync` in servers/gsa-perdiem-mcp) for
   gsa-perdiem; the container image is still built/pushed and its
   pre-deploy check still exercises the Python container, not the Worker.
5. Privacy notice effective date (src/public-docs.ts) when deploying.

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
  waits for `/health.release_sha == --sha`. The Worker's /health reports
  `status, tools, release_sha` (default "development", as the container) and
  no `admission` (it has no queue); see "Parent to do" 2-3.
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
- `null` values (e.g. `match_note: null`) are kept in wire
  `structuredContent` (confirmed by the harness).

### Argument validation (pydantic lax mode + `pre_parse_json`), verified offline

- Fields in signature order, then extras in input order; extra keys ->
  `extra_forbidden`. Messages: `N validation error(s) for <tool>Arguments\n<loc>\n  <msg> [type=..., input_value=<repr>, input_type=...]\n    For further information visit https://errors.pydantic.dev/2.13/v/<type>`.
  A repr over 50 UTF-8 bytes is cut to its first 25 and last 24 bytes, moved
  inward to character boundaries, joined by `...`.
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
- `upstream_calls` (minute buckets with the minute's first call time),
  `upstream_state` (next_start, cooldown_until).
- Local SQLite file: 14.5 MB. Part id = sha256(layout + file bytes)[:16].
- Expected rows read: year blob 2 (release + years); ZIP 2 more; places 1 + hits;
  get_data_status 1. The tests assert at most 2 statements for a ZIP lookup.

