# GSA CALC+ Worker port (emulator + tools + protocol): progress

Owner: the Worker agent. Loader agent's file: `LOADER_PROGRESS.md`. Contracts and decisions: `PORT_PROGRESS.md`.
Plan: `~/.claude/plans/users-jamesjenrette-workspace-artifacts-rustling-quasar.md` (Design, Steps 2-3).
Scratch files: `/private/tmp/claude-501/-Users-jamesjenrette-Workspace/2fd06acc-3b93-4c73-af1b-05eeed69974a/scratchpad/worker/`.
Rules: no GSA calls from the Mac, no deploys, no D1 remote commands, no commits or pushes (the coordinator commits).

## Steps
1. Protocol layer from deploy/ecfr/src: pyjson.ts, text.ts, modern.ts, worker.ts, rpc.ts, args.ts (gsa-calc
   signatures, Literal enums, lax float, `str | int` with the bool BeforeValidator), forward.ts, index.ts
   (GSACalc container + HourlyBudget kept, originFirst Dell-then-container, FORWARD_URL on staging).
2. validate.ts + tools.ts: line-by-line port of server.py's 8 tools and helpers; tools call `emulate()`.
3. emulator.ts + stats.ts + rules.ts ("GSA in a box"; every matching/filter/sort rule in rules.ts).
4. wrangler.jsonc (D1 DB, 120/min limiter, env.staging), package.json, tsconfig.json.
5. Tests: test/d1.ts, test/fixture-db.ts, test/emulator.test.ts (emulate == fixture except took),
   test/worker.test.ts; keep tests/hourly-budget.test.mjs; .github/workflows/gsa-calc-hosted-tests.yml.
6. Parity harness: scripts/emulator-serve.ts, scripts/parity.py, scripts/parity-run.ts, test/parity-cases.json (350+).

## Status (newest last)
- 2026-10-31: started. No LOADER_PROGRESS.md, no PROBE_FINDINGS.md, no .snapshot.nosync yet. npm ci done in
  deploy/gsa-calc. Python: `uv run --frozen --python 3.12 --project servers/gsa-calc-mcp` (mcp 2.0.0, pydantic 2.13.2).
  ES 7.10.2 variable_width_histogram sources fetched to scratch `worker/es/` for the histogram port.

- 2026-10-31: steps 1-4 written. src/ = pyjson.ts, text.ts, modern.ts (copied from ecfr), casefold.ts (from
  acquisition-gov), forward.ts (UA 1102tools-gsa-calc-staging), args.ts (8 signatures; Literal enums, lax float with
  pydantic_core's string rules, sin/sin_code bool BeforeValidator, pre_parse_json also for Literal fields), validate.ts,
  tools.ts (8 tools + helpers, quote_plus incl. the surrogate UnicodeEncodeError), rules.ts (every GSA rule),
  stats.ts (exact extended_stats, floor percentiles, terms, ES 7.10 variable_width_histogram), emulator.ts (one batch:
  meta + grouped stats scan + page with LEFT JOIN sources), rpc.ts/worker.ts (120/min, 10/min forwarded, d1 tag,
  cache host answer-cache.gsa-calc.1102tools.com, EMULATOR_TOOK for tests), index.ts (GSACalc + HourlyBudget kept,
  toBackend = FORWARD_URL or originFirst Dell->container, wrapped in withToolCallLog). wrangler.jsonc: D1 DB placeholder
  id 00000000-0000-0000-0000-000000000000 (top level, production, staging), REQUEST_LIMITER 120/60 (namespace ids
  unchanged: 110260, AI 110273), env.staging gsa-calc-mcp-staging on calc-staging.1102tools.com. `npm run check` passes.
- Verified offline in Python (scratch worker/py/check_stats.py, check_hist.py) against every fixture whose
  current_price buckets are complete (n = 0, 1, 1, 2, 3, 15, 24, 91): exact-rounded sum and sum of squares, avg,
  variances, std devs and bounds all equal to the last digit; the ES 7.10 variable_width_histogram port (one shard,
  sorted input, then the final reduce) equals GSA's wage_histogram exactly in all 8, including n = 91.

- 2026-10-31: tests and harness. test/d1.ts (copied), test/fixture-db.ts (schema.sql + every distinct fixture hit, loader
  conventions; `node test/fixture-db.ts OUT.sqlite` writes it; GSA_CALC_TEST_DB overrides; syntheticRecords() deals a
  fixture's complete bucket counts over records), test/emulator.test.ts (9 tests, all pass): the 5 fully recorded
  answers come back byte-identical except took; the 4 partial ones agree on page 1 up to ties; synthetic copies of
  n = 91, 24, 15 give every aggregation exactly (incl. labor_category buckets, histogram), except n = 91's
  percentiles (GSA's TDigest); rules, suggest, 10,000 cap, empty copy, one round trip.
- Parity harness: scripts/emulator-serve.ts, scripts/parity-run.ts, scripts/parity.py (tools / --verdicts / --record
  on GitHub only / --python-only / --cache), scripts/make_parity_cases.py (+ scripts/case-rates.ts for --db rate
  placement) -> test/parity-cases.json (521 cases). On the fixture copy: 521 cases, 508 identical, 13 documented
  (the ecfr protocol set + 2 lone-surrogate parse errors), 0 unexpected; same with --cache.
  Fixes found by parity: the handshake path now refuses lone surrogate escapes as a parse error like the SDK's jiter
  (pyjson.parseRequest; the 2026-07-28 path accepts them like Python, and the tool then gives Python's
  UnicodeEncodeError text); the answer-cache key now keeps NaN/Infinity/-0 floats apart (JSON.stringify made
  price_min="nan" share the key of no price_min and serve a cached success). ecfr's rpc.ts has the same stable()
  but no float arguments.

- 2026-10-31: test/worker.test.ts (16 tests: contract, initialize, every tool, one round trip per GSA call, messages,
  empty copy / D1 failure forward, forwarded bytes, 120 + 10 caps, staging FORWARD_URL, HTTP edge incl. production
  /health -> backend, 2026-07-28 + listen, read session, cache). `npm test` = 32 pass (9 emulator, 16 worker, 7 hourly
  budget); `node --test ../shared/edge.test.ts` 29 pass; `npm run check` passes; dry runs build (production with
  --containers-rollout=none; staging warns BACKEND/containers absent, as ecfr's does).
- scripts/compare-emulator.ts (comparison a): any recordings vs emulate() over a copy; hits up to ties (edge tie groups
  by size), _source exact, totals/terms/wage_stats exact (std/variance 1e-9 rel), percentiles + histogram measured,
  terms with GSA error bound > 0 counted as gsa-approximate. test/fixture_recording.py writes the fixtures as a
  load_gsa_calc.py recording (42 records + the 5 complete answers); the loader's `build` of it: compare-emulator
  5/5 identical, emulator tests pass on it (GSA_CALC_TEST_DB), tools parity 521: 508 identical, 13 documented, 0 unexpected.
- .github/workflows/gsa-calc-hosted-tests.yml: loader pytest, fixture recording -> loader build, check + tests (+ edge),
  compare-emulator, parity with and without cache, both dry runs. Simulated locally: every step passes.

- 2026-10-31: branch coverage. test/fixture-db.ts branchRecords() (made-up records: a 40-rate verified title, a
  25-rate zero-spread title, a title phrase inside a vendor name, 520 titles sharing a word, vendors for the
  whole-word / multi-match / paging notes) + scripts/make_branch_cases.py -> test/branch-cases.json (44 cases): every
  price_reasonableness_check status incl. the verdict at/around p10-p90, z-score null, UNVERIFIED_POPULATION; every
  vendor_rate_card note. Parity on that copy: 44/44 identical (with and without cache); parity-cases.json on it too:
  508 identical, 13 documented, 0 unexpected. CI runs both.
- 2026-10-31: confirmed from fixture approximate_population_control: whole-dollar current_price keys are "110.0",
  "149.0", "180.0" (float32 printed like Java), as rules.termsKey writes them; no key over 7 significant digits.
- 2026-10-31: timing on a synthetic 351,357-record copy (scratch worker/perf/, node:sqlite on the Mac, not D1): whole-
  index calls 0.46-0.98 s (keyword "a" 351k matches 0.98 s: ~0.25 s stats scan + ~0.23 s page sort, JS stats < 20 ms),
  sin_analysis 54151S 0.2 s, keyword "engineer" (50k) 0.16 s, narrow calls 0-30 ms; RSS 171 MB. Rows read per GSA
  call: about twice the matched records (stats scan + page sort) plus the terms LIKE scan. Tools parity on that copy:
  521 cases, 0 unexpected.

## Checkpoint
- Done: steps 1-6 (code, tests, CI workflow, parity harness, 521 + 44 cases, compare-emulator).
- Waiting: the loader's night-1 copy (`.snapshot.nosync/calc-night1.sqlite`) and the night-1 recording (run
  41263303785: probes + full pull), then PROBE_FINDINGS.md from the coordinator.
- Next, in order (all offline; paths from the repo root; PY = `uv run --frozen --python 3.12 --project servers/gsa-calc-mcp`):
  1. `node deploy/gsa-calc/scripts/compare-emulator.ts COPY REC/pull REC/probes --json report.json` (cwd deploy/gsa-calc
     or absolute paths): fix every "different" by changing src/rules.ts only (PROBE_FINDINGS.md wins).
  2. `$PY python deploy/gsa-calc/scripts/parity.py --db COPY [--cache] [--show]` (tools, must stay 0 unexpected).
  3. `python3 deploy/gsa-calc/scripts/make_parity_cases.py --db COPY` (price-check rates at the copy's p25/p50/p75),
     then the GitHub recording of the cases: `$PY python deploy/gsa-calc/scripts/parity.py --rec DIR --record
     --python-only` (needs GITHUB_ACTIONS=true; 7.5 s per GSA call through load_gsa_calc.Recorder).
  4. `$PY python deploy/gsa-calc/scripts/parity.py --db COPY --rec DIR --verdicts --json verdicts.json` (stop and
     ask James if more than a handful of verdicts change).

## Schema requests
None needed. The Worker relies on: meta current (text, CAST in SQL) / version / timestamp; v_to compared in SQL;
records.price and next_year_price float32-as-double; records.sin = ',' || list || ','; security_clearance 1/0/NULL;
terms.folded = Python value.lower() (rules.fold is JS toLowerCase: change both together if PROBE_FINDINGS changes
the folding); sources.json keeps _timestamp in place (rules.withTimestamp replaces its value). If D1 timing of
price-ordered whole-index pages turns out too slow, an index on records(price) would remove the page sort (one more
index write per record).

## Open questions (provisional rules in src/rules.ts, for PROBE_FINDINGS.md)
- keyword: case-insensitive substring of the whole phrase over the three fields, `*` any run, `?` literal.
- search=field:value: exact and case-sensitive; value cut at its first colon (fixture-confirmed). suggest-contains:
  case-insensitive substring like keyword; answer shape = hits.total (10,000 cap) + that one terms aggregation, no
  hits, no other aggregations (unknown: GSA may send more; the Python tool reads only those two).
- filters: price_range inclusive on float32 bounds; experience_range numeric inclusive; education codes -> words
  (HS = High School + High School Equivalent, TEC = Other Tech School or Certification, PHD = PhD; fixture-
  confirmed counts); sin whole code, ASCII case-insensitive; security_clearance yes/no -> true/false; worksite,
  vendor_name, labor_category filters ignored. min_years_experience terms keys sort as strings in GSA's answers
  ("30" before "9"), so it may be a keyword field: then experience_range and ordering by it could be lexicographic.
- ordering pairs in turn, missing values last, ties by _id ascending (GSA: shard order); sort value of a missing
  price is null here (ES may write Infinity). Repeated keyword/search params: the last one wins.
- errors: page*page_size > 10,000, bad page/page_size or an unknown ordering -> 406 with a JSON detail text (the
  Python server never sends these).
- Percentiles: true values by James's decision; fixture n = 91: 5 of 9 equal GSA's TDigest, the others within $0.95
  (p25 +0.735, p50 +0.952, p65 +0.421, p70 -0.270). Histogram: ES 7.10 algorithm, one shard, sorted input; equals
  GSA on every fixture (n <= 91). Past ~450 prices per GSA shard GSA's 5-shard clustering differs. If the full
  recordings show many histogram differences, emulating GSA's routing (murmur3 of _id, 5 shards) would reproduce
  it exactly up to ~6,000 prices per shard.
