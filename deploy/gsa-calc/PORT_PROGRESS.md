# GSA CALC+ port to Worker + D1: progress

Branch `calc-d1-port`, worktree `Code/fcm-calc-d1` (main checkout untouched). Handoff:
`Artifacts/1102tools/calc-d1-handoff.md`. Plan: `~/.claude/plans/users-jamesjenrette-workspace-artifacts-rustling-quasar.md`.
Loader and Worker work in their own progress files: `LOADER_PROGRESS.md`, `WORKER_PROGRESS.md`.
Status: building. No D1 database yet; production untouched.

## Decisions
- 2026-10-31, James: statistics come from the copy, true values. Percentiles use the `floor(q·n)` rule
  (equal to GSA's own answers on small result sets; GSA's TDigest estimates on big ones drift up to
  $2.93/hr between identical calls). The histogram is a deterministic version of Elasticsearch's
  variable-width clustering. Nothing calls GSA at answer time. If more than a handful of
  price_reasonableness_check verdicts (status, iqr_position, vs_median) change in parity, stop and ask him.
- Two layers in the Worker: `emulator.ts`/`stats.ts` answer GSA's query strings from D1 with GSA's
  body shape; `tools.ts`/`validate.ts` are a line-by-line port of `server.py` calling the emulator
  where Python calls `_get`. Parity checks each layer on its own.
- Snapshot windows (`v_from`/`v_to` + meta `current`), see `schema.sql`. Fallback to the Python
  server (Dell, then container) only on a D1 error or an empty copy, capped at 10 a minute.
- No full D1 load before the November 7 billing reset (the October cycle is past 50M rows written).
  A scratch-D1 sample (~10k records) is fine before then.

## Facts from the recorded fixtures (night 2026-10-10, 9 answers)
- wage_stats sum/avg/min/max: float32 prices added in double; equal in every case. Population σ.
- Percentiles at n = 1, 2, 3, 15, 24: exactly the floor(q·n)-th sorted float32 value. At n = 91: TDigest
  estimates (p50 99.688 vs exact 100.64).
- current_price terms keys are strings ("60.0783"), ordered count desc then key asc (string order).
- Hit `sort` values are the source value (`[28.9]`), not float32. Ties at equal price come back in
  shard order (…485 before …484, …486 before …487): compare hit order up to ties.
- `_timestamp` equal on all 49 hits (2026-10-10T02:00:03Z): one value per night.
- education_level_counts: filters buckets AA, BA, HS, MA, PHD, TEC, zero counts kept.
- security_clearance bucket key "false"; min_years_experience keys are strings ("3").

## Session log (newest last)
- 2026-10-31 20:53 CDT: plan approved. Worktree created from origin/main 4f4ae5f.
- 2026-10-31: PR #289 merged (59b57fb): `scripts/load_gsa_calc.py` record + probe,
  `deploy/gsa-calc/scripts/make_probes.py` → `probes.txt` (171 probes), `.github/workflows/gsa-calc-load.yml`
  (dispatch only, no credentials). Pull logic tested offline against a simulated GSA (40,000 records,
  ties shuffled per call, and a 13,000-record single price): every record collected, ~96–126 calls per
  40,000 records.
- 2026-11-01 02:15 UTC: night-1 recording started on GitHub (probe then full pull), run 41263303785.
- Schema v1 written (`schema.sql`); matching columns (terms.folded, which indexes) may change once the
  probes are read (PROBE_FINDINGS.md).
- 2026-11-01 ~02:30 UTC: two background agents started against schema v1: loader (LOADER_PROGRESS.md:
  build/diff/refresh, tests, full local build of night 1 when the artifact lands) and Worker
  (WORKER_PROGRESS.md: protocol copy, tools port, emulator/stats, tests, parity harness + 350+ cases).
  Next for the coordinator: read the probes once the run finishes and write PROBE_FINDINGS.md; dispatch
  night 2 (full pull) after 02:00 UTC Nov 2 for churn.
- 2026-11-01 04:30 UTC: night-1 recording done (run 41263303785: 849 GSA calls, 106 min; index
  ceilingrates-2026-11-01_02-00-03). Loader built the copy: 351,334 records = GSA's priced count,
  every price and _source byte-identical to the recording, one _timestamp for the night, 430 MB,
  projected first load 1,903,471 D1 rows (10k sample: 57,337). Committed 9b5c35d (Worker) and 4421f8f (loader).
- Probe findings (PROBE_FINDINGS.md): keyword = every 2–3-char n-gram of the keyword present (not a
  substring), `*` literal; sin filter = exact match on standard-tokenizer pieces (reproduced 5 of 5 codes);
  sum_of_squares needs exact summation. Sent to the Worker agent to implement and rerun the comparisons.
  Loader asked to keep cleanup one night behind (closes a read race at the switch).
- 2026-11-01 05:30 UTC: Worker implemented the probe findings (keyword = every min(4, length)-char gram in
  one field value, 61/61 keyword probes; sin = standard-tokenizer term; quirks). compare-emulator over
  1,015 night-1 answers: 0 different (verified by rerun). Tools parity on the real copy: 605 cases, 592
  identical, 13 documented, 0 unexpected. Committed ef3285b.
- PR #293 merged: gsa-calc-load.yml `probe-record-cases` (probes + full pull + Python server on every
  parity case, ~3 h), scheduled ONCE for 02:20 UTC Nov 2 so it doesn't need the Mac. Remove the
  schedule after it runs. Then: build night 2 change-only on the night-1 copy (churn + rows), rerun
  compare-emulator, `parity.py --verdicts`, scratch-D1 sample, report to James.
