# Acquisition.gov port to Worker + D1: progress

Branch: `worktree-agent-a7712d90cbb54b2c9`, main merged in on 2026-10-08 (after PR #35 and #37).
Status: LIVE on Worker + D1 since 2026-10-08 20:25 CDT (PR #38, deployed from the branch before merge, as
James approved step 7). Rollback: `npx wrangler rollback 4c2980ac-4464-459f-9fdd-82856de97d0c --env production`
in deploy/acquisition-gov (the previous container-forwarding Worker; the container and image are unchanged).

## Cutover record (2026-10-08)
- D1 `acquisition-gov` created in WNAM: 158b0481-c351-4a03-ba07-288f342d348a.
- First load: the full snapshot built locally from the recording (snapshot 1, fetch times 2026-10-08 03:03-
  2026-10-09 01:09 UTC), exported as SQL (schema + 394 INSERT statements under 100 KB, 31 MB) and imported with
  `wrangler d1 execute acquisition-gov --remote --file` (Wrangler OAuth, no API token handled; 8 s, 41 MB).
  Remote row counts and character totals equal the local snapshot. From the first daily run on main,
  acquisition-gov-load.yml keeps it current.
- Worker-only deploy keeping image e63cc60512f35e84068818dd948ce282760424ef: previous Worker version
  4c2980ac-4464-459f-9fdd-82856de97d0c, new b9b62472-3cf5-4a80-a933-07e20aaa7b62; container "no changes".
- Verified: verify_hosted_release.py passed (1.0.8, 5 tools, part 52 at 1.9M characters, NSF Part 1 PDF);
  check_hosted_health.py all nine ok plus the Dell origin row; spot check 9 of 9 identical to the container's
  answers taken just before the deploy, now 0.1-0.2 s a call (was 0.8-12 s); subscriptions/listen streams its
  acknowledgement at the edge; a 2026-07-28 tools/call answers.

## Session log (newest last)
- Merged main (clean). Recording crawl resumed with `--record-only` in the background
  (`.snapshot.nosync/crawl2.log`).
- Loader: `--replay` of the partial recording into a fresh sqlite works (304 docs parsed, 68 s); a second
  run on top reuses every doc and switches snapshot 1 -> 2. Fixed: the end-of-run carry-forward rule (a PDF
  carries over unless this run or the resumed one stored it fresh; one query instead of one per PDF, which
  mattered for remote D1), and the `fetched` counter. The guidance_pdf timeout fallback already matches the
  live server's timeout answer; left as is.
- Worker written (`src/`): `worker.ts`, `modern.ts`, `rpc.ts`, `pyjson.ts` copied from BLS (both protocol eras,
  listen streams via `listenAtEdge`); new `tools.ts` (five tools over D1), `args.ts` (pydantic emulation incl.
  lax int strings and pre_parse_json, Literal is pre-parsed, plain `str` is not), `text.ts` (Python whitespace,
  splitlines, code-point slicing, sorted), `casefold.ts` (Python casefold; 0 mismatches over all code points).
  `index.ts` keeps exporting the `AcquisitionGov` container class. wrangler.jsonc: D1 binding `DB`
  (`REPLACE_WITH_D1_DATABASE_ID`, top level + production), per-IP limit 120/min. `npm run check` passes; smoke
  test answers all five tools in 1 D1 round trip (2 with an agency filter).
  Gotcha: the file-writing tool turns `\u2028`-style escapes into raw characters, which breaks regex literals;
  escape non-ASCII after writing.
- Parity harness `scripts/parity.py` + `test/parity-cases.json` (263 cases: BLS's protocol cases with our tool
  names, all 53 parts, sections, cursors, every validation path, agency/acronym matching, dates, 25-page PDF
  windows, a failed page, a 404 PDF, multi-part duplicates, 40,000-character truncation, the three guidance
  resources, 2026-07-28 tool calls). Python side = `acquisition_gov_mcp.http.create_app()` with `_fetch_bytes`
  answered from the recording and `_now` = last fetch time. Result: 254 identical, 9 documented (the same
  protocol-level ones BLS documents), 0 unexpected. Run:
  `PYTHONPATH=servers/acquisition-gov-mcp/src servers/acquisition-gov-mcp/.venv/bin/python deploy/acquisition-gov/scripts/parity.py [--db X]`
- Reads only the text rows a page overlaps (part 52's text is 1.9M characters): 1 D1 round trip per call,
  2 for a section/heading lookup or an agency filter.
- CI-sized parity: `test/fixture_recording.py OUT` writes a small recording from the package fixtures plus generated
  PDFs (45 pages, ~11K characters a page, one page over 200K) so 25-page windows hit the 200,000-character cap at
  many offsets (no posted PDF does: largest real window 75K). `test/fixture-cases.json` (81 cases): 81 identical,
  37 windows hit the cap. It found a loader bug: applicability lines were stored as text beside the page body, so a
  long matching line could exceed D1's statement limit and abort a load. Now stored as [start, end] offsets
  (FORMAT 2); the Worker squashes the line from the page text.
- Tests: `test/worker.test.ts` (10 node:test cases over the fixture snapshot: contract verbatim and no "live"
  promises, initialize, snapshot fetch times, round trips, windowed reads, atomic snapshot switch, generic error
  without arguments in logs, HTTP edge, 2026-07-28 calls and listen streams, Python string helpers);
  `tests/test_acquisition_gov_loader.py` (8 pytest cases: first load/reuse/cleanup, incremental carry-forward,
  transient failure keeps last good copy, 404 replaces it, abort on index error/shrink/429 without switching,
  resume of an interrupted run, D1 statement limits, code-point splitting, applicability offsets). The resume
  test found that an aborted run dropped PDFs it had fetched but not yet stored; `run()` now drains pending
  stores before stopping.
- Workflows: `acquisition-gov-hosted-tests.yml` (loader tests, fixture snapshot, check, npm test, shared edge
  test, parity on `test/fixture-cases.json` = 84 protocol + 81 fixture cases, wrangler dry run with
  `--containers-rollout=none`); `acquisition-gov-load.yml` (daily 09:40 UTC + dispatch with `full`; environment
  `sam-data-load`, secret `CLOUDFLARE_D1_TOKEN`, database id from wrangler.jsonc). Decision: NOT dispatched from
  `data-refresh.yml` (handoff 3 asked for that): data-refresh rebuilds package-bundled files weekly and cuts a
  release; this data comes from the live site and the loader is built for daily incremental runs, like SAM's
  nightly load. All CI steps pass locally under bash. `configure_hosted_image.py` already writes
  `vars.RELEASE_SHA` for any config with `d1_databases`, so nothing to change there.
- Recording complete (2026-10-08 20:09 CDT): 1,458 requests total, about an hour at 3.1 s each, no 429/403;
  471 MB. 14 fetch errors, all HTTP 404 (parts 20 and 21 and 12 dead PDF links), as the live server reports.
  Full snapshot from it: 1,444 docs, 41 MB SQLite, 6 minutes. Largest 25-page PDF window 92,743 characters
  (under the 200K cap); 77 PDF pages fail extraction, as in the package.
- Full parity on the complete snapshot: 263 cases, 254 identical, 9 documented, 0 unexpected. Plus 60 random
  PDFs from the whole index (default range, windows around failed pages, pages 3-27): 60 identical.
- Live spot check (local Worker over the full snapshot vs the live container, fetch times ignored): 9 of 9 calls
  identical. The container took 0.8-12 s a call. Live release_sha before cutover:
  e63cc60512f35e84068818dd948ce282760424ef.

## Cutover plan (steps 7-9 of Desktop handoff 3; needs James's go)

1. Push the branch, open the PR (CI: acquisition-gov-hosted-tests.yml).
2. `npx wrangler d1 create acquisition-gov`; put the id in `deploy/acquisition-gov/wrangler.jsonc` (top level and
   env.production); commit.
3. First load from the Mac, from the complete recording, so the site is not crawled twice:
   `CLOUDFLARE_D1_TOKEN=$(security find-generic-password -s cloudflare-api-token -w) PYTHONPATH=servers/acquisition-gov-mcp/src
   servers/acquisition-gov-mcp/.venv/bin/python scripts/load_acquisition_gov.py --remote --replay deploy/acquisition-gov/.snapshot.nosync/rec`
   (retrieved_at = the recording's fetch times). The daily workflow then refreshes the index/parts/guidance and
   rechecks 100 PDFs a day.
4. Worker-only deploy keeping the live image: SHA from `/health` or
   `npx wrangler containers info a03e7823-29ff-4e0c-82ef-1f83bed25b55`; `python3 scripts/configure_hosted_image.py
   acquisition-gov <sha>`; in deploy/acquisition-gov `npx wrangler deployments list --env production` (record the
   rollback version), then `npx wrangler deploy --config wrangler.release.json --env production`.
5. Verify: `python3 scripts/verify_hosted_release.py acquisition-gov --sha <sha>`, `python3 scripts/check_hosted_health.py`,
   spot check vs the old container's answers (captured before the deploy), a subscriptions/listen test. Merge.
6. Later: drop acquisition-gov from container deploys (services.json / publish-pypi.yml / release_plan.py; PyPI and
   check_hosted_health.py stay); update the govnode progress page; a week later delete the container + DO class.

## Done
- Studied SAM (`deploy/sam-gov`), the container Worker, the Python package, mcp SDK 2.0.0 serializers,
  `check_hosted_health.py`, `verify_hosted_release.py`, the release workflow (`publish-pypi.yml`).
- Partial recording crawl (stopped cleanly between requests on request): 163 of ~1458 requests.
- `deploy/acquisition-gov/schema.sql`: written (untested).
- `scripts/load_acquisition_gov.py`: full loader written, compiles, NOT yet run end to end or tested.
  The partial crawl was made by an earlier crawl-only version of this file.

## Half-done / not started
- Loader: never executed in its current form. Next: run `--replay` on the partial recording into a local
  sqlite and fix bugs. Known gaps to review: the carry-forward/`missing` logic at the end of `Loader.run`
  is convoluted; `parse()` timeout fallback shape for guidance_pdf; remote D1 path is untested by design.
- Not started: Worker rewrite (`src/index.ts`, `src/tools.ts`, Python-compat helpers), wrangler.jsonc D1
  binding, package.json scripts, TS tests, parity harness, CI workflow, `.github/workflows/acquisition-gov-load.yml`,
  `scripts/configure_hosted_image.py` RELEASE_SHA var (see below), loader pytest.

## Crawl measurements (2026-10-08, from www.acquisition.gov)
- Index: 573,561 bytes; 51 part cards (parts 20 and 21 absent; their part URLs return HTTP 404);
  1,555 deviation links, 1,401 unique PDF URLs, 42 agency labels; parsed index JSON ~952 KB.
- Pacing: 163 requests in 504 s = 3.09 s/request at the 3 s floor.
- Partial recording: 56 HTML (12.2 MB: index + 53 parts + 2 guidance pages) and 107 PDF fetches
  (104 bodies, 36.8 MB, avg 354 KB, max 3.4 MB; 3 OSHRC links return 404).
- Projected full crawl: 1 + 53 + 3 + 1,401 = 1,458 requests, about 75 minutes, about 0.5 GB of PDFs.
  Too heavy daily, so the loader is incremental: daily it fetches index + 53 parts + 3 guidance (57
  requests, ~3 min), every PDF URL new to the index or previously failed, and the 100 least recently
  fetched existing PDFs (`--revalidate`, so every PDF is rechecked about every 14 days). `--full` refetches
  all. First load is a full ~75-minute run. Runs are resumable (staged snapshot, see design).

## Where the data lives (not in git)
- Partial recording: `/private/tmp/claude-501/-Users-jamesjenrette-Library-Mobile-Documents-com-apple-CloudDocs-Workspace/00ac8416-8b1c-4dc3-8015-1770c492df13/scratchpad/rec1/`
  (`manifest.json` keyed "<url> <first allowed type>", entries {url, final_url, content_type, sha256,
  fetched_at} or {url, error, transient, fetched_at}; bodies in `bodies/<sha256>`). Verified intact:
  every manifest body exists and hashes correctly. The scratchpad may be deleted; regenerate with the
  resume command below (`--record DIR`; `Recorder` resumes into an existing DIR's manifest).

## Key findings (for the Worker and parity)
- Tools fetch: index `https://www.acquisition.gov/far-overhaul/far-part-deviation-guide`; part N
  `<index>/far-overhaul-part-N` for any 1..53 (not only indexed parts); guidance faq
  `/far-overhaul/faqs`, policy_and_guidance `/far-overhaul/policy-and-guidance` (HTML), deviation_guidance
  `/sites/default/files/page_file_uploads/FAR-Council-Deviation-Guidance-on-FAR-Overhaul.pdf` (PDF, pages 1-25);
  deviation PDFs from index links.
- SDK text = `pydantic_core.to_json(result, fallback=str, indent=2)` (mcp/server/mcpserver/utilities/func_metadata.py
  `_convert_to_content`); expected byte-identical to `JSON.stringify(x, null, 2)` for our str/int/bool/null data.
  Live wire: `{"content":[{"text":...,"type":"text"}],"isError":false,"structuredContent":...}`.
- Errors: tool exception -> `{"content":[{"type":"text","text":"Error executing tool <name>: <msg>"}],"isError":true}`,
  no structuredContent. Unknown tool -> text `Unknown tool: <name>`. Argument errors are pydantic messages in the
  same wrapper, e.g. `1 validation error for get_rfo_partArguments\npart\n  Field required [type=missing,
  input_value={}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing`
  (probe: scratchpad `validation_probe.py`). Rules seen: bool->int accepted, " 7 " accepted, "1e3"/5.5 rejected,
  JSON-string "null"/"[..]"/"{..}" pre-parsed for non-`str` fields (source_id is plain `str`), extras ->
  extra_forbidden, input_value repr truncated to 25+"..."+24 chars when over 50.
- Live initialize (2025-11-25): `{"capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":
  {"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"protocolVersion":"2025-11-25",
  "serverInfo":{"name":"acquisition-gov","version":"1.0.8"}}`. SDK also speaks 2026-07-28 (server/discover,
  subscriptions/listen); plan: follow SAM (handshake versions only) and report it.
- Time-of-fetch fields: retrieved_at (every tool; per-deviation retrieved_at in list_rfo_agency_deviations =
  index fetch time), index_retrieved_at. Carry the snapshot fetch times.
- get_rfo_part echoes the raw `section` argument (not normalized); get_rfo_guidance echoes the normalized heading.
- Python helpers TS must mirror: whitespace = str.isspace set (0x9-0xd, 0x1c-0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000-0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000); casefold = lower() except 297 code points (Cherokee
  ranges + ~80 specials: ß->ss, ligatures, Greek); `!r` repr quoting; code-point lengths/slices.
- Release: `publish-pypi.yml` deploys with `wrangler deploy --config wrangler.release.json` (no `--var`), and
  `verify_hosted_release.py` waits for /health `release_sha`. The Worker must get RELEASE_SHA as a var: plan is to
  have `configure_hosted_image.py` add `vars.RELEASE_SHA` to each env in wrangler.release.json.

## Design (implemented in loader/schema, untested)
- Content-addressed docs (`docs`, `chunks`, `headings`, `pages`, `index_parts`, `index_deviations`) keyed by
  hash(parser version, kind, inputs, body sha); `sources(snapshot, key)` maps index/part:N/guidance:X/pdf:URL to
  final_url, source_id, retrieved_at, sha, fetch error, doc. `meta.current` pointer flips in one statement; the
  previous snapshot is kept; staging is resumable. Parsing runs in child processes with the package's own
  functions: `_parse_index`, `_parse_html_document` (node captured by wrapping `_extract_section`; heading
  section spans verified against `_extract_section`), `_read_pdf` one page at a time (exact per-page text,
  failures, cap flag), labeled-date patterns captured from `_pdf._labeled_date` and all match positions stored
  so any page range's dates can be resolved, applicability lines via `_extract_document_fields` per line.
- Remote writes: D1 HTTP API `/query` with literal multi-statement SQL (each statement < 90 KB, request < 900 KB).

## Next steps (in order)
1. `--replay` the partial recording into local sqlite; debug loader; add `tests/test_acquisition_gov_loader.py`.
2. Finish the recording crawl (resume command below), then rebuild.
3. Worker: `src/py.ts` (Python-compat), `src/tools.ts`, `src/index.ts` on SAM's structure; keep exporting the
   `AcquisitionGov` container class; wrangler D1 binding (placeholder id) top-level + env.production; limit 120.
4. Parity harness (Python tools with `_fetch_bytes`/`_now` replayed from the recording vs Worker over the
   replayed sqlite), 50+ cases; node:test tests; CI + load workflows; configure_hosted_image.py vars.

## Resume commands (from the worktree root)
- Python env: `cd servers/acquisition-gov-mcp && uv sync --frozen --python 3.12` (iCloud marks .pth files hidden,
  so the loader also adds `servers/acquisition-gov-mcp/src` to sys.path).
- Resume recording crawl: `servers/acquisition-gov-mcp/.venv/bin/python scripts/load_acquisition_gov.py --local /tmp/acq.sqlite --record <scratchpad>/rec1 --full`
  (current loader; fetches index/parts/guidance again and all PDFs; ~75 min; polite 3 s spacing).
- Build from recording only: `... scripts/load_acquisition_gov.py --local /tmp/acq.sqlite --replay <scratchpad>/rec1`
  (note: replay aborts on URLs missing from a partial recording; finish the crawl first or add a skip option).
