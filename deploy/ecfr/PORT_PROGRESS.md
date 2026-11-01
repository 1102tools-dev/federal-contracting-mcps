# eCFR port to Worker + D1: progress

Branch `ecfr-d1-port`, worktree `Code/fcm-ecfr-d1` (main checkout untouched). Handoff:
`Artifacts/1102tools/ecfr-d1-handoff.md`. Plan: `~/.claude/plans/breezy-kindling-barto.md`.
Status: building. D1 `ecfr` created 2026-10-31 (WNAM, id 52271b16-3137-4dc4-9068-0a311ed09ec8, schema applied,
12 rows written). Production untouched.

2026-10-31, James: the full load goes ahead now. It's ~0.56M rows, under $1, so the Nov 7 wait is dropped. Test on a
separate staging Worker (`ecfr-mcp-staging` on workers.dev, same D1, forwards to production for live tools);
James decides the production switch after we talk. He wants eCFR eventually off the Dell, but said
"keep the Dell in the picture for now": the 5 live tools keep going Dell first, container as backup.

## Decisions
- D1 answers: get_latest_date, get_cfr_content, lookup_far_clause, get_cfr_structure,
  list_sections_in_part, get_ancestry, list_agencies, find_far_definition (when 2.101 defines the term).
- Live (forwarded unchanged through `originFirst`: the Dell, then the container): compare_versions,
  get_version_history, get_corrections, find_recent_changes, search_cfr (unless the side-by-side wins).
- Forward rule for the D1 tools. Forward the original request when any of these holds:
  - a date other than the copy's date for that title
  - `raw_xml=True`
  - the node isn't in the copy, the filters disagree, or the identifier is ambiguous
  - a scope over 4 MB of XML (the structure `size`)
  - a chapter-only scope
  - a node flagged below
  - find_far_definition with no 2.101 definition
  - any D1 error or empty copy

  Validation errors are computed in the Worker, never forwarded.
- Content comes from eCFR's per-part XML (`full/{date}/title-N.xml?part=X`), parsed at load time
  with the package's own `ecfr_mcp._xml_text`, so the text is the Python server's by construction.
  Per-part XML (not the whole-title download) because only it carries `hierarchy_metadata` on
  every DIV.

## Probe facts (2026-10-31, date 2026-10-29)
- titles.json `meta` = {date, import_in_progress}. Title 48 latest_issue_date 10-28 vs
  latest_amended_on 10-19: issue dates move on their own. No latest_amended_on is later than
  up_to_date_as_of.
- The whole-title XML has no hierarchy_metadata attributes, and its HEAD whitespace differs.
  `_xml_text.parse` of a part sliced from it still equals the `?part=` answer (part 15),
  except for the metadata.
- `?section=15.305` parses identically to that section inside `?part=15`, metadata included.
  In part answers the root's hierarchy_metadata is double-escaped (`&amp;quot;`) and the nested
  DIVs' are single-escaped; `_metadata` reads both.
- A filtered structure answer is the title-down chain, each ancestor with only the one child on
  the path, then the full subtree of the target. Node objects are byte-identical to the full
  structure's (0 diffs over Part 15).
- Key order varies by node: `children` comes before `descendant_range`, and `generated_id`
  comes first on generated subparts. Keep eCFR's order.
- Counts: 49 titles; 9,659 parts; 227,254 sections; 23,299 subparts; 8,888 subject groups;
  4,096 appendices (24 outside parts: chapter or subtitle level); 118 hed1 nodes (no
  identifier, no XML DIV).
  - 829 MB of part XML in all.
  - Biggest parts: 26 CFR 1 at 70 MB; 40 CFR 63, 52, 60 and 81 at 12–26 MB.
  - 9 parts are over 4 MB and get forwarded.
  - FAR Part 52 is 2.6 MB.
- One identifier contains '/' (40 CFR "Appendix I to Part 75 - Optional F - Factor/Fuel Flow Method").

## Content format (nodes.content)
For every node with its own XML DIV (part, subpart, subject group, division, section, appendix,
plus out-of-part appendices) the content is a JSON object:
- `n`: the DIV's N attribute ("" if missing)
- `kind`: "section" or "appendix" for DIV8/DIV9; otherwise `_GROUP_KEYS[TYPE]` or "division"
- `unit`: `_Unit.as_dict()` with no `always` keys, exactly as `_parse_container` renders that DIV.
  - Sections and appendices: `render()`, so nested DIVs are inlined.
  - Groups: the group's own blocks with child DIVs left out.
  - Canonical key order.
- `label`: subject groups only: `group.inline(first_head)`
- `divs`: groups only: child DIV keys in XML document order
- `images`, `pending`, `unparsed`: the unit's counts for `_warnings`

## Flags (nodes.flags)
- 1: the node's own single-scope request can't be rebuilt from the copy, so forward it. Cases:
  - a section or appendix with nested section DIVs (`parse()` would switch to container mode)
  - a group with no section or appendix below it
  - XML DIVs that don't align with structure nodes

## Session log (newest last)
- 2026-10-31: plan approved. Probes above. Worktree created. `scripts/load_ecfr.py record` written.
  Recording of 2026-10-29 started in the background (Title 48 first, then all titles; ~9,700 XML
  requests with the 3 s gap, about 8 h). Recording dir: `deploy/ecfr/.snapshot.nosync/rec-2026-10-29/`
  (`manifest.jsonl`, `titles.json`, `agencies.json`, `structure/`, `parts/title-N/part-X.xml`,
  `appendices/`); log in `record.log`. Resume: rerun the same command, and the manifest skips
  what's done:
  `servers/ecfr-mcp/.venv/bin/python -I scripts/load_ecfr.py record --date 2026-10-29 --out deploy/ecfr/.snapshot.nosync/rec-2026-10-29`
- 2026-10-31: `deploy/ecfr/schema.sql` written.

## Visitor copy drafts (show James in chat before the deploy; not applied yet)
**eCFR `/privacy`** (`deploy/ecfr/src/public-docs.ts`). The effective date becomes the deploy date. Changed lines only; everything else stays as is.
- Short version, IP bullet: "1102tools doesn't log or keep your IP address. For the lookups that still go to eCFR, Cloudflare strips it before your request reaches the 1102tools server."
- Short version, searches bullet: "Your searches aren't logged or saved, and nobody at 1102tools reads them."
- Short version, new bullet after that one: "Most answers, such as the current text of a section, part or FAR definition, come from 1102tools' own copy of the current eCFR, so those lookups are never sent to eCFR. Searches, past dates, version history, corrections and recent changes still go to eCFR when you ask."
- Short version, cache bullet: "For the lookups that go to eCFR, recent public answers stay in the server's memory for up to 24 hours and are then deleted. The cache holds the public answer, not who asked."
- Where your request goes, first bullet replaced by two:
  - "Cloudflare runs the service. For the current text of the regulations (sections, parts, definitions, the table of contents and the agency list), it answers from 1102tools' copy of the Electronic Code of Federal Regulations (ecfr.gov), checked every hour, updated as soon as eCFR publishes, and stored in a Cloudflare database. Nothing is sent to eCFR for these."
  - "For searches, past dates, version history, corrections and recent changes, Cloudflare strips your IP address, location and browser details and passes the request through an encrypted tunnel to a server 1102tools runs, which gets the answer from eCFR. If that server is down, a copy hosted by Cloudflare answers instead."
- What is kept, answer cache bullet: "Answer cache: for the lookups that go to eCFR, public answers are kept for up to 24 hours, ..." (rest unchanged).
- What is kept, new bullet: "The copy of eCFR: public regulation text only. It holds nothing about you or your searches."

**federal-contracting-prompts `tools/build.py`** (llms.txt, /mcp/ecfr, homepage FAQ):
- `FRESHNESS['ecfr']`: "1102tools' copy of the current eCFR, checked every hour and updated as soon as eCFR publishes. Search, past dates, version history, corrections and recent changes come live from eCFR and may be reused for up to 24 hours."
- `llms_help()`, "How the hosted servers run": add eCFR to the copy sentence ("SAM.gov, BLS OEWS, GSA Per Diem, Acquisition.gov and eCFR answer from 1102tools' copy…"), with "eCFR calls eCFR live only for search, past dates, version history, corrections and recent changes." Drop eCFR from the live-API sentence.
- `llms_help()`, Privacy: "SAM.gov, BLS OEWS and Acquisition.gov answer from…" becomes "SAM.gov, BLS OEWS, Acquisition.gov and most eCFR lookups answer from…".
- Repo README "Hosted privacy" stays true as written.
- 2026-10-31: `nodes` changed to a rowid table: Title 48 is 37 MB instead of 58 MB, for 3 row writes per node
  instead of 2. Remote Title 48 measured twice: 30,161 rows under WITHOUT ROWID (then dropped), then **45,247
  rows, 36.9 MB** under the final schema. Projection for all titles: 274,804 nodes × 3 ≈ 830k rows (≈ $0.83)
  and ≈ 1.4 GB, which puts D1 at ≈ 5.2 GB in all (5 GB included).
- 2026-10-31: staging deployed: `ecfr-mcp-staging` at https://ecfr-mcp-staging.1102moderator.workers.dev
  (version 978016dc-da6e-4c2e-8854-caab83ee8040), D1 `ecfr`, forwarding to production. Smoke test: get_latest_date
  and lookup_far_clause from D1 (52.212-4 in 0.18 s); search_cfr and title 2 forwarded and answered.
- 2026-10-31: search side-by-side, first pass (Title 48 FTS5 vs live eCFR search, `.snapshot.nosync/search/`):
  - known-item queries (30 unique headings): ours 29/30 in the top 5, eCFR 27/30
  - 26 natural Title 48 questions: about 5 of 10 top results shared; ours is worse on "small business
    set-aside" and "simplified acquisition threshold", better on "past performance evaluation"
  - local FTS writes ≈ 3.7 rows per section (≈ 0.85M for all titles)

  Verdict so far: keep search_cfr live. Ranking is comparable, not as good on common phrases, and the
  answer can't match eCFR's fields (score, excerpts, starts_on/ends_on, order options, agency and date
  filters, current_only=False). Recheck the 4 non-48 questions once ecfr-all exists.
- 2026-10-31: James asked for the Dell-style cache and multiple copies. Read replication is on for D1 `ecfr`
  (`mode: auto`, same as SAM). The Worker agent is adding SAM's `withSession("first-unconstrained")` reads and a
  Cloudflare answer cache keyed to `meta.version`, kept until the next load and never more than 24 h. The loader
  bumps `meta.version` on every writing run.
  Privacy draft addition, SAM wording adapted. Short version, searches bullet: "Your searches aren't logged or
  saved, apart from a short answer cache, and nobody at 1102tools reads them." What is kept, new bullet: "Copy
  answer cache: answers built from the copy are kept in Cloudflare's cache at the location that answered until the
  copy is next updated, and never more than 24 hours, so a repeat question is answered without querying the
  database again. Entries are filed under a scrambled fingerprint of the request and hold public eCFR text, not
  your IP address or anything that identifies you."
- 2026-10-31: Worker agent added read replication (`withSession("first-unconstrained")`) and the answer cache
  (key = sha256 of release + meta.version + tool + validated args; only D1-built answers; 24 h max).
  15/15 tests pass; parity 438/11/0 with the cache on and off.
  - Staging has a custom domain, `ecfr-staging.1102tools.com`, because the Cache API is a no-op on workers.dev
    (version c514d9db-0882-4dbd-8010-af50df46444b).
  - Wrote a `meta.version` row by hand (2 rows) for Title 48, which was loaded before versions existed.
  - Measured get_cfr_content Part 52 page 3: miss 0.41 s, then hits at 0.15 s and 0.10 s.
- 2026-10-31: configuration settled with James: D1 (+ replicas + edge answer cache) for the copy tools; the
  Dell first for the 5 live tools (warm, persistent 24 h cache), the container only as backup. The container
  sleeps after 2 min and loses its cache, and a Worker passthrough would mean porting the live tools without
  adding capacity, since eCFR pacing caps them wherever they run.
- 2026-10-31: **Shortcut, at James's request.** Stopped the part-by-part recorder after Title 48 (complete),
  Titles 1–4 (complete) and 186 of Title 5's 422 parts. Each remaining part now comes from eCFR's whole-title XML
  (one request per title), with the hierarchy_metadata written by rule: `deploy/ecfr/scripts/derive_parts.py`.
  - Rule, outside Title 48:
    - part: `title-N/part-P`, "N CFR Part P"
    - subpart: `part-P/subpart-S`, "N CFR Part P Subpart S"
    - subject group: `part-P/subject-group-G`, "N CFR Part P[ Subpart S] - <HEAD text>"
    - section: `section-X`, "N CFR X"
    - appendix: `part-P/appendix-A`, "A, Title N"
  - Title 48 is never derived (FAR cross-reference fields).
  - Check on Titles 1–5: 428 real parts, 8,299 DIVs, 0 differences in metadata or in the full parse() answer.
  - Running: whole titles 6–50, plus 4 real sample parts per title (subject groups, appendices, subparts first),
    then the same check.
  - Out-of-part appendices (24 outside Title 48) are logged as 404 "answered live", so they're flagged and forwarded.
- 2026-10-31: **Live comparison, staging vs production** (`compare_live.py`, every tools/call parity case,
  3.5 s pacing): 365 cases, 364 identical, 1 different. The one difference was "lookup: int": staging forwarded a
  not-found section to production and got eCFR's 404 text, while production's own call met a transient eCFR 503.
  Rerun: identical. So 365 of 365 identical, with Title 48 from D1 and everything else forwarded.
- 2026-10-31: Derivation check on the samples (4 real parts per title, 600 parts / 21,301 DIVs in all) found
  eCFR quirks, so the rule gained:
  - an alternate_reference for Title 14 ("FAR") and Title 41 ("FMR"), appendices ", FAR"/", FMR"
  - Title 43's out-of-part section links (`section-3430.3431.0-1`)

  Still different, and not derivable:
  - 12 CFR 192's subject group "Completion of the Offering", which eCFR cites as "…OfferingCompletion of the
    Conversion" (a heading that isn't in the XML)
  - one editorial note in 20 CFR 404 App. 1 to Subpart P, where the whole-title file has "and b." and the part
    answer has "andb."

  Result 598/600. `derive_parts.py write` wrote 8,258 derived parts (manifest `"derived": "whole-title"`).
  `.snapshot.nosync/load_all.sh` then runs a local all-titles build, the reference verification, and the remote
  load in 5 batches (log `load_all.log`).
  The recorder now re-fetches derived entries (`load_ecfr.py` Recorder skips only non-derived ones). Restarted as
  an overnight **audit**: once done, a change-only `build --remote` swaps in eCFR's real part answers (a few rows).
- 2026-10-31 18:49: **All titles loaded into D1** (`load_all.sh`; the 5 batches wrote 182,857 + 182,572 + 150,133 +
  172,024 + 93,032 = 780,618 rows; Title 48 unchanged, 0). Remote: 274,804 nodes, 1,321 chunks, 50 titles rows,
  meta.version set, **1.05 GB**. D1 account total ≈ 4.86 GB of the 5 GB included.
  Rows written for eCFR so far: 30,161 (first Title 48 load, dropped) + 45,247 + 780,618 + 14 ≈ **856k ≈ $0.86**.
  - Local reference verification over all titles: 231,340 sections and appendices, 8,242 parts and 21,856 subparts
    match `parse()`, 0 mismatches.
  - Flagged and forwarded: 2,804 groups with no section below, 56 DIVs with no structure node, 10 parts with no XML.
  - Parity over ecfr-all: 449 cases, 438 identical, 11 documented, 0 unexpected (396 answered from D1, 53 forwarded).
- 2026-10-31: search side-by-side over all titles: mean top-10 overlap with eCFR 5.4. Known items: ours 29/30,
  eCFR 27/30. An FTS5 index over all titles is 1.44M row changes locally (≈ $1.44) and ≈ 1 GB, which would put D1
  over 5 GB. **Recommendation: keep search_cfr live** (its answer fields, filters and order options can't match
  from our index; rankings are comparable, not better).
- 2026-10-31 19:2x: **Live comparison with all titles loaded: 365 of 365 identical** (`compare-live-all.log`).
  During the runs eCFR sent 2 × 429 to the random-500 recorder (retried fine). The Mac and the Dell share the home
  IP, so I stopped the audit recorder: one direct eCFR stream at a time from now on. Run the audit later, slower,
  overnight.
- 2026-10-31: **Speed** (`scripts/time_live.py`, from the Mac, each call twice):
  - Common clauses and sections: new 0.04–0.10 s vs production 0.08–0.29 s.
  - FAR Part 52 page: 0.18 / 0.07 s vs 0.55 / 0.64 s.
  - Rarely asked sections (production cache miss): new 0.08–0.16 s vs production 1.56–3.00 s.
  - Search is the same path on both: staging forwarded first, so it paid production's uncached 4.7 s.
  - Median first call: new 0.07 s vs production 0.14 s.
- 2026-10-31 19:3x: **Parity with 500 random sections from all titles** (live per-section eCFR answers vs the D1 copy,
  derived metadata included): 949 cases, 938 identical, 11 documented, **0 unexpected**; 896 answered from D1.
  eCFR still at 2026-10-29 (no title changed), so the copy is current. Committed on the branch (1a80158), not pushed.

## Switch checklist (when James says go)
1. Show James the privacy and freshness drafts above; apply the approved wording to `public-docs.ts` (+ prompts
   repo FRESHNESS / llms_help after the switch).
2. Push the branch, open the PR (CI: ecfr-hosted-tests.yml), merge, so `ecfr-load.yml` (hourly refresh, daily
   verify) runs from main with `CLOUDFLARE_D1_TOKEN` (environment sam-data-load). Run one refresh by hand first.
3. Worker-only production deploy keeping the live container image and the Dell's RELEASE_SHA:
   - `configure_hosted_image.py ecfr <live sha>`
   - `npx wrangler deployments list --env production` (record the rollback version here)
   - `npx wrangler deploy --config wrangler.release.json --env production --containers-rollout=none`
4. Verify: verify_hosted_release.py, check_hosted_health.py, compare_live.py staging-style against the pre-switch
   answers, a listen test, and a D1 analytics rowsWritten check.
5. Later: the slow overnight audit of derived parts (one stream, ≥ 6 s gap); delete the staging Worker and its
   domain once production has run cleanly for a week.
