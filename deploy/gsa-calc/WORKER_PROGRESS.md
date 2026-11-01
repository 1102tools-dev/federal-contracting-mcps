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

- 2026-11-01 (coordinator's night-1 round, step 1): PROBE_FINDINGS.md implemented in src/rules.ts (+ _score for
  match_all in emulator.ts): keyword and suggest-contains = 2-4 char grams per field (json_each + instr in SQL, one
  bound parameter per field), 1-char nothing, `*` literal; sin = standard-tokenizer pieces via GLOB; filters: same
  field twice -> last, min_years_experience exact, unknown education codes ignored, worksite customer/contractor,
  suggest + filter -> plain search; ordering: several pairs drop idv_piid, sort=desc alone, match_all _score;
  paging: page_size 0/501 answered, empty-body 406. Evidence under "Settled" in PROBE_FINDINGS.md (max gram 4 per
  field: 61/61 keyword probes). stats.ts unchanged: sums were already exactly rounded (= fsum); GSA differs by 1 ulp
  in 158 of 1,005 answers and shard models do worse (documented). Tests updated: npm test 32/32.
- 2026-11-01 (step 2): compare-emulator gained: other-night skip (manifest index), max_score check, categories
  (noise: tie order, tie cut by page edge, 1-ulp sum_of_squares, terminated_early, undercount past GSA's bound;
  gsa-approximate only when GSA never counts more than the copy). Night 1: 0 different (details in PROBE_FINDINGS.md).

- 2026-11-01 (step 3): tools parity on calc-night1.sqlite (521 cases, then the regenerated 605): 592 identical, 13
  documented, 0 unexpected, with and without --cache (435 cache hits); fixture copy and branch copy unchanged (0
  unexpected). parity.py now resolves --db/--rec (node helpers run in deploy/gsa-calc). Per tool on the real copy
  (Mac, node:sqlite; scratch worker/n1/per-tool.ts; rows read are an estimate: match scan + terms rows of the searched
  fields, once per statement, + materialized/page rows): keyword_search p50 94 ms / p95 199 ms, ~295k rows (two terms
  scans of 146,789 rows dominate); igce/price check ~105-125 ms, ~295k; filtered_browse 226/648 ms, 0.7-1.0M rows;
  sin_analysis 249/553 ms, 0.7-0.8M; suggest 10/110 ms; vendor_rate_card 3/21 ms (2 round trips); exact_search 1/183 ms.
- 2026-11-01 (step 4): make_parity_cases.py --db: price-check rates at the copy's p25/p50/p75 (case-rates.ts), plus 14
  VERDICT_TITLES (the only titles with 20+ rates whose keyword population is one verified exact title, found by
  checking all 1,693 such titles) -> 605 cases, 84 of them verdict-bearing price checks (14 low, 56 typical, 14 high
  on the copy). Loader pytest was already in gsa-calc-hosted-tests.yml (uv, Python 3.12).
- 2026-11-01 (step 5): gsa-calc-load.yml: new commands probe-record-cases (probe, record, cases; one job, one stream,
  --gap between phases too, stops at the first failure, one artifact) and cases; uv set up and the package synced
  before any GSA call when cases run; existing commands unchanged (stub run of every command checked). parity.py gained
  --gap. The cases make ~319 distinct GSA calls (about 40 min at 7.5 s); with probes and the pull about 3 h.

## Checkpoint
- Done: steps 1-6 and the coordinator's night-1 round (rules from PROBE_FINDINGS.md, compare-emulator 0 different,
  tools parity 0 unexpected on the real copy, 605 cases at the copy's percentiles, recording workflow).
- Waiting: the coordinator merges .github/workflows/gsa-calc-load.yml (+ deploy/gsa-calc/scripts/parity.py and
  test/parity-cases.json on the dispatched ref) and dispatches probe-record-cases after 02:00 UTC.
- Next, when that artifact lands (offline; PY = `uv run --frozen --python 3.12 --project servers/gsa-calc-mcp`):
  1. build the night's copy from its pull (loader), then `node scripts/compare-emulator.ts COPY REC/pull REC/probes
     REC/cases --json r.json` (cwd deploy/gsa-calc): expect 0 different.
  2. `$PY python deploy/gsa-calc/scripts/parity.py --db COPY [--cache]` (0 unexpected).
  3. `$PY python deploy/gsa-calc/scripts/parity.py --db COPY --rec REC/cases --verdicts --json verdicts.json`; stop and
     ask James if more than a handful of verdicts change.

## Schema requests
None needed. The Worker relies on: meta current (text, CAST in SQL) / version / timestamp; v_to compared in SQL;
records.price and next_year_price float32-as-double; records.sin = ',' || list || ','; security_clearance 1/0/NULL;
terms.folded = Python value.lower() (rules.fold is JS toLowerCase: change both together if PROBE_FINDINGS changes
the folding); sources.json keeps _timestamp in place (rules.withTimestamp replaces its value). If D1 timing of
price-ordered whole-index pages turns out too slow, an index on records(price) would remove the page sort (one more
index write per record).

## Open questions
Settled by the night-1 probes (PROBE_FINDINGS.md "Settled"): keyword/suggest grams, sin tokens, filters, ordering,
paging, match_all _score, summation. Still open:
- GSA's last-digit sum_of_squares (1 ulp in 158 of 1,005 answers) and terminated_early on some suggest answers are
  not reproducible; counted as documented noise.
- Unreachable leftovers: worksite values other than customer/contractor, a mix of known and unknown education codes
  (known ones kept), an unknown ordering field (empty 406 assumed).
- Lowercasing: the copy folds with Python lower()/JS toLowerCase (full mapping); Lucene lowercases per code point
  (simple mapping). Only differs for a few characters such as U+0130.
- Rows read: the keyword match scans `terms` in both the statistics and the page statement (~294k of the ~295k rows
  per keyword call). Folding both into one statement would halve it if D1's rows-read bill or time calls for it.
