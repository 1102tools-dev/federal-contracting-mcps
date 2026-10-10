# October 10, 2026 MCP content audit and release record

**Package, Cloudflare and all-five Dell release checks passed. Website publication and final round closure remain pending.** This record distinguishes executed checks, collected tests and source limitations. The subsequent zero-new-P0/P1/P2 audit has not started. Evidence paths are relative to `Artifacts/mcp-e2e-20261010/`.

## Scope and findings ledger

The current goal covers SAM.gov, USAspending, GSA CALC+, BLS OEWS, GSA Per Diem, eCFR, Federal Register and Regulations.gov. Acquisition.gov is explicitly excluded from this goal and all future rounds; its already-started work is a separate appendix. The next content round starts only on coordinator dispatch. Release/regression checks do not constitute a new broad content audit or establish the zero-new-P0/P1/P2 stopping condition.

The authoritative `coordinator/release-state.json` ledger records **36 newly confirmed findings: P0=0, P1=2, P2=21, P3=13** in the eight-server goal. This includes development tooling and historical first-round validation findings; they are not all ordinary-user content defects. Historical audit totals are not added. Individual server evidence accounts for 35; the shared privacy correction is counted once as the remaining P2. Four high npm advisory entries in one deployment dependency chain count as one toolchain finding for each affected owner, not four defects.

| Owner | P1 / P2 / P3 | Corrected behavior and evidence | Source status / final destination status |
|---|---:|---|---|
| SAM.gov | 0 / 2 / 2 | Own-property dispatch/group checks; inverted-date recovery; stable relevance tie ordering; patched Wrangler. `sam-gov/FINDINGS.md`, `summary.json`, `source-parity.json` | All four fixed and public verified; distinct unchanged Python package verified with credentialed live coverage unavailable. |
| USAspending | 0 / 4 / 2 | Recent DoD/USACE lag disclosure; USACE scope; distinguish File C/IDV coverage; submission calendar cannot prove agency completion; fiscal timeline labels; patched tooling. `usaspending/FINDINGS.md`, `semantic-verification.txt` | All six fixed and verified in published1.0.15: fresh installed CLI17, public73 questions/all55 tools and3 further DoD/USACE followups passed. |
| GSA CALC+ | 1 / 2 / 1 | Mixed vendor/contract/title population no longer supports a comparable-title verdict; counts retain lower bounds; undefined zero-variance statistics remain null; patched tooling. `gsa-calc/findings.json` | All four fixed and verified in published1.0.14: fresh installed CLI,19 regressions,28 local/public cases and19 direct source comparisons passed. |
| BLS OEWS | 0 / 3 / 1 | Preserve hourly-only musicians/actors benchmarks without fabricated annual salaries; actionable national-ratio scope guidance; deliberate errors survive newly resolved MCP 2.3; patched tooling. `bls-oews/checkpoint.md`, `sdk-corrective-finding.json` | Numeric corrections verified in published 1.1.2. CLI recovery guidance fixed and verified in actual freshly installed published1.1.3 and public endpoint. |
| GSA Per Diem | 0 / 2 / 4 | Split-month trips calculate M&IE once; known city/county contradictions rejected; complete ZIP+4 validation; patched tooling; comparison source attribution; keyless bundled city+county setup guidance. `gsa-perdiem/FINDINGS.md`, `METADATA-FOLLOWUP.md` | All six fixed and verified in published1.2.3: fresh installed CLI28,12 installed regressions,28 public cases, actual corrected descriptions and source parity passed. |
| eCFR | 1 / 2 / 2 | Unavailable snapshot dates cannot imply a removed section; reject cross-title citation conflicts with recovery; changes-only removal summaries omit full text; patched tooling; recovery survives fresh MCP 2.3. `ecfr/CHECKPOINT.md`, `FINAL.json` | First-release hosted content verified; fresh 1.1.1 CLI lost recovery details. Published 1.1.2 verifies that correction, CLI guidance and all13 public tools; physical Dell takeover passed. |
| Federal Register | 0 / 2 / 1 | Explicit partial comment scans and FAR lower-bound metadata; API archive start distinguished from first publication in 1936; patched tooling. `federal-register/checkpoint.json`, `release-status.json` | All three fixed; actual PyPI and public 1.0.14 verified. The bounded scan remains a disclosed source limitation, not a partially fixed defect. |
| Regulations.gov | 0 / 3 / 0 | Workflow wrappers retain past-end/last-page recovery; failed organization lookup leaves organization unknown; patched tooling. `regulations/final.json` | All three fixed and actual PyPI/public 2.0.4 verified. Direct-source live checks remain quota/credential limited. |
| Shared privacy | 0 / 1 / 0 | Replace claims of no stored results/global hashed cache keys with accurate temporary bounded-memory public-response caching and no retained query/result logs. Current reviewed README and service privacy copy; coordinator ledger | Root README corrected in merged PR93. Final website publication remains pending. |

All35 server findings are fully fixed and final-package/public-content verified; none are partially fixed or unresolved. The shared P2 documentation correction is source-complete; its website publication remains pending, so it is not yet counted as fully published. Automatic directory review outcomes are not observable from public tools/list; deployed correct metadata does not prove directory propagation.

## Versions, PRs and immutable source identities

Baseline checkout: `2a1feb0ced5c4012b449a7f2a5373d09b8ed9f86`. First unified release `v1.0.33`: `b379d69b3ac505d5f1f1ae255896acb2b5f0d866`, workflow `38062697011`, success. The final five scoped tags use the same reviewed source **`7754923b8c77e51022e2c561856fd6ccf4eab874`**. Documentation-only PR91 does not require a Federal Register deployment or package bump. Unchanged services retain their already verified identities.

| Package / service | Baseline → first published → final target | Relevant merged PRs | Required final runtime identity |
|---|---|---|---|
| SAM Python / separate mirror | Python 1.0.13 unchanged; mirror 1.0.0→1.0.1 | [76](https://github.com/1102tools-dev/federal-contracting-mcps/pull/76) | Mirror `8ead8d6dbacd9db4dc89618852a31c54bb9ed18b`, deployment `0c63291c-4f65-4cdb-a962-5ee8b79e9554`; no new scoped release |
| USAspending | 1.0.13→1.0.14→1.0.15 | [81](https://github.com/1102tools-dev/federal-contracting-mcps/pull/81), [86](https://github.com/1102tools-dev/federal-contracting-mcps/pull/86) | Final reviewed SHA above |
| CALC+ | 1.0.12→1.0.13→1.0.14 | [79](https://github.com/1102tools-dev/federal-contracting-mcps/pull/79), [84](https://github.com/1102tools-dev/federal-contracting-mcps/pull/84) | Final reviewed SHA above |
| BLS OEWS | 1.1.1→1.1.2→1.1.3 | [74](https://github.com/1102tools-dev/federal-contracting-mcps/pull/74), [87](https://github.com/1102tools-dev/federal-contracting-mcps/pull/87) | Final reviewed SHA above |
| GSA Per Diem | 1.2.1→1.2.2→1.2.3 | [78](https://github.com/1102tools-dev/federal-contracting-mcps/pull/78), [82](https://github.com/1102tools-dev/federal-contracting-mcps/pull/82), [85](https://github.com/1102tools-dev/federal-contracting-mcps/pull/85) | Final reviewed SHA above |
| eCFR | 1.1.0→1.1.1→1.1.2 | [77](https://github.com/1102tools-dev/federal-contracting-mcps/pull/77), [88](https://github.com/1102tools-dev/federal-contracting-mcps/pull/88) | Final reviewed SHA above |
| Federal Register | 1.0.13→1.0.14 unchanged thereafter | [72](https://github.com/1102tools-dev/federal-contracting-mcps/pull/72), docs [91](https://github.com/1102tools-dev/federal-contracting-mcps/pull/91) | First unified SHA b379d69… |
| Regulations.gov | 2.0.3→2.0.4 unchanged thereafter | [73](https://github.com/1102tools-dev/federal-contracting-mcps/pull/73) | First unified SHA b379d69… |

Shared preflight PR80 and final documentation PRs are coordinator changes; they do not add duplicate server findings. `coordinator/release-state.json` retains original reviewed heads and merge SHAs.

## Measured regression and source/content evidence

The coordinator `final-collection/*.log` files independently measure **6,024 collected package tests across nine packages**, including Acquisition's 255; the eight-goal-server subtotal is **5,769**. Collected is not executed. Live skips are not passes. Native Worker/parity checks are additional lanes and are not added to this Python collected total.

| Server | Current collected | Latest complete offline lane: pass / skip | Separate meaningful execution |
|---|---:|---:|---|
| SAM | 1,155 | 781 / 374 | 27 Worker tests; 12 loader tests; official CSV parity 36 cases; public 48 original/followup calls and five error regressions; 35 unchanged valid responses match. |
| USAspending | 2,297 | 1,918 / 379 | 73 before/after official-source cases and hosted calls cover all 55 tools; financial results retained exactly, modification sums match detail to the cent; first published CLI 17 originals/followups. |
| CALC+ | 433 | 312 / 121 | 28 ordinary question cases/all eight tools; separately 30 live content tests; six Worker tests; 19 new before failures. |
| BLS | 295 | 294 / 1 under both SDK 2.0 and 2.3 | Live official series parity passes; 29 Worker tests; 222 Python/Worker cases (211 identical, 11 documented differences, zero unexpected). Candidate real CLI ratio→Virginia completion passes. |
| Per Diem | 576 | 309 / 267 | 28 Worker tests; 25 hosted original cases; 1,368 parity calls (1,361 identical, seven documented differences); 17 official source hashes match; independently parsed 40,426 ZIPs/295 destinations match bundle. This is not a 40,426-call hosted test. |
| eCFR | 441 | 323 / 118 under both SDK 2.0 and 2.3 | All 13 tools/19 workflows; all 118 live-gated tests passed in an earlier 432-test full run before final offline additions; final source workflow checks passed. Do not call the final 441-test lane a full live run. |
| Federal Register | 286 | 181 / 105 | Full final live-enabled suite 286 passed; 12 ordinary workflows/all eight tools; four new regressions fail before/pass after and pass against installed PyPI package. |
| Regulations.gov | 286 | 167 / 119 | 33 hosted calls/all nine tools; seven before-fail/after-pass regressions; actual public six final content originals/followups; actual installed CLI initialize/catalog/access status. |

Authoritative source examples: Federal Register specific Oct10–13 deadline search finds `2026-19904` omitted by the bounded broad scan; eCFR Title48 latest Oct7 snapshot and section history disprove false FAR15.305 removal; BLS current series/footnotes preserve musicians $60.46 hourly mean and $47.80 median; Per Diem official FY2027 files establish five-day M&IE $414 versus incorrectly added $460; USAspending official reporting documentation establishes procurement delay and File C linkage scope; CALC official API rows prove mixed-field populations; Regulations fresh Federal Register cross-references verify selected deadlines/withdrawal while DEMO_KEY source access returns HTTP429. Exact original questions, wrong answers, expected corrections and authority links remain in each owner evidence record.

Npm audit remediation uses Wrangler 4.149.0 and records zero advisories after upgrades. Typechecks and Worker bundle dry-runs passed. Local Docker CLI was unavailable; successful first-release CI image builds clear that local container-build gap for the first publication. Final scoped releases must pass their own build/deployment gates.

## Actual completed destinations and pending final slots

First-release actual verification is retained, not reused as evidence of later targets:

- Federal Register PyPI1.0.14: fresh official by-name install, actual installed stdio CLI/catalog8, fixed regressions and published payload parity pass; public all eight tools/original broad scan plus FAR/deadline followups pass at b379d69. `federal-register/release-status.json`.
- Regulations PyPI2.0.4: fresh install, actual stdio CLI/catalog9/access status pass; installed regressions and public original/followups pass at b379d69. Direct keyed API content is not claimed. `regulations/final.json`, `actual-pypi-cli-stdio.json`.
- SAM Python1.0.13: fresh PyPI installed CLI/catalog20 and missing-key guidance verified. Hosted mirror1.0.1 all four tools and official CSV parity pass at its own SHA; loader38061635411 succeeded, Oct10 file loaded14:57:32Z, 64,417 rows/46,083 latest. `sam-gov/summary.json`, `post-reload-data-status.json`.
- Initial published USA1.0.14, CALC1.0.13, Per Diem1.2.2, eCFR1.1.1 and BLS1.1.2 checks are recorded in owner evidence. eCFR/BLS fresh MCP2.3 guidance failures are explicitly superseded by reviewed corrective candidates, not retroactively labeled passes.
- All five Dell origins were verified against b379d69 for first release: public GET/POST origin headers plus health/version and physical origin checks. `coordinator/dell-v1.0.33-verified.json`. Final checks require a per-service expected identity, not one global SHA.

| Final scoped release | Workflow / conclusion | Fresh official PyPI actual CLI, originals/followups | Public version/SHA/content/metadata | Applicable Dell origin | Registry / release summary |
|---|---|---|---|---|---|
| ecfr/v1.1.2 | [38065011229](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065011229), success | Fresh by-name PyPI install/MCP2.3; actual CLI5 originals/followups; published suite323 passed/118 live skipped | 18 originals/followups, all13 tools; SHA/version/contract passed | Passed | Passed |
| bls-oews/v1.1.3 | [38065339718](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065339718), success | Fresh official published PyPI wheel/MCP2.3; actual CLI13 calls/all8 tools | 13 originals/followups/all8 tools; SHA/version/contract passed | Native Worker; no Dell origin configured | Passed |
| usaspending/v1.0.15 | [38065592978](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065592978), success | Fresh official PyPI installed CLI17/all55 tools | 73 questions/all55 tools +3 followups; exact SHA/version/contract passed | Passed | Passed |
| gsa-calc/v1.0.14 | [38065833808](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065833808), success | Fresh official PyPI CLI,19 installed regressions | 28 local/public cases and19 direct source comparisons;8 tools, exact SHA/version/contract passed | Passed | Passed |
| gsa-perdiem/v1.2.3 | [38066135863](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38066135863), attempt2 success | Fresh by-name official PyPI CLI28,12 installed regressions | 28 public cases/all7 tools, exact SHA/version/descriptions/source attribution passed | Native Worker/D1; no Dell origin configured | Passed after propagation retry |

All five must bind to7754923b8c77e51022e2c561856fd6ccf4eab874. Unchanged Federal Register and Regulations must retain b379d69; SAM must retain its independent mirror SHA. Complete directory definitions remain subject to OpenAI automatic continuous checks; [current official maintenance rules](https://developers.openai.com/plugins/deploy/app-review#how-published-mcp-metadata-versions-work) require no manual republication solely for changed descriptions, but plugin info/skills and origin changes have different requirements. Keep old definitions compatible while checks run.

**Shared documentation/site slot — PENDING:** root to insert repository docs commit, website source/build commit, public URL/version/count comparison, deployment conclusion and final live copy evidence. Candidate counts must be6,024 overall, not6,022 or6,021; FR rounds9; Per Diem city+county keyless; privacy must disclose temporary bounded-memory caching. Do not infer public-site success from a local generated build.

**Round closure slot — PENDING:** root to fill five workflow IDs/conclusions, final owner evidence links, final destination matrix and website result before declaring this round closed. A subsequent complete eight-server ordinary-content round with zero new P0/P1/P2 is still required by the user’s loop instruction; this draft makes no claim that condition is satisfied.

## Source limitations and enhancements

These remain honest limits, distinct from unresolved confirmed defects: SAM daily active-only file lacks authoritative amendment parent chains/archive/attachments and Python live operations require credentials; USAspending lag, account-linkage gaps and unsupported IDV time filters; CALC mixed-field keyword scope, capped/approximate aggregations and unsupported worksite filter; BLS May2025-only bundle and unpublished/top-coded estimates; Per Diem CONUS scope, Census2020 geography and itinerary/date-aware pricing enhancement; eCFR snapshot lag/2017-onward history; Federal Register500-row bounded scans/1994-onward API archive; Regulations quota/credentials, posted-versus-received counts and attachment URLs without extraction. No fabricated source totals or blanket source-completeness claims are made.

## Separate Acquisition.gov appendix — excluded from goal acceptance

The all-current-round coordinator ledger has41 findings (P0=0/P1=3/P2=23/P3=15). Subtracting the excluded Acquisition track's five (P1=1/P2=2/P3=2) yields the eight-server36 above. Acquisition255 collected tests contribute only to the repository-wide6,024 total. Published1.0.10 package/CLI evidence and first b379d69 service checks exist in `acquisition/final-published-cli-validation.json` and `final-published-wheel-validation.json`. Its parser4 full reload proceeds separately; **root to fill current reload result**, without making it a blocker for the eight-server goal or future loop. No new Acquisition scoped tag belongs to the five final releases above.

## Per-owner fix counts at package/deployment verification

| Owner | P0 | P1 | P2 | P3 | Fully fixed | Partially fixed | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| SAM.gov | 0 | 0 | 2 | 2 | 4 | 0 | 0 |
| USAspending | 0 | 0 | 4 | 2 | 6 | 0 | 0 |
| eCFR | 0 | 1 | 2 | 2 | 5 | 0 | 0 |
| Federal Register | 0 | 0 | 2 | 1 | 3 | 0 | 0 |
| Regulations.gov | 0 | 0 | 3 | 0 | 3 | 0 | 0 |
| GSA CALC+ | 0 | 1 | 2 | 1 | 4 | 0 | 0 |
| GSA Per Diem | 0 | 0 | 2 | 4 | 6 | 0 | 0 |
| BLS OEWS | 0 | 0 | 3 | 1 | 4 | 0 | 0 |
| Shared documentation | 0 | 0 | 1 | 0 | 0 | 1 (website pending) | 0 |

Final public metadata independently matches all112 hosted tool definitions across eight services. Allfive Dell checks passed: USA1.0.15/eCFR1.1.2/CALC1.0.14 at7754923; unchanged FR1.0.14/Regulations2.0.4 atb379d69. Public GET and POST report origin backend; physical origin health and direct container initialize match each expected tag/version/SHA. Evidence: `coordinator/eight-server-final-contracts.json`, `coordinator/dell-corrective-7754923-verified.json`.

PerDiem first registry attempt failed because PyPI1.2.3 was not yet visible to the registry. After official metadata/index propagation, only failed jobs were rerun on the same workflow/tag; attempt2 completed successfully, without another package publication or overlapping release. SAM nightly-file reload passed; PerDiem/BLS source bundles are unchanged, so no data reload was required for these corrective releases.
