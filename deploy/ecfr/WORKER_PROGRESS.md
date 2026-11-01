# eCFR Worker port (D1 + forward): progress

Owner: the Worker agent. Loader agent's file: `LOADER_PROGRESS.md`. Contracts: `PORT_PROGRESS.md`.

## Plan
1. Protocol layer copied from acquisition-gov (modern, pyjson, worker, rpc, args, text, casefold, index).
2. Routing: live tools forwarded; Forward signal; D1 errors forward; health local.
3. validate.ts (every server.py input check, same order).
4. assemble.ts (_xml_text.parse output from nodes rows, paginate).
5. structure.ts, definitions.ts, tools.ts.
6. test/d1.ts + test/worker.test.ts over a fixture sqlite; npm check/test.
7. Parity: scripts/parity.py, parity-run.ts, test/parity-cases.json (~300 cases), record into parity-rec.
8. CI workflow ecfr-hosted-tests.yml.

## Status (newest last)
- 2026-10-31: started. LOADER_PROGRESS.md not present yet; rec-2026-10-29 has titles.json/agencies.json.
- Items 1-5 written: `src/` = index.ts (ECFR container + RateCounter, `toBackend` = today's forwarding through
  `originFirst`), worker.ts (`makeWorker(backend)`; Forward from a tool call sends the original request on),
  modern.ts/pyjson.ts/text.ts (copied), rpc.ts (`callTool`: live tools and any D1 error or gap -> Forward,
  never retried), args.ts (pydantic: smart `str | int` unions with `x.str`/`x.int` errors, lax bool, Python
  signature order), validate.ts, assemble.ts (parse + `_Plan`/paginate), data.ts (queries, key paths),
  structure.ts, definitions.ts, tools.ts. wrangler.jsonc: D1 `DB` top level + production. `npm run check` passes.
  Gotcha (as acquisition-gov found): the Write tool turns `\u2028`-style escapes into raw characters;
  non-ASCII in args.ts/validate.ts/definitions.ts is escaped after writing.
- Dev-only check (scratchpad, not in the repo): a throwaway builder of the content contract over the
  recording, plus the Python server's own get_cfr_content over the recorded part XML (sections sliced from
  their part): 10,120 calls (every recorded Title 48 part, subpart and section, every page) identical, 0 diffs.
- Parity harness written (`scripts/parity.py`, `scripts/parity-run.ts`, `test/parity-cases.json`, 445 cases).
  Recording into `.snapshot.nosync/parity-rec/` started (log `.snapshot.nosync/parity-logs/record1.log`).
  Resume/re-record: `servers/ecfr-mcp/.venv/bin/python deploy/ecfr/scripts/parity.py --record --python-only`
  (the manifest skips what is recorded). Probe: eCFR answers `?part=16&section=15.305` with 404.

- Parity, first full run (445 cases) over a partial Title 48 build: 434 identical, 11 documented, 0 unexpected;
  354 answered from D1, 91 forwarded. (That run read `scratchpad/dev48.sqlite`, which turned out to be the loader
  agent's partial build: the scratchpad is shared, so my scratch files now live in `scratchpad/worker/`.)
- Offline structure check: Python's get_cfr_structure / get_ancestry / list_sections_in_part with eCFR's filtered
  answer emulated from the whole-title structure (chain + subtree) vs the Worker: 20,685 calls identical, 0 diffs
  (every Title 48 part at depth none/1/2, every chapter, subpart, section ancestry; list pages and detail).
- Fixture: `test/fixture_recording.py OUT` (recorder format, from the package's XML fixtures, plus `OUT/parity`
  answers) and `test/fixture-cases.json` (153: protocol + fixture tool calls). Built with the loader's dev build
  (`load_ecfr.py build --rec OUT --local X`): 142 identical, 11 documented, 0 unexpected; 147 D1, 6 forwarded.

- Parity on the loader's `ecfr-48.sqlite` (17:50 build): 445 cases, 434 identical, 11 documented, 0 unexpected.
  Recording showed eCFR's structure endpoint ignores `chapter` when `part` is the deepest filter (it answers
  with the part's own chain; `?chapter=1&part=252` = part 252 under chapter 2), but with a subpart a wrong
  chapter is a 404. The Worker now does the same: get_cfr_structure answers those from D1, and
  list_sections_in_part raises the Python server's "Part N is in chapter X" error itself. 4 cases added.
  **Current: 449 cases, 438 identical, 11 documented, 0 unexpected; 364 answered from D1, 85 forwarded.**
  The 85 forwarded: live tools (8 + 2 modern), other dates and raw_xml (12), titles not in ecfr-48 (2, 5,
  29, 41, 50, 1, 35: about 30), not found or inconsistent filters (15.399, part 98, section in another part,
  lowercase appendix, appendix + section), Title 48's whole structure without depth (15,073 nodes > 6,000),
  and find_far_definition misses (8: the Python server searches the FAR/DFARS live).
- Documented differences (11, all protocol-level, the same kinds acquisition-gov documents): tools/list x5
  (contract sorted by name vs registration order; same definitions), invalid JSON-RPC x4 (short message, same
  status and code), NaN literal (Worker: parse error), numeric-looking extra argument names (error order).
- Tests: `test/worker.test.ts` (11 node:test cases over the fixture copy: contract, initialize, answers and
  dates, one D1 round trip per call, what forwards, forwarded bytes and headers, D1 failure forwards without
  retry and logs only a category, staging FORWARD_URL headers, HTTP edge with the 20/min limit, 2026-07-28
  calls/forwards/listen, Python helpers). `npm run check` and `npm test` pass (11/11); shared edge test 28/28.
- CI: `.github/workflows/ecfr-hosted-tests.yml` (loader pytest, fixture copy via `load_ecfr.py build`, check,
  npm test, edge test, fixture parity, production and staging dry runs). Simulated locally with `uv run`:
  all steps pass (fixture parity 155: 144 identical, 11 documented, 0 unexpected).
- Timing over ecfr-48 (node:sqlite): part 52 page 3 84 ms, part 252 page 2 69 ms, chapter 1 structure 78 ms,
  2.101 page 2 11 ms.

## Plan change 2026-10-31 (James, via the coordinator): load now, test on a staging Worker first
- `wrangler.jsonc` `env.staging`: `ecfr-mcp-staging`, workers_dev, no routes, D1 `DB` =
  `REPLACE_WITH_STAGING_D1_DATABASE_ID` (database_name `ecfr-staging`), the same ratelimits, RateCounter DO only
  (its own `migrations`, v1 = RateCounter), no containers, no BACKEND, var `FORWARD_URL` =
  `https://ecfr.1102tools.com/mcp`. Top level and env.production unchanged.
- `src/index.ts`: with `FORWARD_URL` set, a forwarded request goes there with plain fetch (method, body, the MCP
  headers accept/content-type/mcp-protocol-version/mcp-method/mcp-name, plus User-Agent `1102tools-ecfr-staging`
  and `X-1102tools-Monitor: 1` so production counts it as our own traffic); otherwise originFirst + container.
- Dry runs build: `npx wrangler deploy --dry-run --env staging` (bindings: RATE_COUNTER, DB, both limiters,
  FORWARD_URL; wrangler warns that BACKEND and containers are not on env.staging, which is the point) and
  `--env production --containers-rollout=none` (unchanged bindings plus DB).
- `scripts/compare_live.py A B [--cases] [--only] [--json]`: the parity tool calls to two deployed endpoints,
  identical / date-only (bodies equal once dates within 45 days are normalized) / different; each endpoint gets
  one request per 3.5 s; waits 60 s on a rate-limit answer.

## Read replication and answer cache (2026-10-31, James via the coordinator; copied from deploy/sam-gov)
- Every tool call reads through one `env.DB.withSession?.("first-unconstrained") ?? env.DB` session
  (`readSession` in rpc.ts), so reads go to the nearest replica once replication is on.
- Answer cache in `callTool` (rpc.ts), both protocol eras. Only answers the Worker builds from D1 are stored:
  never errors, never forwarded answers. Key: SHA-256 of [RELEASE_SHA (or the package version), meta
  'version', tool, pydantic-validated arguments with keys sorted] at `https://answer-cache.ecfr.1102tools.com/<hex>`,
  so `{}` and `{"title_number": 48}` share an entry and a new load or release never serves an older answer.
  `Cache-Control: public, max-age=86400`. `caches.default` when deployed, `env.ANSWER_CACHE` in tests.
  Flow: arguments pydantic rejects are answered first (no D1, no cache); then the version row (1 small read);
  hit -> the stored text and its parsed structuredContent; miss -> the handler, whose batches each also read
  the version (same round trip as its data), and the answer is stored only if every read saw the key's
  version (no load landed in between). No version row: no caching. A broken or unreadable entry is a miss.
  Hits and misses set `X-1102tools-Cache` (logToolCall logs it as `cache`). Round trips: hit 1, miss 2,
  cache off 1. The loader writes meta 'version' on every write (scripts/load_ecfr.py `Writer.write`);
  `ecfr-48.sqlite` predates that, so parity's cache mode adds a version to a temporary copy.
- Tests (15 pass): one session per call; same bytes from the cache for every D1 tool; same validated
  arguments share an entry; a version bump stops old entries being used; key changes with version and
  release; errors, forwards, a missing version row and a load landing mid-call are not stored; a broken or
  corrupt cache never breaks a call; HTTP and 2026-07-28 responses say miss then hit.
- Parity on ecfr-48.sqlite: cache off 449 cases, 438 identical, 11 documented, 0 unexpected; `--cache` (each
  case sent twice, the second reported, any change flagged): the same counts, 195 second answers were hits,
  0 changed. Fixture parity: same both ways (51 hits). CI runs fixture parity both ways.
- Likely caveat for staging: Cloudflare's Cache API does nothing on workers.dev hostnames, so staging on
  workers.dev would always miss (answers stay correct); the cache only works on a custom domain such as
  ecfr.1102tools.com. Worth checking before judging the cache from staging.

## Left to do / resume here
- When `ecfr-all.sqlite` is listed in LOADER_PROGRESS.md: full parity on it (the non-48 cases should move to
  D1), then 500 random sections across all titles (records ~500 section XMLs at the 3 s pace, ~30 min):
  `servers/ecfr-mcp/.venv/bin/python deploy/ecfr/scripts/parity.py --db deploy/ecfr/.snapshot.nosync/ecfr-all.sqlite`
  `servers/ecfr-mcp/.venv/bin/python deploy/ecfr/scripts/parity.py --db deploy/ecfr/.snapshot.nosync/ecfr-all.sqlite --random 500 --record`
- After staging is deployed: `python3 deploy/ecfr/scripts/compare_live.py <staging url> https://ecfr.1102tools.com --json report.json`.
- `deploy/ecfr/.snapshot.nosync/` is untracked but not git-ignored: keep it out of commits.

## For the loader
- Minor, probably never hit: a group's `images` count differs by role. As a request root (`?subpart=`) the
  HEAD's images count once; as a group inside a part, `_parse_container` inlines the HEAD a second time for the
  label, so they count twice. The Worker uses the stored count as is.
- The scratchpad directory is shared between us; I overwrote `scratchpad/dev48.sqlite` once early on before I
  noticed (sorry). Mine are under `scratchpad/worker/` now.
