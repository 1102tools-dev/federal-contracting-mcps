# eCFR loader: progress

Owner: the loader agent. Files: `scripts/load_ecfr.py`, `deploy/ecfr/scripts/assemble_reference.py`,
`tests/test_ecfr_loader.py`, `.github/workflows/ecfr-load.yml`, this file, and
`deploy/ecfr/.snapshot.nosync/*` (sqlite builds, reports).

## Notes for the Worker agent (contract details the loader fixed)
- No change by the loader to the Content format / Flags contracts. `schema.sql` change by the
  coordinator (2026-10-31 ~18:00): `nodes` is an ordinary rowid table now (PRIMARY KEY (title, key)
  autoindex); the loader doesn't depend on WITHOUT ROWID (upserts use ON CONFLICT (title, key)) and
  estimates 3 D1 writes per node row for `--max-rows`.
- `meta` row `version`: every loader run that writes anything (build, refresh, verify) sets it to a
  new value (`<UTC timestamp>-<8 hex>`, e.g. `2026-10-31T23:04:15.711054Z-7501fd71`) as the LAST
  statement of each write (after the titles row of that title, so the run's last request carries it
  too). A run that writes nothing leaves it alone. Key the answer cache to it.
- `docs` row name for agencies.json: `agencies.json` (seq 0, 1, ...; concatenate `text` in seq order
  to get the body exactly as eCFR sent it).
- `nodes.children`: full child keys. One node in all titles (40 CFR 721 subpart E, 2,669 children,
  165 KB) is too big for one D1 statement, so the loader inserts it and then appends the rest with
  `UPDATE ... SET children = children || ...`. Readers see the whole value; nothing to do.
- Content is chunked when the node row would not fit one statement (content over 85,000 bytes,
  or a smaller content beside a big `children`). `chunks > 0` means `content` is NULL; read
  `chunks` rows `seq` 0..n-1 and concatenate `text`.
- hed1 keys are `hed1:#<n>`, n = 0-based position among all the parent's children.
- Reference for the TypeScript port: `deploy/ecfr/scripts/assemble_reference.py` `assemble()`
  (single unit vs container shape, group records and context keys, section_count,
  hierarchy_metadata with the date in and `url`, table_note, the three warning strings copied
  verbatim). It reads only nodes/chunks rows. Its `verify` proves it equals `_xml_text.parse()`.
- Subject groups: XML `DIV7 N` equals the structure's generated identifier (seen in Title 1), and the
  generated-id subpart in Title 48 (970.23) is `DIV6 N="ECFR9c2c643993d7644"`, so every DIV aligns by
  type + identifier. Key: `.../subject_group:ECFRbf8cbe3dda76da6`.
- `nodes.meta` is the parsed hierarchy_metadata object (`_SUBSTITUTE_DATE_` kept, no `url`); NULL when
  the DIV has none (title/chapter/subchapter/hed1 rows, and the whole-title XML never has it).
- Flag reasons per key are in `<sqlite>.flags.json` next to each local build (not in D1).
- Group HEAD images (WORKER_PROGRESS "For the loader"): the stored unit of a subpart or subject
  group is the in-part rendering (HEAD images counted twice). A group whose first HEAD holds an IMG
  gets flag 1 (reason "image in heading"), so its own `?subpart=` request forwards; the part answer
  uses the stored count as is and is exact. None in Title 48 or Title 1.
- `deploy/ecfr/.snapshot.nosync/.gitignore` (`*`) keeps recordings and sqlite builds out of git.

## Remote load (approved 2026-10-31; James runs it, the loader agent makes no Cloudflare calls)
`build --remote` loads from the recording one title or batch at a time, change-only: rows whose
hash already matches are skipped, so rerunning a loaded title writes ~0 rows (only the safety-net
rotation row in `meta` is rewritten when the set of loaded titles changes, 1 row). It prints
`title N: ... X rows written` per title, `rows written: TOTAL` at the end and a JSON summary
(`--json` keeps it), and refuses a title before writing anything when its estimate (3 per node:
row, primary-key index, identifier index; 2 per chunk; +1 for meta version) would pass
`--max-rows` (default 200,000), then stops on the measured `meta.rows_written` sum too. An empty database gets `schema.sql` applied automatically
on the first run (`CREATE TABLE IF NOT EXISTS`, one request); the separate equivalent is
`npx wrangler d1 execute <db-name> --remote --file deploy/ecfr/schema.sql` from `deploy/ecfr`.

    cd /Users/jamesjenrette/Workspace/Code/fcm-ecfr-d1
    export CLOUDFLARE_D1_TOKEN=...        # the D1-capable API token (Keychain cloudflare-api-token)
    export CLOUDFLARE_ACCOUNT_ID=846d3e41e48446abcd3570c0959f9fb5
    REC=deploy/ecfr/.snapshot.nosync/rec-2026-10-29
    PY="servers/ecfr-mcp/.venv/bin/python -I scripts/load_ecfr.py"
    $PY build --remote --database-id <ecfr-db-uuid> --rec $REC --titles 48 --max-rows 40000 \
        --json deploy/ecfr/.snapshot.nosync/remote-48.json
    # then the rest, each batch under 200,000 rows at 3 per node (node counts from the recorded structures):
    $PY build --remote --database-id <uuid> --rec $REC --titles 1 2 3 4 5 6 7 8 9 10 11 12 13 14     # 60,867 nodes, ~182.6k rows
    $PY build --remote --database-id <uuid> --rec $REC --titles 15 16 17 18 19 20 21 22 23 24 25 26 27  # 60,716, ~182.1k
    $PY build --remote --database-id <uuid> --rec $REC --titles 28 29 30 31 32 33 34 36 37 38 39   # 49,984, ~150.0k
    $PY build --remote --database-id <uuid> --rec $REC --titles 40 41 42 43 44 45                  # 57,227, ~171.7k
    $PY build --remote --database-id <uuid> --rec $REC --titles 46 47 49 50 35                     # 30,937, ~92.8k (+ reserved 35's titles row)

A batch only builds titles whose recording is complete (others are listed under "skipped" and
write nothing), so wait for `recording complete` in `rec-2026-10-29/record.log` (the second one)
before the batches. A title whose recorded date differs from its titles.json row is skipped too.
After the load, `refresh` brings each title from 2026-10-29 to the current date, change-only.

Expected remote rows for Title 48 alone. Old schema (WITHOUT ROWID nodes; measured by the
coordinator: 30,161): 15,073 x 2 + 8 chunks + 1 titles + 2 docs + 2 meta rows x 2 (rowid table
with a TEXT primary key) = 30,161, which matches. New schema (rowid nodes) with the version row:
15,073 x 3 = 45,219 + 8 chunks + 1 titles + 2 docs + meta (agencies hash, rotation, and version
written once per write: 3 writes; 5 x 2) = **45,240** (45,234 with a loader from before the
version row). All titles: 274,804 x 3 + ~2,200 chunks (estimated from section sizes) + 50 titles
+ 2 docs + ~100 meta writes = about **827,000** (measured counts in the all-titles entry below
once built).

## Plan
1. `build`: recording -> sqlite (or D1) via one change-only writer (`sync`).
2. `deploy/ecfr/scripts/assemble_reference.py` + `verify-build` over every part/section/appendix/subpart.
3. `RemoteD1` with rows_written summing and `--max-rows` cap; fake-transport tests.
4. `refresh` (live, change-only) and 5. `verify` (weekly rotation from whole-title XML).
6. `tests/test_ecfr_loader.py`. 7. `.github/workflows/ecfr-load.yml`.
8. `ecfr-48.sqlite` once Title 48 is recorded; `ecfr-all.sqlite` + full verification when the
   whole recording is complete.

Development copy while the recorder chain might still reload `scripts/load_ecfr.py`: the second
recorder process (all titles) imports the file when Title 48 finishes, so the file in the worktree is
only replaced by a tested version after that process has started.

## Log (newest last)
- 2026-10-31 16:50: plan written. Recording: Title 48 in progress (~20 parts/min).
- 2026-10-31 17:07: loader written in a dev copy
  (`$SCRATCH/repo/scripts/load_ecfr.py`, symlinked servers/ and deploy/), moved into the worktree once
  the all-titles recorder has started. `build`, `refresh`, `verify`, `RemoteD1` (rows_written sum,
  `--max-rows`), change-only `Writer` (upserts, chunks, appended oversize children, deletes, titles
  row last). `deploy/ecfr/scripts/assemble_reference.py` written (assemble + `verify` over a
  recording). `tests/test_ecfr_loader.py`: 19 pass. `.github/workflows/ecfr-load.yml` written
  (dry-run of its shell step checked with a stub uv).
- Partial Title 48 build (348 recorded parts): assemble == parse for 348 parts, 7,641
  sections/appendices, 1,149 subparts, and the 3 real probe answers (?section=15.305,
  ?subpart=15.3, ?part=15); 0 mismatches. Safety-net premise checked: every recorded part parsed
  from the whole-title XML (probe/t48.xml) hashes equal to its per-part rows (0 writes).
- 2026-10-31 17:50: **ecfr-48.sqlite ready**: `deploy/ecfr/.snapshot.nosync/ecfr-48.sqlite` (Title 48
  only, date 2026-10-29; 58 MB). Rows: nodes 15,073 (4 with chunks; 266 flagged: 144 parts and 122
  subparts with no section or appendix below them, all reserved), chunks 8, titles 1, docs 2
  (`agencies.json`), meta 2. Flag reasons per key: `ecfr-48.sqlite.flags.json`. Built with
  `servers/ecfr-mcp/.venv/bin/python -I scripts/load_ecfr.py build --rec deploy/ecfr/.snapshot.nosync/rec-2026-10-29 --local deploy/ecfr/.snapshot.nosync/ecfr-48.sqlite --titles 48`
  (15,086 local rows written; rebuilding it writes 0). Reference check
  (`deploy/ecfr/scripts/assemble_reference.py verify ... --titles 48 --probe deploy/ecfr/.snapshot.nosync/probe`,
  report `ecfr-48.verify.json`): parts 829 match / 144 flagged; sections+appendices 11,564 match;
  subparts 2,173 match / 122 flagged; real probe answers 3/3 match; **0 mismatches**.
  Loader, tests and workflow now in the worktree (all-titles recorder already running, pid 66673).
- 2026-10-31 17:55: `tests/test_ecfr_loader.py`: 20 pass (`servers/ecfr-mcp/.venv/bin/python -I -m pytest -q tests/test_ecfr_loader.py`),
  incl. a CLI `build --remote --titles 48` run against a fake D1 with no tables (schema applied, rerun
  writes 0, `--max-rows 10` refuses with nothing written).
  Live refresh test on a copy of ecfr-48 (eCFR GETs only, paced): with eCFR unchanged it made 2
  requests and wrote 0 rows. With the copy's Title 48 dates rolled back (issue date 10-20) and one
  stored node tampered, it fetched the structure, the versions since 10-20 and 14 parts (18
  requests, 71 s) and wrote exactly 2 rows: the tampered node (back to the build's hash) and the
  titles row. So live `?part=` answers at 2026-10-29 hash identically to the recording.
  Safety net on full Title 48 (whole-title XML probe/t48.xml through a fake fetcher): 987 parts
  checked, 0 differ, 1 request, 0 rows written.
  Title 1 (subject groups: XML `DIV7 N` = the structure's generated identifier, so they align by
  type + identifier like everything else): 28 parts, 288 sections, 22 subparts match, 0 mismatches.
- 2026-10-31 17:55: `deploy/ecfr/.snapshot.nosync/build_all_when_recorded.sh` started detached
  (nohup + caffeinate; output `build_all_waiter.log`). It waits for the second `recording complete`
  in `rec-2026-10-29/record.log`, then builds `ecfr-all.sqlite`, runs the reference verification over
  every title (`ecfr-all.verify.json`) and appends the counts here. If the recorder dies first it
  appends a note instead. Resume: rerun that script (build and verify are change-only/read-only).
- 2026-10-31 18:05: coordinator's schema change (rowid `nodes`) and `meta.version` added: estimates 3 per
  node, every write ends with the version upsert (`Writer.write`), tests updated + 2 new
  (`test_every_writing_run_sets_a_new_version_last`, `test_build_never_rolls_back_a_refreshed_title`:
  `build` skips a title whose copy is newer than the recording). 22 tests pass.
  `ecfr-48.sqlite` rebuilt under the new schema: 37 MB, nodes 15,073, chunks 8, titles 1, docs 2,
  meta 3 (version, docs:agencies.json, verify_rotation); 15,089 local rows; reference check again
  829 parts / 11,564 sections+appendices / 2,173 subparts / 3 probes match, 0 mismatches; rebuild writes 0.
  (My mistake: for a few seconds at 18:04 `ecfr-48.sqlite` was an empty file after a failed shell
  glob; rebuilt at once. If a Worker test failed with "no such table" around then, rerun it.)
  Titles 1-3 (recorded since): 2,674 nodes; 137 parts, 1,911 sections+appendices, 363 subparts match,
  0 mismatches, 0 alignment problems; 152 nodes flagged, all "no section or appendix below".

## Audit of derived parts (branch `ecfr-audit`, from origin/main 58d43ea)
- 2026-10-31 20:30: `load_ecfr.py audit` added, plus `command=audit` in `ecfr-load.yml`.
  - Fetches each part's real `?part=X` answer (and each out-of-part `?appendix=`) at the title's copy
    date. One XML request at a time, 3 s after the previous one completes (the loader's `Fetcher`).
  - Rebuilds the nodes exactly as `build` does (`unit_rows` over the copy's stored structure), then
    writes only rows whose hash changed: the same `Writer`, `rows_written` summed, `--max-rows`, and
    `meta.version` moved by content writes only.
  - Titles go in ascending order; 48 is skipped unless named.
  - The cursor lives in `meta` as `audit_cursor`: `{titles (the plan), title, after (last part done),
    index, date, done, updated}`. It's saved with every 25 parts (`AUDIT_BATCH`) and at each title's
    end. Cursor saves don't move `meta.version`, because no answer changes.
  - Resuming:
    - A new run with the same title list resumes after `after`; a different list starts a new plan.
    - `done: true` means a rerun does nothing until `--restart` (workflow input `restart`).
  - The run stops cleanly after `--minutes` (default 300; the workflow allows at most 330, and the job
    timeout is now 350). What was fetched before a stop (time budget, a 403, eCFR failing) is still
    written and the cursor saved, before the stop is reported.
  - Dates are never mixed:
    - Each title is audited at its copy date when the run reaches it. A refresh that moved it between
      runs just means the rest is fetched at the new date: parts already audited are either unchanged
      across the move or were refetched by that refresh.
    - Each batch is written only if the copy is still at the date it was fetched at. If a writer
      elsewhere moved it mid-run, the batch is dropped, the cursor stays, and the run stops with a
      note; the next run redoes the batch at the copy's date.
  - Log, per part that differed: `title N <part key>: k node(s) differ: <keys>`. Per title:
    `title N (date): fetched of total parts fetched, nodes changed in P parts, rows written`. The JSON
    (`--json`, the step summary) has per title `fetched`, `nodes_changed`, `rows_written` and
    `differed` {part key: nodes}.
  - Concurrency: the same `ecfr-load` group, so an hourly refresh waits (one queued) while an audit runs.
    300 minutes means the copy can lag eCFR by up to ~5 h during an audit run; dispatch a smaller
    `minutes` if that matters.
  - Tests (fake eCFR via httpx.MockTransport and fake D1 only; no live requests from the Mac), in
    `tests/test_ecfr_loader.py`: **29 pass** (22 before + 7 audit). They cover:
    - a derived node that differs is rewritten (only it, 2 rows), and the copy then equals a build from
      the real answers
    - identical parts write no content and keep `meta.version`
    - the cursor resumes (only the remaining part fetched), done stays done, `--restart` starts over
    - the time budget stops cleanly (`main` exit 0, nothing fetched with `--minutes 0`)
    - the copy date moving between runs (audited at the new date) and during a run (batch not written)
    - 48 skipped unless named
    - remote: `--max-rows` refuses with nothing written; a 403 after Part 2 still writes its fix and
      saves the cursor
  - Offline dry run on real data (a copy of `ecfr-all.sqlite`; fake fetcher serving the real sampled
    `?part=` answers in `rec-2026-10-29/sample/` where present, else the derived files):
    - Titles 12 and 20: 628 parts fetched; exactly the two known misses differ: 12 CFR 192
      `subpart:A/subject_group:ECFR9a7490d1c0ea607` (2 rows) and 20 CFR 404
      `subpart:P/appendix:Appendix 1 to Subpart P of Part 404` (chunked: 15 rows).
    - 46 rows in all, the rest cursor saves. On D1 a cursor save is 2 rows (meta row plus its key
      index), about 660 rows for a full pass.
  - Full pass from GitHub: about 8,300 requests at 3 s+ each is about 7 to 9 hours, so 2 runs at
    300 minutes.
  - Dispatch, once merged to main (the `sam-data-load` environment is main-only):
    `gh workflow run ecfr-load.yml --ref main -f command=audit -f minutes=300`. Add
    `-f titles="12 20"` for chosen titles; repeat the same command to continue.
