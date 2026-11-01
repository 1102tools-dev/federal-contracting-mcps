# GSA CALC+ loader: progress

Owner: the loader agent. Files owned: `scripts/load_gsa_calc.py`, `tests/test_gsa_calc_loader.py`,
this file, `deploy/gsa-calc/schema.sql` (changes listed under "Schema changes"), and
`deploy/gsa-calc/.snapshot.nosync/` (git-ignored). Branch `calc-d1-port`, worktree `Code/fcm-calc-d1`.
Nothing here commits, pushes, deploys, creates a D1 database or writes to a remote one. Zero GSA calls from
the Mac.

Brief (from the coordinator, 2026-10-31): add `build`, the `--remote` target, `diff` and `refresh` to
`scripts/load_gsa_calc.py` (standard library only, Python 3.9+), tests in `tests/test_gsa_calc_loader.py`,
then a full local build of the night-1 recording (GitHub run 41263303785, artifact
`gsa-calc-rec-41263303785`) into `deploy/gsa-calc/.snapshot.nosync/calc-night1.sqlite` with a report.

## Steps
1. Create this file.
2. `build --rec DIR --local DB [--limit N] [--json F]`: recording -> schema.sql rows, night 1 and
   change-only later nights (stage N+1, one-statement switch, cleanup), written_estimate counting.
3. `--remote` target (RemoteD1 copied from load_ecfr.py; database id from --database-id,
   GSA_CALC_D1_DATABASE_ID or wrangler.jsonc env.production d1_databases). Not run against any real D1.
4. `diff --a REC --b REC`: churn, id stability, distinct _timestamp, changed keys, projected refresh rows.
5. `refresh --local DB | --remote [--rec DIR]`: index unchanged -> no writes; else record (or use --rec),
   build change-only, --max-rows checked before staging and before the switch.
6. Tests `tests/test_gsa_calc_loader.py` with a synthetic two-night recording.
7. Download the night-1 recording when run 41263303785 completes; full local build; report numbers.
8. (Coordinator, 2026-11-01, after commit 4421f8f) Keep cleanup one night behind: at the switch to N+1
   delete only rows with v_to <= N (plus their sources rows and unused terms); rows retired at this switch
   stay until the next one. Update schema.sql's header, counting, diff's projection and tests.

## Checkpoint
- Done: steps 1-8. Night-1 recording in `.snapshot.nosync/rec-night1/` (probes/ and pull/), built into
  `.snapshot.nosync/calc-night1.sqlite` (status in `calc-night1.status.json`, log in `calc-night1.build.log`).
- In progress: nothing.
- Next (coordinator): scratch-D1 measurement with `build --remote --limit 10000 --database-id <scratch>`
  (compare D1's rows_written with written_estimate); a night-2 recording for `diff`; add
  tests/test_gsa_calc_loader.py to the CALC+ CI workflow.

## Schema changes
- 2026-11-01 (step 8): comments only, no DDL change. The header now says the copy keeps the night before
  the current one too, and a refresh deletes rows with v_to <= N after the switch to N+1 (those closed at
  the previous switch), not v_to <= N+1. The terms comment says terms stay while any remaining row (night
  N+1 or the night-N rows kept a night) uses them. Worker impact: none for queries (they already read
  `v_from <= N < v_to`); the copy holds one night's churn more rows (night 1: about 7,000 at 2% churn).

## How build works (for a fresh agent)
- Two passes over records.jsonl.gz: `scan` (id, content hash, terms, _timestamp counts, checks), then
  `write_records` for the positions the plan inserts. `make_plan` compares stored rows (read in rid pages:
  rid, id, hash, v_from, v_to) with the recording: live rows that match stay (reopened if a stopped run
  closed them); other live rows are retired (v_to = N+1) and kept for night N until the next switch;
  staged rows of a stopped run (v_from = N+1) are kept when they still match, dropped otherwise; rows with
  v_to <= N (retired at the previous switch, or left by a stopped cleanup) are deleted after this switch;
  orphan sources rows (a stopped run inserted sources but not records) are deleted.
- Terms after the switch = night N+1's values plus the values of the rows retired now (`plan_terms`,
  reading those rows' three fields by rid); new or refolded terms are upserted before the switch, terms
  outside that set deleted after it. So terms always cover nights N and N+1.
- Order: meta staging -> drop stale staged rows -> reopen -> terms upsert -> sources then records inserts
  (INSERT OR IGNORE, rids assigned by the loader from max(rid)+1) -> close -> count check (night N+1 must
  hold exactly the recording's records, else no switch) -> one meta upsert (current, version, timestamp,
  loaded_at) -> cleanup a night behind (sources and records with v_to <= N, unused terms, meta staging).
- `--max-rows`: the whole projected total is checked before any write (RowCap "Nothing written"); a run
  that D1 bills past the cap stops mid-staging, never switched; switch+cleanup are checked again before
  the switch.
- Refusals (exit 2, nothing written): a recording older than meta version; a change-only night whose
  recording has fewer records than summary priced_records, or unresolved/lost > 0 (`--allow-short`).
- written_estimate: records/sources/terms/meta are table rows; index_entries = 3 per records insert or
  delete + 1 per meta key inserted or deleted. Local rows_written (SQLite total_changes) equals
  total - index_entries; tests check it. A build's deletes are the rows the previous switch retired.
- diff's `projected_rows_written` is what the change from A to B costs in all (same as before step 8);
  `projected_split.at_switch` is the refresh to B (inserts, closes, new terms, meta) and
  `projected_split.next_switch` the deletes of the rows B retired and their terms, paid at the switch
  after B. A real refresh to B also pays the previous change's next_switch.

## Notes for the Worker agent
- `sources.json` keeps the `_timestamp` of the night the row was written. Rows are rewritten only when
  their hash (which excludes `_timestamp`) changes, so the Worker must put meta `timestamp` in its place
  in every returned `_source` (same key position).
- `meta.current` is text ('1'); `v_to` of an open row is 9223372036854775807 (compare in SQL, never in JS).
- terms holds only non-null values; `folded` is `value.lower()` (Python) for now; one function `fold()`.
- Night 1 facts (2026-11-01): every labor_category, vendor_name and idv_piid term has value.lower() equal to
  an ASCII-only lowercase (no uppercase non-ASCII letters), so SQLite's ASCII lower()/LIKE agrees with
  `folded` on this night. Non-ASCII in labor categories: en dash (1,969 values), e-acute (262), no-break
  space (111, some trailing), em dash, 13 values with a newline, curly quotes. 1,707 labor categories
  differ from another only by case (133,371 distinct, 131,664 lowercased).
- Whole-index wage_stats: SUM(price) over the copy equals GSA's sum, avg, min and max exactly. GSA's
  sum_of_squares (8290102411.919576) is the exactly rounded sum (math.fsum); a naive double loop gives
  ...922192. Use compensated summation for sum_of_squares/variance.
- education_level words: Bachelors, High School, Associates, Masters, High School Equivalent, None, PhD,
  Other Tech School or Certification, MD DO (1). GSA's filters buckets: HS = High School + High School
  Equivalent; "None" and "MD DO" are in no bucket. Counts match GSA's education_level_counts exactly.
- Since step 8, night N stays whole after the switch to N+1 (until the following switch), so a request
  that read `current = N` just before a switch still finds every night-N row, its sources JSON and its
  terms. Meta `timestamp` moves with `current`; read current, version and timestamp in one query.

## Log (newest last)
- 2026-11-01 02:10 UTC: started; run 41263303785 in progress. Mac SQLite 3.54 parses Python's repr()
  floats exactly (200,000 float32 prices round-tripped through SQL literals, 0 mismatches).
- 2026-11-01 02:20 UTC: steps 2-6 done. `build`, `--remote` (RemoteD1 copied from load_ecfr.py, plus
  size_after capture and INSERT OR IGNORE inserts), `diff`, `refresh` (with `--rec`, `--work`) in
  scripts/load_gsa_calc.py; tests/test_gsa_calc_loader.py 26 passed (uv 3.12 and /usr/bin/python3 3.9).
  Night-1 estimate for the 5-record test: 50 rows; night 2: 47, and diff projects the same 47.
- 2026-11-01 02:30 UTC: synthetic timing (scratch only, 351,357 made-up records shaped like GSA's):
  night-1 local build 21.5 s, 290 MB RSS, 432 MB sqlite, written_estimate 1,829,631 (1,054,077 of them
  index entries; 72,834 terms). Night 2 with 2% price churn (7,052 records): diff 8.7 s / 616 MB RSS,
  change-only build 7.7 s, 77,580 rows projected by both. A changed record costs 11 D1 rows (insert 5 =
  row + 3 indexes + sources; close 1; delete 5). pyflakes clean. Profile script for step 7:
  deploy/gsa-calc/.snapshot.nosync/night1-profile.py (DB REC; output calc-night1.profile.json) checks every stored price and sources row against the recording.
  Waiting on run 41263303785 (background poll every 10 min).
- 2026-11-01 04:21 UTC: run 41263303785 completed (success); downloaded to .snapshot.nosync/rec-night1.
  Full local build: 351,334 records = summary priced_records, 20.3 s (20.5 s wall, 508 MB RSS),
  calc-night1.sqlite 429,682,688 bytes (sources 300 MB, records 80 MB, 3 indexes 35 MB, terms 13.6 MB),
  written_estimate 1,903,471 (records 351,334, sources 351,334, terms 146,789, meta 6, index entries
  1,054,008); local rows_written 849,463 = total - index entries. One _timestamp for the whole night
  (2026-11-01T02:00:03Z), one key order. Every stored price equals float32(current_price) and every
  sources row equals the recorded _source byte for byte (report.py). Business size, clearance, worksite,
  education and wage_stats match GSA's whole-index aggregations. Probes: 11 of 171 answered from the
  previous index (ceilingrates-2026-10-31_02-00-02): the workflow started 01:59 UTC, before the rebuild.
- 2026-11-01 04:30 UTC: a `--limit 10000` local build of night 1 projects 57,337 D1 rows (10,000 records +
  10,000 sources + 7,325 terms + 6 meta + 30,006 index entries); that is the number to compare with the
  scratch D1's rows_written. Tests rerun: 26 passed. Nothing committed.
- 2026-11-01 (step 8): cleanup now runs a night behind (`make_plan` retire list, `plan_terms`,
  `stored_values`; diff `projected_split`); schema.sql header and terms comments updated (no DDL). Tests:
  27 passed (uv 3.12 and /usr/bin/python3 3.9), pyflakes clean; new test that night 1 reads identically
  (rows, sources JSON, terms) after the switch to night 2, and loses its retired rows only at the switch
  to night 3. 5-record fixture: night 2 now 29 rows, night 3 (timestamps only) 26 = its 8 + the 18 night
  2's retirees cost; diff n1->n2 total still 47 (29 at switch + 18 next switch). Simulated night 2 from the
  real night-1 recording (scratch: 2% of prices changed, 0.2% removed): build estimate 38,622 = diff
  at_switch exactly; next_switch 35,332; total 73,954; terms 146,789 kept (146,602 for night 2 itself).
  Nothing committed.
