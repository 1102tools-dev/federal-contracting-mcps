# October 10, 2026 MCP content audit and release record

**Rounds 1–3 are closed: 53 cumulative findings fully fixed and live verified. Round 4 content coverage is complete across all eight servers, with nine new findings (0 P0, 0 P1, 5 P2, 4 P3); all nine fixes are merged and all scoped releases have succeeded.** Final eight-service production identity/112-tool contract checks, all16 official PyPI artifacts and all-five Dell/45 backend checks passed. SAM Python1.0.14, CALC1.0.16 and eCFR1.1.6 completed actual published content acceptance; USAspending1.0.20 completed150CLI/150public questions plus six guided workflows; independent original/recovery checks also passed. Actual website publication passed; this final coordinator merge and served-file check complete documentation closure. Round5 starts only after Round4 closes. This record distinguishes executed checks, collected tests and source limitations. Evidence paths are relative to `Artifacts/mcp-e2e-20261010/`.

## Scope and findings ledger

The current goal covers SAM.gov, USAspending, GSA CALC+, BLS OEWS, GSA Per Diem, eCFR, Federal Register and Regulations.gov. Acquisition.gov is explicitly excluded from this goal and all future rounds; its already-started work is a separate appendix. The next content round starts only on coordinator dispatch. Release/regression checks do not constitute a new broad content audit or establish the zero-new-P0/P1/P2 stopping condition.

The authoritative `coordinator/release-state.json` ledger records **36 newly confirmed findings: P0=0, P1=2, P2=21, P3=13** in the eight-server goal. This includes development tooling and historical first-round validation findings; they are not all ordinary-user content defects. Historical audit totals are not added. Individual server evidence accounts for 35; the shared privacy correction is counted once as the remaining P2. Four high npm advisory entries in one deployment dependency chain count as one toolchain finding for each affected owner, not four defects.

| Owner | P1 / P2 / P3 | Corrected behavior and evidence | Source status / final destination status |
|---|---:|---|---|
| SAM.gov | 0 / 2 / 2 | Own-property dispatch/group checks; inverted-date recovery; stable relevance tie ordering; patched Wrangler. `sam-gov/FINDINGS.md`, `summary.json`, `source-parity.json` | All four fixed and public verified; distinct unchanged Python package verified with credentialed live coverage unavailable. |
| USAspending | 0 / 4 / 2 | Recent DoD/USACE lag disclosure; USACE scope; distinguish File C/IDV coverage; submission calendar cannot prove agency completion; fiscal timeline labels; patched tooling. `usaspending/FINDINGS.md`, `semantic-verification.txt` | All six fixed and verified in published 1.0.15: fresh installed CLI 17, public 73 questions/all 55 tools and3 further DoD/USACE followups passed. |
| GSA CALC+ | 1 / 2 / 1 | Mixed vendor/contract/title population no longer supports a comparable-title verdict; counts retain lower bounds; undefined zero-variance statistics remain null; patched tooling. `gsa-calc/findings.json` | All four fixed and verified in published 1.0.14: fresh installed CLI,19 regressions,28 local/public cases and19 direct source comparisons passed. |
| BLS OEWS | 0 / 3 / 1 | Preserve hourly-only musicians/actors benchmarks without fabricated annual salaries; actionable national-ratio scope guidance; deliberate errors survive newly resolved MCP 2.3; patched tooling. `bls-oews/checkpoint.md`, `sdk-corrective-finding.json` | Numeric corrections verified in published 1.1.2. CLI recovery guidance fixed and verified in actual freshly installed published 1.1.3 and public endpoint. |
| GSA Per Diem | 0 / 2 / 4 | Split-month trips calculate M&IE once; known city/county contradictions rejected; complete ZIP+4 validation; patched tooling; comparison source attribution; keyless bundled city+county setup guidance. `gsa-perdiem/FINDINGS.md`, `METADATA-FOLLOWUP.md` | All six fixed and verified in published 1.2.3: fresh installed CLI 28,12 installed regressions,28 public cases, actual corrected descriptions and source parity passed. |
| eCFR | 1 / 2 / 2 | Unavailable snapshot dates cannot imply a removed section; reject cross-title citation conflicts with recovery; changes-only removal summaries omit full text; patched tooling; recovery survives fresh MCP 2.3. `ecfr/CHECKPOINT.md`, `ecfr/final-1.1.2-7754923/FINAL.json` | First-release hosted content verified; fresh 1.1.1 CLI lost recovery details. Published 1.1.2 verifies that correction, CLI guidance and all 13 public tools; physical Dell takeover passed. |
| Federal Register | 0 / 2 / 1 | Explicit partial comment scans and FAR lower-bound metadata; API archive start distinguished from first publication in 1936; patched tooling. `federal-register/checkpoint.json`, `release-status.json` | All three fixed; actual PyPI and public 1.0.14 verified. The bounded scan remains a disclosed source limitation, not a partially fixed defect. |
| Regulations.gov | 0 / 3 / 0 | Workflow wrappers retain past-end/last-page recovery; failed organization lookup leaves organization unknown; patched tooling. `regulations/final.json` | All three fixed and actual PyPI/public 2.0.4 verified. Direct-source live checks remain quota/credential limited. |
| Shared privacy | 0 / 1 / 0 | Replace claims of no stored results/global hashed cache keys with accurate temporary bounded memory public-response caching and no retained query/result logs. Current reviewed README and service privacy copy; coordinator ledger | Root README corrected in merged PR93; website source PR1 and deployment PR3 merged, published and verified. |

All 36 findings, comprising 35 server findings and one shared documentation correction, are fully fixed and published verified; none are partially fixed or unresolved. Automatic directory review outcomes are not observable from public tools/list; deployed correct metadata does not prove directory propagation.

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

Npm audit remediation uses Wrangler 4.149.0 and records zero advisories after upgrades. Typechecks and Worker bundle dry-runs passed. Local Docker CLI was unavailable; successful first-release CI image builds clear that local container-build gap for the first publication. All five final scoped releases passed their own build/deployment gates.

## Actual completed destinations

First-release actual verification is retained, not reused as evidence of later targets:

- Federal Register PyPI1.0.14: fresh official by-name install, actual installed stdio CLI/catalog8, fixed regressions and published payload parity pass; public all eight tools/original broad scan plus FAR/deadline followups pass at b379d69. `federal-register/release-status.json`.
- Regulations PyPI2.0.4: fresh install, actual stdio CLI/catalog9/access status pass; installed regressions and public original/followups pass at b379d69. Direct keyed API content is not claimed. `regulations/final.json`, `actual-pypi-cli-stdio.json`.
- SAM Python1.0.13: fresh PyPI installed CLI/catalog20 and missing-key guidance verified. Hosted mirror1.0.1 all four tools and official CSV parity pass at its own SHA; loader38061635411 succeeded, Oct10 file loaded14:57:32Z, 64,417 rows/46,083 latest. `sam-gov/summary.json`, `post-reload-data-status.json`.
- Initial published USA1.0.14, CALC1.0.13, Per Diem1.2.2, eCFR1.1.1 and BLS1.1.2 checks are recorded in owner evidence. eCFR/BLS fresh MCP2.3 guidance failures are explicitly superseded by verified published corrective releases, not retroactively labeled passes.
- All five Dell origins were verified against b379d69 for first release: public GET/POST origin headers plus health/version and physical origin checks. `coordinator/dell-v1.0.33-verified.json`. Final checks passed against each service expected identity rather than one global SHA.

| Final scoped release | Workflow / conclusion | Fresh official PyPI actual CLI, originals/followups | Public version/SHA/content/metadata | Applicable Dell origin | Registry / release summary |
|---|---|---|---|---|---|
| ecfr/v1.1.2 | [38065011229](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065011229), success | Fresh by-name PyPI install/MCP2.3; actual CLI5 originals/followups; published suite323 passed/118 live skipped | 18 originals/followups, all 13 tools; SHA/version/contract passed | Passed | Passed |
| bls-oews/v1.1.3 | [38065339718](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065339718), success | Fresh official published PyPI wheel/MCP2.3; actual CLI13 calls/all 8 tools | 13 originals/followups/all 8 tools; SHA/version/contract passed | Native Worker; no Dell origin configured | Passed |
| usaspending/v1.0.15 | [38065592978](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065592978), success | Fresh official PyPI installed catalog55 +17 CLI calls | 73 questions/all 55 tools +3 followups; exact SHA/version/contract passed | Passed | Passed |
| gsa-calc/v1.0.14 | [38065833808](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38065833808), success | Fresh official PyPI CLI,19 installed regressions | 28 local/public cases and19 direct source comparisons;8 tools, exact SHA/version/contract passed | Passed | Passed |
| gsa-perdiem/v1.2.3 | [38066135863](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38066135863), attempt2 success | Fresh by-name official PyPI CLI 28,12 installed regressions | 28 public cases/all 7 tools, exact SHA/version/descriptions/source attribution passed | Native Worker/D1; no Dell origin configured | Passed after propagation retry |

All five bind to7754923b8c77e51022e2c561856fd6ccf4eab874. Unchanged Federal Register and Regulations retain b379d69; SAM retains its independent mirror SHA. Complete directory definitions remain subject to OpenAI automatic continuous checks; [current official maintenance rules](https://developers.openai.com/plugins/deploy/app-review#how-published-mcp-metadata-versions-work) require no manual republication solely for changed descriptions, but plugin info/skills and origin changes have different requirements. Keep old definitions compatible while checks run.

**Published documentation and website — PASSED:** repository README changes and release record merged in [PR93](https://github.com/1102tools-dev/federal-contracting-mcps/pull/93) and [PR96](https://github.com/1102tools-dev/federal-contracting-mcps/pull/96). Website [source PR1](https://github.com/1102tools-dev/federal-contracting-prompts/pull/1) merged at `5d0f56836bdfca3fbd65a4c77c64a9b0b7438544`; deployment snapshot [PR3](https://github.com/1102tools-dev/1102tools-deploy/pull/3) merged at `3c7beea76e3fa8027c23ffda9735666d6518006f`. Cloudflare Pages deployment [6213f0a5](https://6213f0a5.1102tools.pages.dev) succeeded. [1102tools.com](https://1102tools.com) passed published-byte checks for all 49 served assets (HTML comparison removes only Cloudflare-injected analytics) plus source/deployment checks for two configuration files; four additional live copy checks passed. Actual browser verification confirmed current versions, 6,024 **collected** tests and the dated release link. The 57 prompts and 15-page PDF remain unchanged. Evidence: `coordinator/website-public-all-assets.json`, `coordinator/website-final-copy-proof.json`.

**Round 1 closure — COMPLETE:** final owner evidence, all five scoped workflows, eight package/public destination matrices, all five Dell origins and website publication have passed. A subsequent complete eight-server ordinary-content round with zero new P0/P1/P2 is still required by the user's loop instruction; this record makes no claim that condition is satisfied. Acquisition.gov remains excluded.

## Source limitations and enhancements

These remain honest limits, distinct from unresolved confirmed defects: SAM daily active-only file lacks authoritative amendment parent chains/archive/attachments and Python live operations require credentials; USAspending lag, account-linkage gaps and unsupported IDV time filters; CALC mixed-field keyword scope, capped/approximate aggregations and unsupported worksite filter; BLS May2025-only bundle and unpublished/top-coded estimates; Per Diem CONUS scope, Census2020 geography and itinerary/date-aware pricing enhancement; eCFR snapshot lag/2017-onward history; Federal Register500-row bounded scans/1994-onward API archive; Regulations quota/credentials, posted-versus-received counts and attachment URLs without extraction. No fabricated source totals or blanket source-completeness claims are made.

## Separate Acquisition.gov appendix — excluded from goal acceptance

The all-current-round coordinator ledger has41 findings (P0=0/P1=3/P2=23/P3=15). Subtracting the excluded Acquisition track's five (P1=1/P2=2/P3=2) yields the eight-server36 above. Acquisition255 collected tests contribute only to the repository-wide6,024 total. Published1.0.10 package/CLI evidence and first b379d69 service checks exist in `acquisition/final-published-cli-validation.json` and `final-published-wheel-validation.json`. Its parser4 full reload proceeds separately; completed at 16:26:52 UTC: loader [38062661329](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38062661329) atomically activated snapshot 6; all 1,389 successful PDFs of 1,401 sources use parser `1.0.10+4`, with zero old parser rows or mismatches. Twelve posted-PDF fetch failures remain source limitations. Actual published package/CLI and six final public originals/followups passed, without making it a blocker for the eight-server goal or future loop. No new Acquisition scoped tag belongs to the five final releases above.

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
| Shared documentation | 0 | 0 | 1 | 0 | 1 | 0 | 0 |

Final public metadata independently matches all112 hosted tool definitions across eight services. Allfive Dell checks passed: USA1.0.15/eCFR1.1.2/CALC1.0.14 at7754923; unchanged FR1.0.14/Regulations2.0.4 atb379d69. Public GET and POST report origin backend; physical origin health and direct container initialize match each expected tag/version/SHA. Evidence: `coordinator/eight-server-final-contracts.json`, `coordinator/dell-corrective-7754923-verified.json`.

PerDiem first registry attempt failed because PyPI1.2.3 was not yet visible to the registry. After official metadata/index propagation, only failed jobs were rerun on the same workflow/tag; attempt2 completed successfully, without another package publication or overlapping release. SAM nightly-file reload passed; PerDiem/BLS source bundles are unchanged, so no data reload was required for these corrective releases.

Final corrective package evidence: `ecfr/final-1.1.2-7754923/FINAL.json`; `bls-oews/final-113-completion.json`; `usaspending/final-verification-1.0.15.json`; `gsa-calc/published-1.0.14/published-verification.json`; `gsa-perdiem/release123-final.json`. USA catalog coverage55 and17 actual CLI calls are distinct from its73 public calls across all 55 tools.

## Sequential content loop — round 2 (final publication and closure)

All eight owners completed another comprehensive audit using ordinary and power-user content questions, useful follow-ups and primary-source comparisons. No adversarial, malformed-input or structure campaign was run. Independent reviews completed for every owner. **Seven newly confirmed findings: P0=0, P1=0, P2=5, P3=2.** Because new P2 issues were found, this round does not satisfy the stopping condition. Round 3 starts only after every round-2 release, destination and documentation gate passes.

| Server | Real content questions / follow-ups | New P0 | New P1 | New P2 | New P3 | Correction / evidence |
|---|---:|---:|---:|---:|---:|---|
| SAM.gov mirror | 87 + status | 0 | 0 | 0 | 1 | Prior-year active notices remain searchable; status no longer excludes all previous fiscal years. Fresh official CSV supports 87 comparisons and 390 returned-row checks. PR98; mirror1.0.2 live verified. Python1.0.13 unchanged; 19 keyed workflow questions were not executed without credentials. |
| USAspending | 127 | 0 | 0 | 1 | 1 | True fiscal-year new-award counts aggregate source fiscal quarters, whose exact unique award counts are additive; monthly/quarterly values and messages remain unchanged. Recipient follow-ups use discovered parent UEI rather than a recipient hash. PR101; package1.0.16 published after successful same-tag rollout retry; 127 actual fresh installed CLI questions plus11 follow-ups and127 actual public questions plus11 follow-ups passed across all55 tools. Fresh official fiscal-quarter cross-foot and217-child parent-UEI source comparisons passed. |
| eCFR | 70 | 0 | 0 | 3 | 0 | COR definition recognizes ordinary nonpossessive wording; historical text/history hints retain title/chapter scope; correction searches match all requested fields in the same reference. PR100/105; published1.1.4 verified:73 fresh installed CLI calls,70 public calls,50 current primary comparisons plusfive corrected-original source checks,13-tool contracts and12-module payload parity passed. Actual published offline suite331 passed/118 skipped/449 collected. |
| BLS OEWS | 46 | 0 | 0 | 1 | 0 | Existing unpublished cells use actual BLS footnotes and actionable alternate measures instead of suggesting absent/retired occupations; topcoded wage floors remain disclosed. PR99; published1.1.4 verified with46 fresh installed CLI questions and46 public questions, unchanged eight-tool contracts, matching wheel/sdist hashes and release SHA. |
| Federal Register | 49 valid calls / 45 completed comparisons | 0 | 0 | 0 | 0 | Eight tools covered; 45 actual fresh installed CLI answers match public answers; four official texts and source semantics verified. Caller/source-harness corrections are documented, not product findings. |
| Regulations.gov | 62 | 0 | 0 | 0 | 0 | Nine tools; 60 primary FR JSON records plus two full texts support 88 comparisons. Direct keyed API parity remains quota/credential limited. |
| GSA CALC+ | 123 | 0 | 0 | 0 | 0 | Eight tools; ten labor domains and six qualified exact-title annual-cost workflows; 2,521 source/workflow assertions. Approximate percentile changes and tied sort boundaries are source variations, not identical-response passes. |
| GSA Per Diem | 59 | 0 | 0 | 0 | 0 | Seven tools; 54 official-source comparisons, 55 identical installed bundled answers and four documented key-required paths. All 12 saved travel estimates independently recompute. |

Source-fixed candidates and completed audits are distinct from final publication. Full eCFR candidate live suite passed **448/448 with zero skips**; its frozen/current-SDK offline lanes passed330/skipped118. BLS candidate passed297/skipped1; USA candidate passed1,924/skipped379. Independent final source collection at `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f` measured **6,040 nine-product package tests**, **5,785 eight-goal tests**; these are collected counts, not a claim all were executed. Additional peer assertions and Worker tests are not included in that total.

Merged content PRs98,99,100,101 and coordinator integration PR102 used reviewed source `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f`. PR102 aligns the standalone BLS container pin before release; it is not another content finding. The failed local preflight pushed no release tag; full nine-package version consistency subsequently passed. SAM production deployment `7b29b820-0fc4-4045-a282-2542b611b9cc` already verifies version1.0.2/source SHA and all87 questions. SAM current verified official-file loader38065331780 completed successfully; data loaded15:52:32Z with64,417 active rows/46,083 latest versions. Code fixes leave source bundles unchanged and do not require an additional data reload.

BLS scoped release [38069372010](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38069372010) succeeded. eCFR [38069656331](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38069656331) stopped at an existing throughput start-spacing assertion:329 passed,118 skipped,one failed. Publication/deployment jobs were skipped; the coordinator stopped the serial queue before pushing the USAspending tag. Independent controlled evidence reproduced durable reservation spacing of0.6028 seconds but request-body spacing of0.4007 seconds after delayed persistence. The test asserted a stronger scheduler-dependent body-spacing guarantee than the shared-permit contract. PR105 corrected the test to check durable reservations while retaining the500-attempt/300-second budget, two-request concurrency cap and cross-process checks, and documenting this scheduling limit. The exact CI trigger is unknown; a retry alone is not evidence of strict dispatch spacing. The old tag is preserved. Independently reviewed PR105 merged at`d0b3e9883b2a70ac0c250b83f7fdd30234349fd8`; its immutable1.1.4 release completed successfully, followed serially by USAspending1.0.16 from the same source. Both frozen/current SDK offline lanes pass331/skipped118;17 independent pacing/content tests passed. Final independent collection at this source is**6,041 nine-product /5,786 eight-goal tests**. PR103/104 update BLS/USA README prose and do not require republishing unchanged package payloads. This integration/test correction is distinct from the seven content findings.

Round-2 source/answer/review/regression evidence lives under `round2/<server>/`; coordinator retains immutable collection, workflow, package artifact, public and physical-origin records. Eight final public service identities and all112 exact tool definitions passed. Allfive configured Dell origins passed45 independently reviewed checks: exact expected versions/SHAs, public GET/POST origin headers, tunnel health and direct authenticated physical container health/initialize. Sixteen official PyPI wheel/sdist artifacts across all eight packages were downloaded and matched declared sizes and hashes. USAspending final installed/public corpus also passed; the website and final record publication complete the closure gates below before round3.


### Round-2 final published destinations and verification

| MCP | Final published version | Release source SHA | Actual installed/public content verification |
|---|---|---|---|
| SAM.gov | Python1.0.13; public mirror1.0.2 | Mirror `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f` | Fresh installed Python catalog/startup;87 mirror/source questions and390 rows passed.19 keyed Python questions unexecuted. |
| USAspending | 1.0.16 | `d0b3e9883b2a70ac0c250b83f7fdd30234349fd8` | 127 CLI+11 follow-ups and127 public+11 follow-ups;55 tools; official fiscal-quarter totals/217 children passed. |
| eCFR | 1.1.4 | `d0b3e9883b2a70ac0c250b83f7fdd30234349fd8` | 73 CLI/70 public;50 current source comparisons+five original correction checks passed. |
| BLS OEWS | 1.1.4 | `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f` | 46 CLI/46 public;20 current official cells/footnotes; payload/hash parity passed. Original flat-file403 retained. |
| Federal Register | 1.0.14 | `b379d69b3ac505d5f1f1ae255896acb2b5f0d866` | 45 actual CLI/public comparisons,49 valid calls; four official full texts passed. |
| Regulations.gov | 2.0.4 | `b379d69b3ac505d5f1f1ae255896acb2b5f0d866` | 62 calls across nine tools;88 primary comparisons. Keyed source quota limits remain explicit. |
| GSA CALC+ | 1.0.14 | `7754923b8c77e51022e2c561856fd6ccf4eab874` | 123 installed registered-tool/public cases;2,521 source/workflow checks. Actual CLI startup/catalog/comparison separately passed;123 are not stdio calls. |
| GSA Per Diem | 1.2.3 | `7754923b8c77e51022e2c561856fd6ccf4eab874` | 59 calls,54 source comparisons,55 bundled CLI/public comparisons;12 independently recomputed estimates. |

Final eCFR scoped workflow [38070988195](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38070988195) succeeded on attempt1. USAspending [38071313999](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38071313999) succeeded on attempt2 after retrying only failed jobs on the same immutable tag. Its initial verifier observed matching health SHA but mismatching initialize version. Subsequent actual public and physical-origin evidence confirms the correct release. The original log did not identify a backend; the cause remains unknown and is not attributed to Dell. Releases were serialized; no queued release was canceled or replaced.

Independent PR113 strengthens hosted rollout readiness: both health SHA and initialize version must match within the existing bounded deadline before the remaining strict gates run. Three meaningful regressions include two before-fix failures; all67 release-guard tests and independent peer review passed. This integration correction is not a new content finding and does not require republishing unchanged package payloads. Documentation PRs103,104,106–112 and114 publish per-server evidence and source limits.

Final package collection is6,041 across nine product packages,5,786 in the eight-server goal. Ordinary offline lanes account for4,554 passed/1,487 skipped across nine;4,302 passed/1,484 skipped in scope. Collection, skipped source tests, independent source comparisons, historical full-live executions and Worker/parity checks remain separate measurements. The current449 eCFR collection is not represented as449 full-live passes.

### Cumulative goal findings through round 2

| MCP | P0 | P1 | P2 | P3 | Fully fixed | Partially fixed | Unresolved confirmed defects |
|---|---:|---:|---:|---:|---:|---:|---:|
| SAM.gov |0|0|2|3|5|0|0|
| USAspending |0|0|5|3|8|0|0|
| eCFR |0|1|5|2|8|0|0|
| Federal Register |0|0|2|1|3|0|0|
| Regulations.gov |0|0|3|0|3|0|0|
| GSA CALC+ |0|1|2|1|4|0|0|
| GSA Per Diem |0|0|2|4|6|0|0|
| BLS OEWS |0|0|4|1|5|0|0|
| Shared metadata |0|0|1|0|1|0|0|
| **Total** |**0**|**2**|**26**|**15**|**43**|**0**|**0**|

Source-access limitations and unsupported enhancements above remain limitations, not silently downgraded defects. Acquisition.gov's separate appendix is excluded from these counts and every future round. Compatible fixes retain existing endpoints, tool contracts and directory identities; no user manual directory republication is required. Directory scan timing and individual client approval are not claimed verified.


### Website and documentation publication

Website source [PR2](https://github.com/1102tools-dev/federal-contracting-prompts/pull/2) merged at `1b66bc38b0cf12bc72474d17a6a68e9f77c74dad`; deployment snapshot [PR4](https://github.com/1102tools-dev/1102tools-deploy/pull/4) merged at `e8f85433da5ff744eacf1d85543bbf100ddd9f5b`. Independent snapshot review verified source stamp, generated bytes, versions, audit counts and Acquisition exclusion. Actual Cloudflare Pages production deployment `7303b7e9` published the51-file allowlist to [1102tools.com](https://1102tools.com/). Fresh browser reload visibly confirms6,041 collected tests, current USAspending1.0.16 and BLS1.1.4, seven corrected Round2 findings and the dated record link. Public asset verification covers49 served assets plus two deployment configuration files; HTML comparisons remove only Cloudflare-injected analytics scripts and do not claim raw byte identity. Copy validation covers four core checks. Exact results remain in `coordinator/website-round2-public-assets.json`, `website-round2-copy-proof.json` and `website-round2-browser-proof.json`.

Published package metadata, source provenance, primary-source answer checks, eight public service identities/112 tool definitions and all-five Dell45 checks are saved separately. SAM source-data loader result remains current and successful; unchanged bundles require no additional reload. Server README/testing updates and this coordinator record preserve skipped checks and remaining source-access limits. No confirmed in-scope defect remains partially fixed or unresolved; the zero-new-P0/P1/P2 stopping condition still requires the next complete eight-server content audit. Round3 will be dispatched only after this final documentation PR is merged and its actual GitHub-served contents verified.


## Content round 3 — reviewed source and measured acceptance

Round 3 covered the same eight servers; Acquisition.gov remains excluded. All eight owners completed new ordinary-user and power-user content coverage and independent reviews. Ten new findings were confirmed: **P0=0, P1=0, P2=7, P3=3**. Source PRs [116](https://github.com/1102tools-dev/federal-contracting-mcps/pull/116), [117](https://github.com/1102tools-dev/federal-contracting-mcps/pull/117), [118](https://github.com/1102tools-dev/federal-contracting-mcps/pull/118), [119](https://github.com/1102tools-dev/federal-contracting-mcps/pull/119), [120](https://github.com/1102tools-dev/federal-contracting-mcps/pull/120) and [121](https://github.com/1102tools-dev/federal-contracting-mcps/pull/121) merged. Five scoped package releases use frozen source `7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336`; all five package, Cloudflare and automated registry workflows succeeded sequentially. The initial nine content fixes have published acceptance; the additional Regulations 2.0.6 correction has also passed final acceptance; website acceptance passed; this final coordinator publication closes the GitHub record gate after its served files are verified.

| Server | New P0 / P1 / P2 / P3 | Corrected ordinary-user behavior | Final target |
|---|---:|---|---|
| SAM.gov | 0 / 0 / 0 / 1 | Summary discovery permits older active notices while explaining incomplete historical coverage. | Python 1.0.13 unchanged; native mirror 1.0.3, source `0d87bdcf9d0c645428a57271736e4c35891bca53` already live. |
| USAspending | 0 / 0 / 1 / 0 | Grouped subaward totals explicitly cover the full prime record; fiscal filters select primes. Date-filtered, fully paged subaward followups recover reported subaward amounts for the requested dates; these do not establish a global subaward ranking or net-new spending. | 1.0.17 |
| GSA CALC+ | 0 / 0 / 1 / 0 | Fresh MCP 2.3 installations preserve anticipated unsupported-worksite recovery guidance instead of a generic error. | 1.0.15 |
| BLS OEWS | 0 / 0 / 0 / 0 | No new defects in 58 realistic questions, 431 measure/benchmark objects and 28 current official source cells. | 1.1.4 unchanged |
| GSA Per Diem | 0 / 0 / 1 / 1 | Correct UTF-8 county geography and accent normalization resolve Doña Ana/White Sands; registry setup guidance correctly permits bundled keyless city-plus-county workflows. | 1.2.4 |
| eCFR | 0 / 0 / 2 / 1 | History groups by section and sorts dates before pagination; catalog explains older history; available pre-2017 text comparisons work, with source-specific unavailable-date recovery. | 1.1.5 |
| Federal Register | 0 / 0 / 0 / 0 | No new defects in 54 realistic public/installed-CLI questions and current primary-source comparisons. | 1.0.14 unchanged |
| Regulations.gov | 0 / 0 / 2 / 0 | Provider closing timestamps are qualified source metadata; users follow controlling notices, eligibility conditions and later extensions. Ordinary filter/date recovery guidance must also survive fresh MCP SDK installs. | 2.0.6; original deadline and SDK recovery fixes verified live |

The eCFR result supersedes any earlier universal 2017 snapshot floor claim: actual 36 CFR 1194.1 text exists for December 13, 2016. Older availability depends on the title and section. Regulations.gov's provider conflict remains a disclosed source limitation; the corrected application no longer presents the raw timestamp as an established controlling deadline. The OSHA notice's October 30, 2025 extension applies to timely NOITA filers. Direct credentialed provider checks remain unavailable under quota/key constraints; captured-provider adapter checks are not claimed as live keyed CLI calls.

### Independent regression inventory

The initial frozen-source `7e8c4132` collection measured 6,064 product / 5,809 goal tests. After the corrective merge `c0553538`, a second independent collection measured **6,067 product package tests**, including Acquisition's 255, and **5,812 for the eight-server goal**. Both proof files remain immutable. All nine collection commands exited successfully. These are collected tests, not an all-passed claim. Worker, loader, contract, parity, current-source and realistic-content checks are separate lanes.

| Server | Collected | Saved complete offline lane: passed / skipped | New content coverage |
|---|---:|---:|---|
| SAM.gov | 1,155 | 781 / 374 (earlier execution) | 110 final public/source comparisons, 345 raw row checks; actual fresh Python CLI catalog/access verification. Nineteen keyed workflows unexecuted without SAM_API_KEY. |
| USAspending | 2,306 | 1,927 / 379 | 130 new cases across all 55 tools, 134 source captures; date-filtered followups. |
| GSA CALC+ | 435 | 314 / 121 | 132 registered-tool and public cases, 3,200 source/workflow assertions; original errors and corrected followups separately through actual stdio. Registered calls are not all stdio calls. |
| BLS OEWS | 298 | 297 / 1 | 58 actual fresh published CLI and public calls; 28 official source cells. |
| GSA Per Diem | 583 | 316 / 267 | 101 realistic cases; 98 primary numeric checks after the two corrections, 18 ZIP memberships. Two no-key workflows are expected guidance, not successful API source calls. |
| eCFR | 451 | 333 / 118 | 80 actual published CLI workflow occurrences and 75 public questions, 83 source checks per transport against 58 freshly recaptured primary sources; targeted source retries are retained separately. |
| Federal Register | 286 | 181 / 105 | 54 actual fresh published CLI/public/source cases; four complete agency deadline sets and four inspected source texts. |
| Regulations.gov | 298 | 179 / 119 (actual fresh published 2.0.6, SDK 2.3) | 115 public calls, 110 comparison rows and 70 primary captures (68 JSON plus two XML); four occurrences of one OSHA conflict qualified, with the linked controlling-notice workflow verified; two agenda dates unverified. |

Root version consistency passed for all nine packages after refreshing stale local editable installations; no runtime code change was needed for that local environment repair. All nine wheel/sdist builds and published-payload guards passed. The unchanged versions matched official PyPI payloads; five corrected versions were confirmed new. All 67 release guard regressions passed. Individual source PR CI and independent peer reviews passed before publication.

### Applicable production data reload

GSA Per Diem serves its public route from a native Worker and D1. A retained container configuration does not establish the active request backend. Automatic atomic loader [38074915107](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38074915107) succeeded after the merged bundle change. An actual remote production D1 query independently confirmed release `ba0994b637ca8ae7`, places part `2dee3470caca1a82`, complete flag 1 and **43,665 actual rows**, loaded `2026-10-10T18:13:46Z`. Corrected `NM|dona ana` and `NM|white sands` mappings are present. All seven fiscal-year parts remain unchanged. Evidence: `coordinator/gpd-round3-actual-d1.json`. Fresh published package, native deployment and original $396 two-night estimate acceptance passed, including independent registry setup-description verification.

SAM mirror 1.0.3 deployment `1b4b44a6-95eb-416e-992b-788d69afa06f` is live at source `0d87bdcf9d0c645428a57271736e4c35891bca53`: all 110 final realistic questions plus status passed against the fresh official CSV. Python 1.0.13, its data loader and schema are unchanged. Status retains 64,417 active notices / 46,083 latest versions and `2026-10-10T15:52:32Z` load time.

**All round-3 fixes and website acceptance passed.** This final coordinator publication completes the GitHub record; the coordinator verifies its actual served files after merge before dispatching round 4. The additional Regulations 2.0.6 corrective workflow, actual fresh published recovery/content checks, final mixed-SHA eight-server matrix and all-five Dell checks, and registry metadata passed. The initial five sequential package workflows and their destination checks already passed. Round 4 is required because this round found new P2 issues, and will start only after those gates close. No manual directory republication is required for these compatible corrections; registry publication and unobserved client directory review remain distinct.


### Cumulative ledger through confirmed round-3 findings

This table counts each confirmed finding once. The earlier 43 findings and nine initial round-3 fixes have final published acceptance; the additional Regulations SDK recovery finding has also passed published 2.0.6 acceptance. Acquisition's separate five findings are excluded.

| MCP / shared owner | P0 | P1 | P2 | P3 | Total confirmed | Fully fixed | Partially fixed | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SAM.gov | 0 | 0 | 2 | 4 | 6 | 6 | 0 | 0 |
| USAspending | 0 | 0 | 6 | 3 | 9 | 9 | 0 | 0 |
| eCFR | 0 | 1 | 7 | 3 | 11 | 11 | 0 | 0 |
| Federal Register | 0 | 0 | 2 | 1 | 3 | 3 | 0 | 0 |
| Regulations.gov | 0 | 0 | 5 | 0 | 5 | 5 | 0 | 0 |
| GSA CALC+ | 0 | 1 | 3 | 1 | 5 | 5 | 0 | 0 |
| GSA Per Diem | 0 | 0 | 3 | 5 | 8 | 8 | 0 | 0 |
| BLS OEWS | 0 | 0 | 4 | 1 | 5 | 5 | 0 | 0 |
| Shared documentation | 0 | 0 | 1 | 0 | 1 | 1 | 0 | 0 |
| **Total** | 0 | 2 | 33 | 18 | 53 | 53 | 0 | 0 |


### Round-3 publication and actual backend acceptance

All five scoped releases completed successfully at frozen source `7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336`, with no overlapping or replaced release runs:

| Scoped tag | Successful workflow | Cloudflare Worker deployment UUID |
|---|---|---|
| gsa-perdiem/v1.2.4 | [38075460793](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38075460793) | `2f637dc9-eea4-43b7-9632-8e471fb406a4` |
| gsa-calc/v1.0.15 | [38075712974](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38075712974) | `3fbb9010-0395-4560-8c47-13baf47a7743` |
| ecfr/v1.1.5 | [38076027377](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076027377) | `92925fb3-a4db-44c5-a2b5-b5202d88ad95` |
| usaspending/v1.0.17 | [38076343015](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076343015) | `6ab00396-e9e6-4951-96a2-059343201cb5` |
| regulations-gov/v2.0.5 | [38076645801](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076645801) | `3a91c410-cb7a-4214-a6f9-b48defda9924` |

Root initial production acceptance passed for all eight public health/source/version identities, absence of unexpected server instructions, and all **112 exact tool definitions**. Unchanged Federal Register remains `b379d69b3ac505d5f1f1ae255896acb2b5f0d866` / 1.0.14; BLS remains `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f` / 1.1.4; SAM retains its independent `0d87bdcf9d0c645428a57271736e4c35891bca53` / mirror 1.0.3. These are explicit per-service identities, not a single uniform SHA assertion. Evidence: `coordinator/eight-server-round3-final-contracts.json`.

Root independently downloaded **16 actual official wheel/sdist artifacts for all eight goal packages** and verified published version, byte count, official SHA-256 and non-yanked status. Expected-version checkout provenance is distinct from an assertion that unchanged artifacts were rebuilt at the new release SHA. Evidence: `coordinator/round3-pypi-artifacts.json`.

**All five configured Dell origins passed 45 actual initial-round checks.** USAspending 1.0.17, eCFR 1.1.5, CALC+ 1.0.15 and Regulations.gov 2.0.5 use the frozen new source SHA; unchanged Federal Register 1.0.14 uses `b379d69b3ac505d5f1f1ae255896acb2b5f0d866`. For each service, public GET health and POST initialization returned `x-1102tools-backend: origin`, the HTTPS origin reported the expected health identity, and SSH-authenticated direct physical-container health and initialization verified the matching SHA/version and no unexpected instructions. No backend conclusion relies solely on retained configuration. Evidence: `coordinator/dell-round3-final-verified.json`.

Brief official simple-index propagation delays affected initial fresh by-name installs; bounded retries used only official PyPI and retained the failed attempts. No candidate wheel was substituted. Final content acceptance remains separate from these publication and routing gates.

### Fresh-installed SDK recovery correction — published acceptance

The actual published Regulations.gov 2.0.5 package installed with MCP SDK 2.3 returned generic errors for ordinary requests to include closed comment periods and reuse a document filter date in a docket search. Its fresh suite measured 138 passed, 38 failed and 119 skipped; the earlier locked-SDK 176 passed / 119 skipped result is not a fresh-SDK pass. PR129 preserves anticipated recovery guidance with a narrow compatible exception class. Two original regressions fail before the correction; corrected SDK 2.0 and 2.3 candidate lanes each measure 179 passed, 119 skipped and 298 collected. Actual console originals and captured-provider corrected followups passed in both candidate and final published checks; captured adapters are not keyed live provider calls. Independent merged-source collection now measures 6,067 product / 5,812 goal tests, with Regulations at 298; actual checkout provenance differs only in coordinator documentation. Evidence: `coordinator/round3-corrective-final-collection/collection.json`. Publication of 2.0.6 and final mixed-SHA destination acceptance passed. Fresh official installed console originals and the resolved SDK 2.3 suite passed (179 passed, 119 skipped, 298 collected). Independent actual public recovery and conditional deadline workflows also passed. Full final public corpus replay passed all 115 calls across nine tools with 91 qualified dated records. Retained source hashes were checked and one returned primary notice fetched afresh; Website publication and actual browser/asset acceptance passed; this coordinator record is the final documentation publication. Existing tags and initial destination proofs remain immutable.

### Published content acceptance and source boundaries

The initial nine corrections passed their final published questions and relevant followups. These results remain valid for the seven unchanged services during the additional Regulations corrective release:

| Service | Actual published content evidence | Material source or execution limits |
|---|---|---|
| SAM.gov | 110 public questions plus status, 345 raw row checks and freshly retrieved official CSV; installed Python catalog/access verified. | Nineteen keyed Python workflows were unexecuted without SAM_API_KEY; public mirror coverage is not full historical completeness. |
| USAspending | 130 published CLI and 130 public questions across all 55 tools; six guided date/pagination workflows, 134 initial canonical-JSON source captures and two targeted retry captures. | Initial CLI CFDA ReadTimeout and public Transportation program-activity verifier timeout each recovered in targeted retries. Public timeout cause remains unknown; neither attempt is silently counted as an initial pass. Reported subaward amounts are not net-new spending or a global fiscal-year ranking. |
| GSA CALC+ | 132 actual installed registered-tool calls and 132 public calls; 3,200 source/workflow assertions. Actual stdio separately passed the two original worksite errors, two repaired followups and one smoke question. | Registered calls are not all stdio. Current primary data fluctuated: 216 percentile checks varied by at most $2.9341/hour and six aggregation cases had bounded bucket-count/tail-membership variation; these are documented source variation, not exact response parity. |
| BLS OEWS | 58 actual fresh published CLI and58 public questions, 431 measure/benchmark objects and 28 current official source cells; 297 offline passed/one skipped. | A source flat-footnote endpoint returned 403; corrected draft questions are excluded. Source notes and historical/area definitions are preserved. |
| GSA Per Diem | 101 fresh published CLI and101 public questions,98 primary numeric checks,18 ZIP memberships, keyless county/Arlington followups and independently verified $396 Doña Ana estimate. Actual registry1.2.4 setup description passed. | Two city-only keyless paths return expected missing-key guidance, not successful API rates. D1 data reload evidence is separate from package acceptance. |
| eCFR | 80 actual published CLI workflow occurrences and75 public questions;83 checks per transport against 58 freshly recaptured primary XML/JSON sources; six complete independently recomputed FAR definition blocks. | 75 semantic CLI/public matches include 74 exact matches and one FEMA search-score drift. Source 429/timeout attempts are retained; only the remaining workflows/sources were retried. Four-call unavailable-date guidance/history/available-compare recovery passed per transport; availability is title/section-specific. |
| Federal Register | 54 actual fresh published CLI and54 public questions across all eight tools,54 primary comparisons, four complete agency deadline sets and four inspected original source texts. |181 offline passed / 105 skipped / 286 collected is distinct from this new content corpus. Discovery scan bounds, archive coverage and weekend Public Inspection behavior remain explicit. |

Regulations.gov initial 2.0.5 accepted 115 public calls and 110 comparison rows from 70 primary captures: 76 machine matches, 22 records with no date, six extension reconciliations, four occurrences of one disclosed OSHA timestamp conflict and two EPA agenda dates whose controlling date was unverified. The controlling notice established the conditional October 30 deadline for timely NOITA filers. Source quota 429 and two PDF 403 responses remain unavailable checks. The additional fresh-SDK recovery correction is tracked separately above with 2.0.6 final acceptance also passed.

### Corrective release identity and final destination matrix

Regulations.gov [PR129](https://github.com/1102tools-dev/federal-contracting-mcps/pull/129) merged at `c0553538fca43e13a8c7db5a6ecd77a887303c32`. The single additional immutable tag `regulations-gov/v2.0.6` completed [workflow38078614558](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38078614558), publishing PyPI, Cloudflare deployment `74313844-eef7-4d96-bb20-bb653966bd06`, automated registry metadata and GitHub release. No initial tag was moved, no queued workflow canceled or replaced, and no additional data reload was applicable to this error-guidance-only change.

Actual final checks use a per-service matrix: Regulations2.0.6 at `c0553538`, the other four initially updated services at `7e8c4132`, SAM mirror1.0.3 at `0d87bdcf`, BLS1.1.4 at `5ba4a4ba` and Federal Register1.0.14 at `b379d69b`. All eight public identities and112 exact tool definitions passed; all five configured public Dell takeovers and their actual HTTPS/SSH physical backends passed45 checks; all eight official package versions and16 downloaded artifact hashes/sizes/non-yanked states passed. Evidence: `coordinator/round3-corrective-final-expected.json`, `eight-server-round3-corrective-final-contracts.json`, `dell-round3-corrective-final-verified.json` and `round3-corrective-pypi-artifacts.json`. The initial2.0.5 proof files remain unchanged. Fresh installed package and final 115-call content acceptance also passed. Website publication passed. The final coordinator record publication and actual GitHub served-file check complete round closure.

Final Regulations source seal confirms all110 semantic comparisons, 70 retained source hashes and the freshly returned controlling notice. The final owner evidence is `round3/regulations/final-published-2.0.6/summary.json`; independent SAM peer evidence verifies12 actual public recovery/deadline questions and a fresh official installed console. Docs-only PR130 publishes final acceptance without a further package bump.

### Website and final documentation publication

Website source [PR3](https://github.com/1102tools-dev/federal-contracting-prompts/pull/3) merged at `3c034775695fa071fb98fc77109fc8c4b1da95a5`; deployment snapshot [PR5](https://github.com/1102tools-dev/1102tools-deploy/pull/5) merged at `a07c606ed35198b2713d2bc8843fd512b88bbd0d`. Independent source and snapshot review passed exact source stamping/byte identity, counts, versions, scope exclusion and the51-file allowlist; both CI workflows passed. Actual Cloudflare Pages deployment `28a5c883` published to [1102tools.com](https://1102tools.com/). Final public acceptance passed49 served assets plus two configurations, four copy checks and an actual browser reload/expanded-card review. HTML source comparisons remove only Cloudflare-injected analytics scripts; no raw HTML-byte identity is claimed. The browser shows6,067 collected product tests,5,812 goal tests, Regulations2.0.6/298, current package cards, ten corrected round-3 findings and the unmet future zero-new-P0/P1/P2 stopping condition.

Evidence: `coordinator/website-round3-public-assets.json`, `website-round3-copy-proof.json`, `website-round3-browser-proof.json`. Server documentation PRs122–130 are merged; the additional final Regulations documentation merge is `c7b5a204b18e981194e7fbd73428c919c289d367`. This coordinator change publishes the root README, measured inventory, native Per Diem deployment guidance and the cumulative release record. Actual GitHub served-file verification follows merge and is retained in the coordinator closure evidence; it does not require republishing compatible MCP directory listings. All53 confirmed findings are fully fixed, none partially fixed and none unresolved. Source credential/quota/unavailable-document limits remain explicit. Round4 must still find no new P0/P1/P2 issues before the overall goal can complete.


## Round 4 — published content and website accepted; final record publication

All eight owners finished realistic ordinary-user and power-user content coverage before release integration. Nine new confirmed findings comprise five P2 and four P3 issues. No P0 or P1 was found. Acquisition.gov remains excluded from this goal and every subsequent round. The cumulative confirmed inventory is 62 (0 P0, 2 P1, 38 P2, 22 P3), with all62 source fixes merged. All62confirmed findings have actual published content acceptance and the updated website is deployed and verified. This final coordinator publication completes the GitHub record; actual served-file verification follows merge. The zero-new-P0/P1/P2 stopping condition remains unmet because this round found five P2 issues.

| MCP | New P0 | New P1 | New P2 | New P3 | Correction / current acceptance |
|---|---:|---:|---:|---:|---|
| SAM.gov | 0 | 0 | 1 | 0 | Reusing returned ISO award dates or CGAC codes preserves actionable format guidance in the fresh SDK. Python 1.0.14 is published and independently accepted; the separate native mirror remains 1.0.3. |
| USAspending | 0 | 0 | 2 | 3 | Program inventories disclose that fiscal-year filtering is not applied, return complete bounded lists, preserve source types, and distinguish inventory from fiscal-year spending. Catalog guidance no longer promises an unsupported mandatory/discretionary split or a current-fiscal-year default when the source uses its latest available certified year. Published1.0.19 verified the original four corrections in150CLI/public questions. Published1.0.20 additionally preserves explicit-current-FY availability guidance; independent final original/recovery checks passed, with the full150CLI/public owner replay and six guided workflows passed. |
| GSA CALC+ | 0 | 0 | 1 | 0 | Mixed Registered Nurse grades and specialties no longer support a verified comparable-price verdict; matched-title recovery and unsupported-filter limitations remain explicit. Published1.0.16 passed152registered/152public workflows plus18actual stdio calls; final fresh-package acceptance passed. |
| eCFR | 0 | 0 | 1 | 0 | Missing current legacy 41 CFR 102-75.45 returns useful removal/history/dated-text recovery in a fresh installed console. Actual published1.1.6 passed80CLI/76public calls,192retained-source comparisons and the fresh338passed/118skipped suite. |
| Regulations.gov | 0 | 0 | 0 | 1 | Public README badge now reports the actual 298 collected cases. Docs-only change is served and verified; package 2.0.6 remains unchanged. |
| BLS OEWS | 0 | 0 | 0 | 0 | Full assigned coverage completed; source limitations retained separately. |
| Federal Register | 0 | 0 | 0 | 0 | Full assigned coverage completed; scan and source-date qualifications retained. |
| GSA Per Diem | 0 | 0 | 0 | 0 | Full assigned ordinary-content coverage completed; fresh SDK test-message compatibility failures are disclosed separately. |
| **Total** | **0** | **0** | **5** | **4** | **All nine corrections and website publication accepted; final coordinator record completes closure.** |

### Reviewed release integration and immutable failed attempt

SAM package-only workflow PR135 preserved the hosted mirror and established fail-closed publication gates for legitimate empty hosted matrices. Actual tag `sam-gov/v1.0.14`, source `d6ea8fea87732e5d28945be9cbd2917c87c844c8`, workflow38080882021 succeeded through official PyPI publication, payload verification, registry metadata and GitHub release. Hosted build/access/deployment jobs were genuinely skipped. Owner and independent fresh official installed console acceptance, unchanged 20-tool contract and 784 passed / 374 skipped / 1,158 collected acceptance passed. Credentialed SAM source calls remain unavailable without a key; those are not counted as live source passes.

The immutable first hosted attempt `usaspending/v1.0.18` at `dcb2192ac215f3ea78b144b60ac2155a16305dfd`, workflow38081445249, stopped on an existing body-entry spacing assertion: 1,929 passed / 379 skipped / one failed. Production deployment, PyPI publication, registry publication and GitHub release were skipped; CALC and eCFR tags were not pushed. No tag was moved and no queued release was canceled or replaced.

Controlled delayed-persistence experiments reproduced compressed request-body entry gaps while durable request reservations remained correctly spaced. This proves an invalid timing assertion; the precise cause on the original CI runner remains unknown. Narrow test-only PR144 for USAspending and PR145 for CALC retain meaningful attempt-budget, concurrency, cancellation, error-consumption, cooldown, crash and cross-process checks. CALC's actual policy is 500 attempts/hour with two concurrent attempts; USAspending retains its own 500/300-second budget and cap four. Runtime helpers, tool contracts and content fixes are unchanged. USAspending metadata PR143 reserves a new immutable 1.0.19 release; failed 1.0.18 history is retained. These release-test integration repairs are not additional content findings.

### Coverage inventory and limitations

The original candidate-source collection independently measured 6,081 package cases across nine product servers, of which 5,826 belong to the eight-server goal. That original proof remains immutable. A separate independent corrective-source collection at `4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b` also measures **6,081 product / 5,826 goal cases**, with all nine collection commands exiting successfully and unchanged source/environment provenance verified. These are collected cases, not passing-test totals. Evidence: `coordinator/round4-corrective-final-collection/collection.json`. The 255 Acquisition cases are passive product inventory, not an Acquisition audit.

GSA Per Diem's frozen suite passed316 with267 skips, whereas the actually installed fresh SDK suite passed300 with267 skips and16 pre-existing expected-message failures. The ordinary content corpus did not reproduce an affected workflow. Those16 failures remain explicit, outside this content campaign; no full fresh-suite pass is claimed. BLS flat-footnote403, SAM credentials, Regulations source credentials/quota and source-date/availability limitations are retained in per-server records. Registered-tool calls, actual stdio calls, exact parity, source variation and historical retained captures are reported separately.


### Additional published availability guidance and actual fresh SDK results

Actual USAspending1.0.19 publication succeeded in workflow38082477859 at `4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`, with Cloudflare version `cbc8da27-84ce-4c95-ac2f-7aa10bc7c99c`. Owner acceptance completed150 actual CLI/public questions and150 retained-source comparisons; independent fresh official installed console/public acceptance passed six original/followup workflows, all55 tool definitions and reviewed payload identity. An evidence lookup that omitted tool names was corrected by reconciling saved outputs with the original tool-qualified source captures; no product data changed and no unnecessary corpus replay was performed.

The actual fresh installed SDK2.3 suite measured **1,075 passed / 855 failed / 379 skipped / 2,309 collected**. The full1930/379 candidate/source test execution was frozen SDK2.0, not a full fresh-SDK pass. Candidate SDK2.3 had executed150 content calls and six guided followups only. Historical logs are retained, and the corrected provenance is recorded in `round4/usaspending/source-suite-provenance.json`. Ordinary supported-content successes and exception/message regression failures are reported separately; a blanket generic-SDK repair is outside this content campaign.

A normal explicit-current-FY2027 account question exposed one additional P3: the official source returns HTTP400 explaining its available2001–2026 range, the public origin preserves that explanation, but the fresh CLI hides it. The unavailable source data is a limitation; suppression of its actionable guidance is the confirmed product defect. The catalog and omitted-year FY2026 default are already accurate, and no wrong FY2027 data is returned, supporting P3 severity. The owner implemented a narrowly scoped dynamic source-range correction for version1.0.20 with the original question and supported omitted-year recovery, preserving unexpected failures and the55-tool contract. Independent exact-head SAM review and CI passed before merge; the separate serialized1.0.20 release subsequently completed successfully.


### Final source inventory and publication preparation

USAspending PR147 merged at `2a93b7b706d818da647f9d56cacbf543f867fa79` after exact-head independent SAM review and CI38083611051 passed. Three source-captured regressions preserve the provider explanation, supported default-year recovery and unexpected503 behavior. The frozen full suite passed1,933 with379 skips; latestSDK focused three cases passed. Actual1.0.20 publication completed successfully; fresh installed full execution measured1,078passed/855failed/379skipped and the150CLI/public owner replay passed.

Independent final collection measured **6,084 product package cases / 5,829 eight-goal cases**, including USAspending2,312 and the passive255 Acquisition inventory. All nine collection commands exited successfully. Actual integration HEAD `9e7717d969a4469aac56de75943cdcc4c958db34` differs from canonical release source2a93 only in the three coordinator documentation files; every tracked package file was independently byte-verified against canonical source. Proof: `coordinator/round4-corrective20-final-collection/collection.json`. Earlier dcb/4ef collections remain immutable. These are collected cases, not a claim of6,084 passing fresh-SDK tests.

CALC1.0.16 actual final acceptance completed152 registered-tool workflows plus152 public workflows,1,742 behavioral checks and3,738 qualified source/data comparisons. Separate actual stdio acceptance passed18 calls across all8 tools, including the affected grade originals and exact-title recovery. Full freshSDK2.3 execution passed317 with121 skips (438collected). The local500/hour budget blocked51 calls plus six retries;152 unique successful registered workflows span209 attempts after honoring expiry. Dynamic source comparison includes244 percentile scalars varying by at most$2.551834/hour and one bounded TechnicalWriter suggestion-tail variation verified by two fresh source repeats and an exact unseen-title check. These are qualified source comparisons, not byte-exact current numeric parity.

Interim1.0.19 destination verification passed eight public services/112 exact definitions, all16 official downloaded artifact hashes/sizes and allfive Dell origins/45 checks. Independent Federal Register review recomputed90 assertions. Actual Dell evidence checks publicGET/POST origin headers, HTTPSoriginGET health, and SSH container-local initialization/physical health. It does not claim HTTPSoriginPOST initialization. These interim19 records remain immutable; final20 requires a separate matrix and actual repeated destination checks before closure.


### Final20 production and package destination checks

USAspending immutable tag `usaspending/v1.0.20` completed workflow[38083846513](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38083846513) at source `2a93b7b706d818da647f9d56cacbf543f867fa79`; Cloudflare deployment is `571c0cb3-0551-4f1a-b32f-cde5c15e6fc8`. Every scoped job succeeded, including official PyPI payload verification, automated registry metadata and GitHub release. No queued release was canceled or replaced.

The separate final20 mixed-SHA matrix passed all eight public health/source/version identities and112 exact tool definitions. All eight official package versions and16 downloaded wheel/sdist artifacts passed official byte-count/hash/non-yanked checks. Allfive configured Dell origins passed45 actual checks: publicGET/POST origin routing headers, HTTPSoriginGET health and SSH-authenticated container-local health/initialization identities. No HTTPSoriginPOST initialization claim is made. Proofs: `coordinator/eight-server-round4-final20-contracts.json`, `round4-final20-pypi-artifacts.json`, `dell-round4-final20-verified.json` and its hash manifest. Interim19 records remain unchanged.

Independent actual official installed USA20 acceptance passed six original/followup CLI and public cases, including the unavailableFY2027 explanation, supported omitted-yearFY2026 recovery, complete25-program Science inventory and separately qualified FY2024 account obligations. The actual55-tool contract and8runtime modules matched released source; three focused published regressions passed. The owner full-corpus replay subsequently passed150CLI and150public calls plus six guided workflows. These content passes do not establish a full fresh-suite pass. Evidence: `round4/usaspending/post-release/peer-sam-final20.json`.

eCFR actual official1.1.6 acceptance passed80CLI calls (four dedicated originals/recoveries plus76corpus calls),76public calls and all76exact shared answers. All192 comparisons passed against61retained primary captures; a separate fresh official title check confirmed nine snapshot metadata values unchanged. Fresh SDK2.3 measured338passed/118skipped/456collected. Missing-section404 answers remain expected source absence, with actionable recovery, not current-text retrieval. Independent GPD finaldocs review and CI38084244699 passed before docsPR149 merged; CALC finaldocsPR148 likewise passed independent GPD review and CI38083971643 before merge.

Fresh actual production data verification passed with no Round4 reload required: GPD complete release `ba0994b637ca8ae7`, places `2dee3470caca1a82`,43,665rows and unchanged seven fiscal-year parts; SAM native mirror1.0.3 and BLSMay2025 bundle identities remain unchanged. The independent remote D1 check wrote zero rows. Source304 reuse is explicitly distinguished from a new completeCSV fetch. Evidence: `round4/final-data-verification-gpd.json`.


### Round4 final version and execution inventory

These counts report completed lanes separately from collection. Acquisition's255cases remain passive inventory, excluded from goal findings and future audits.

| MCP | Actual published package | Public runtime source | Collected | Executed content and suite boundaries |
|---|---|---|---:|---|
| SAM.gov |1.0.14|Native1.0.3 at `0d87bdcf9d0c645428a57271736e4c35891bca53`|1,158|114native content questions/all4tools plus status,348raw-field and18semantic checks; freshPython784passed/374skipped. Nineteen keyedPython workflows unexecuted. Python release source `d6ea8fea87732e5d28945be9cbd2917c87c844c8`.|
| USAspending |1.0.20|`2a93b7b706d818da647f9d56cacbf543f867fa79`|2,312|Published20 completed150CLI/150public/150retained-source comparisons and six guided workflows; independent sixCLI/sixpublic plus threefocused regressions passed. Actual20fresh full suite measured1,078passed/855failed/379skipped; final150-question CLI/public owner replay and six guided workflows passed. Frozen source1,933passed/379skipped is distinct from latestSDK execution.|
| eCFR |1.1.6|`4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`|456|80CLI/76public,192retained-source comparisons; fresh338passed/118skipped. Nine fresh title metadata checks separate from retained61sourcecaptures.|
| Federal Register |1.0.14|`b379d69b3ac505d5f1f1ae255896acb2b5f0d866`|286|63validCLI/public questions across8tools,63primary rows and178DOTdeadline records. One caller-document mistake excluded; one page-view timestamp variation qualified.181passed/105skipped.|
| Regulations.gov |2.0.6|`c0553538fca43e13a8c7db5a6ecd77a887303c32`|298|141public attempts/139successful plus two retained caller-ID404s recovered;107semantic checks,40sourcecomparison rows/35freshcaptures. Fresh179passed/119skipped; keyedCLI live source unavailable.|
| GSA CALC+ |1.0.16|`4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`|438|152registered/152public/18actualstdio;1,742behavior and3,738qualifiedsource checks. Fresh317passed/121skipped;209registeredattempts retain budget waits and dynamic-source variation.|
| GSA Per Diem |1.2.4|`7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336`|583|121public/121CLI calls across7tools (119substantive keyless replays plus two expected credential replies);119officialnumeric checks,36estimates and26ZIPmemberships. Frozen316passed/267skipped; fresh300passed/16failed/267skipped, ordinary workflows unaffected.|
| BLS OEWS |1.1.4|`5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f`|298|66CLI/66public across8tools,418wageobjects and31freshofficial numeric cells.297passed/one skip; flat-footnote403 unavailable.|
| **Eight-server goal** | | |**5,829**|**Collected cases, not an all-passed fresh-suite total.**|
| Passive Acquisition inventory |Excluded|Separate completed track|255|No Round4 audit or future dispatch.|
| **Nine-package product inventory** | | |**6,084**|Independent canonical-source collection only.|


### Round4 completed release workflows

| Scoped tag | Frozen source | Successful workflow | Cloudflare deployment / scope |
|---|---|---|---|
|sam-gov/v1.0.14|`d6ea8fea87732e5d28945be9cbd2917c87c844c8`|[38080882021](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38080882021)|Package-only; hosted jobs genuinely skipped, native mirror unchanged.|
|usaspending/v1.0.19|`4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`|[38082477859](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38082477859)|`cbc8da27-84ce-4c95-ac2f-7aa10bc7c99c`; preserved intermediate release.|
|gsa-calc/v1.0.16|`4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`|[38082856566](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38082856566)|`ab04ec42-39e2-4b28-9b37-8cb5b1d795f8`.|
|ecfr/v1.1.6|`4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`|[38083173160](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38083173160)|`4b4313cb-77f2-4e54-8998-fe136013b875`.|
|usaspending/v1.0.20|`2a93b7b706d818da647f9d56cacbf543f867fa79`|[38083846513](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38083846513)|`571c0cb3-0551-4f1a-b32f-cde5c15e6fc8`; finalUSAversion.|

Source/content/documentation PRs132–145 and147–149 are merged; final USA documentationPR150 is also merged; root coordinatorPR146 publishes the final record after actual website/content gates passed. Runtime/content corrections are PR136(eCFR),137(SAM),139(CALC),141(USAprograms/catalog) and147(USAavailability); PR138 fixes the actual Regulations badge. PR135 is release infrastructure and PR144/145 are meaningful timing-test repairs, not new content findings. Automated registry updates succeeded without requiring manual directory republication. Actual directory/client propagation remains unobserved.


### Cumulative ledger through published Round4 corrections

Each confirmed finding is counted once; historical first-round toolchain/shared findings remain included, while Acquisition's separate findings remain excluded. Independent Regulations review recomputed all62counts and verified the nine new finding evidence records. Source limitations are separate from product findings.

| MCP / shared owner | P0 | P1 | P2 | P3 | Confirmed | Fully fixed | Partially fixed | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|SAM.gov|0|0|3|4|7|7|0|0|
|USAspending|0|0|8|6|14|14|0|0|
|eCFR|0|1|8|3|12|12|0|0|
|Federal Register|0|0|2|1|3|3|0|0|
|Regulations.gov|0|0|5|1|6|6|0|0|
|GSA CALC+|0|1|4|1|6|6|0|0|
|GSA Per Diem|0|0|3|5|8|8|0|0|
|BLS OEWS|0|0|4|1|5|5|0|0|
|Shared documentation|0|0|1|0|1|1|0|0|
|**Total**|**0**|**2**|**38**|**22**|**62**|**62**|**0**|**0**|

The latest fresh USA20suite failures855and GPD16legacy expected-message failures remain explicitly unresolved in their test lanes; they are not silently marked passing or added as855/16content findings. This campaign audits real ordinary and power-user content. Source credentials/quota/unavailable dates/documents remain bounded evidence limitations. Any new ordinary workflow that exposes a real product defect in the next audit must be recorded and corrected normally.


### Round4 website and final documentation publication

Website source[PR4](https://github.com/1102tools-dev/federal-contracting-prompts/pull/4) merged at `faa8cb7383057756bcb050b436548fa269238a49` after exact-head root/GPD review and bothCI workflows passed. The deployment snapshot[PR6](https://github.com/1102tools-dev/1102tools-deploy/pull/6) merged at `f43f0ce05fec9e785620b26d9c8c8ac2c1408ad6`, stamped to that exact source; independent FR review passed116assertions and bothCI checks passed. Exactlyfive snapshot files changed; all57prompt objects,25protected source files, Acquisition entry, directory links, printablePDF and demo/brand assets remain unchanged.

Cloudflare Pages deployment `0f19af06` published to[1102tools.com](https://1102tools.com/). Actual final public verification passed49servedassets plus two configurations, four copy checks and a real browser reload/expanded-card check. Initial post-deployment verification found the comparison page different while the other three copy checks passed; that attempt is preserved. A targeted subsequent fetch matched exactly after removing only the injected Cloudflare analytics script; the complete followup asset/copy gates passed. The initial difference's precise cause is unconfirmed. HTML comparisons remove only injected analytics; no rawHTMLbyte-parity claim is made.

The actual browser shows6,084product/5,829goal collected cases, current package versions, nine corrected Round4findings and62cumulative fixes;855USA/16GPDfresh-suite failures and the unmet future zero-new-P0/P1/P2 condition remain explicit. Evidence: `coordinator/website-round4-pages-deploy.log`, `website-round4-public-assets.json`, `website-round4-copy-proof.json`, `website-round4-browser-proof.json`; initial attempt files remain unchanged.

Final USA documentation[PR150](https://github.com/1102tools-dev/federal-contracting-mcps/pull/150) merged at `44d3bec` after root review, independent SAM review and exactCI38084829120 passed. All Round4 server documentation is merged; rootPR146 publishes the measured README inventory, reviewed release guide and this cumulative record. It touches documentation only, so no path-filteredCI result is expected or falsely claimed. Independent final record review is preserved; the coordinator verifies19actual servedGitHub files after merge and seals the Round4closure manifest before dispatching Round5. No manual MCP directory republication is required.

Round4 found five newP2issues, so the overall goal is still active. Only a subsequent complete eight-server content round with no newP0/P1/P2findings, followed by required fixes/publication/evidence closure, satisfies the stopping condition. Acquisition remains excluded.


## Round5 completed content corrections and release acceptance

Round 5 confirmed four new findings: **0 P0, 0 P1, 1 P2 and 3 P3**. Adding them once to the accepted Round 4 ledger gives **66 cumulative findings: 0 P0, 2 P1, 39 P2 and 25 P3**. Acquisition.gov is excluded from the eight-server content audit. The prior shared documentation P2 remains counted once. A new round starts only after the completed round is sealed.

The four corrections are in merged source. SAM native 1.0.4 and USAspending 1.0.21 have actual published content acceptance. CALC's correction is documentation only and merged in PR159 (`88d866b`); it requires no runtime release. eCFR 1.1.7 completed actual published acceptance: 95 installed CLI and 95 public calls, all shared answers exact, 190 primary comparisons and twelve supplementary checks per surface passed. Independent fresh installed/public five-query acceptance passed. All 66 confirmed content corrections have published acceptance; website/root documentation closure remains a separate gate.

| New finding | Severity | Affected publication | Correction and evidence |
|---|---|---|---|
| eCFR individual-surety definition classified as a mention, with a false “does not define” answer | P2 | 1.1.6 | Recognize three expressly defined numbered Surety subtypes while preserving parent and mention boundaries. Fresh primary FAR2.101 XML; original actual CLI/public failures; meaningful before/after controls; 1.1.7 workflow success. Actual published95CLI/95public and independent five-query acceptance passed. |
| USAspending five current construction NAICS results falsely said ten omitted current codes were retired | P3 | 1.0.20 | Separate actual retired rows from current rows omitted by the requested limit. Official15-row pool has no retired rows; retain real-retired controls. Published1.0.21 original and larger-limit recovery passed. |
| SAM native search catalog falsely said all past-deadline notices were excluded | P3 | Native1.0.3; Python1.0.14 unaffected | Describe the existing AwardNotice/Justification exception. Actual45 old active award records, raw official CSV deadline and original/followup discovery preserved. Published native1.0.4 full127 content/source comparisons passed. |
| CALC current testing summary claimed release1.0.15 and435 tests | P3 | Current repository documentation for published1.0.16 | Correct to1.0.16 and438 collected,317 passed/121 optional skipped. Actual release identity and independent collection/prose checks; docs-only PR159 merged. |

### Actual coverage and source scope

| Server | New realistic coverage and actual execution | Primary comparison scope |
|---|---|---|
| SAM | 127 native public content calls plus status; Python console catalog/status verified;19 keyed Python workflows unexecuted | 127 case comparisons/347 raw rows;34 substantive interpretations and14 exact notice amounts. Fresh HTTP304 confirmed retained full CSV bytes, not a new full download. |
| USAspending | 143 new questions across55 tools;10 prior Interior verification calls retained separately,153 invocations per actual CLI/public surface | 160 parsed primary captures. Published21 final ordinary content and targeted NAICS recovery passed; grouped cumulative and date-filtered amounts remain distinct. |
| eCFR | 93 baseline actual CLI/public calls across13 tools,92 exact/93 substantive matches | 66 fresh primary captures; baseline reconciliation180 passes plus six occurrences of the one known nested-definition finding, not186 passes. Final actual published95CLI/95public passed all190primary comparisons plus twelve supplementary checks per surface;66 captures retained,12 audited-title snapshot metadata checked freshly. |
| Federal Register | 71 new actual public and fresh installed stdio calls across8 tools,69 exact/71 substantive | 75 parsed official API captures and3 raw original texts; four complete agency scans41/22/43/19=125 records, linked earliest-deadline recovery; four exact docket/text unions with provenance. |
| Regulations.gov | 133 valid public calls across9 tools;20 page-size3 operator errors excluded and preserved; fresh actual CLI startup/catalog/status only | 124 semantic assertions/51 selected comparisons/46 fresh FRJSON+5 XML;50 dated occurrences explicitly qualified. Direct keyed local data parity unavailable. |
| CALC | 172 valid registered/public calls across8 tools and22 actual stdio calls;10 word-exclusion harness mistakes excluded | 190 unaugmented parsed GSA captures,4,703 data/1,970 behavior/600 workflow checks; percentile approximation and sort ties remain qualified, not defects or exact scalar parity. |
| Per Diem | 114 new questions+4 actual keyless recovery calls=118 public/stdio across7 tools;116 unique combinations | 115 numeric comparisons, all38 estimates independently recomputed,22 ZIP memberships,7 fresh raw official files. Six caller compositions are not additional tool calls. |
| BLS OEWS | 65 actual CLI/public questions across8 tools;4 caller budgets are not additional tool calls | 450 benchmark objects/33 fresh official numeric API cells; bundled May2025, hourly/annual measure distinctions and industry/geography scope retained. |

No skipped, unavailable, keyed-but-unexecuted, prior replay or caller-composed question is counted as a new successful source call. Source HTTP406/403 attempts, local harness corrections and earlier attempts remain retained. A source-backed provider value does not by itself establish legal enforceability, comment eligibility, current bidability or a controlling deadline.

### Collection and regression lanes

At canonical source `916d6efb07b0a87c2c5fec1fff4a81d5f9f01999`, root collect-only receipts measured **5,837 tests for the eight audited packages** and **6,092 product tests including Acquisition's passive255 inventory**. These are collected cases, not executed passes. All nine Python3.12.13 frozenSDK2.0 environments imported canonical source, and299 runtime/test files plus environment provenance were unchanged before/after collection. No install/sync/source mutation occurred in that root collection. The immutable package source differs from later documentation commits; those later commits do not replace release identities.

| Package | Collected | Frozen/source execution | Fresh official/published SDK2.3 execution |
|---|---:|---|---|
| SAM Python1.0.14 | 1,158 | Use owner/root receipts for distinct lanes; no new keyed full live claim | 784 passed/374 optional skipped |
| USAspending1.0.21 | 2,315 | 1,936 passed/379 skipped, Python3.14 frozenSDK2.0 | **1,081 passed/855 failed/379 skipped**; known negative/error-expectation compatibility observation retained |
| eCFR1.1.7 | 461 | 343 passed/118 optional skipped | 343 passed/118 optional skipped |
| Federal Register1.0.14 | 286 | 181 passed/105 live-gated skipped | **121 passed/60 failed/105 skipped**; existing validation/error-expectation failures retained |
| Regulations.gov2.0.6 | 298 | Root measured collection separately; current recorded regression execution is fresh installed lane | 179 passed/119 optional skipped |
| CALC1.0.16 | 438 | Root measured collection separately | 317 passed/121 optional live skipped |
| Per Diem1.2.4 | 583 | 316 passed/267 optional skipped, Python3.11 | **300 passed/16 failed/267 skipped**, Python3.12; existing invalid-input error-text expectations retained |
| BLS OEWS1.1.4 | 298 | 297 passed/1 skipped | 297 passed/1 skipped |

USA's855, FR's60 and Per Diem's16 fresh-lane failures are not silently counted as passes or new content findings. Ordinary content campaigns and meaningful new correction regressions are separate evidence. No universal fresh-full-suite pass is asserted.

### Published destination identities

| Public service | Actual version | Release source SHA |
|---|---|---|
| SAM native | 1.0.4 | `e81411afed154e04f79c74865acedaeb45b7f40f` |
| USAspending | 1.0.21 | `e694331f1161c557ac5f11e48076b7c3500dc2ea` |
| eCFR | 1.1.7 | `916d6efb07b0a87c2c5fec1fff4a81d5f9f01999` |
| CALC | 1.0.16 | `4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b` |
| Regulations.gov | 2.0.6 | `c0553538fca43e13a8c7db5a6ecd77a887303c32` |
| Per Diem native | 1.2.4 | `7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336` |
| Federal Register | 1.0.14 | `b379d69b3ac505d5f1f1ae255896acb2b5f0d866` |
| BLS OEWS | 1.1.4 | `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f` |

SAM's separate Python distribution remains **1.0.14**, source `d6ea8fea87732e5d28945be9cbd2917c87c844c8`. There is no overall common service SHA claim. Five unchanged services preserve their previously accepted release identities.

USA release workflow **38086492060** and eCFR workflow **38087180501** both completed SUCCESS, with all **13 jobs** successful in each, including package publication, registry, hosted build/deploy and release. Actual nativeSAM4 deployment and final catalog/health evidence are retained separately.

Root final public checks passed all eight identities and **112 exact tool contracts**, with no unexpected initialization instructions. **All five Dell services passed45 checks**. Dell evidence consists of public HTTPS GET health and POST initialize with exactly `x-1102tools-backend: origin`, origin HTTPS GET health, and authenticated SSH physical-container localhost **HTTP** POST initialize plus GET health. It does **not** claim an origin HTTPS POST test. Each service matched its own expected version/SHA.

All eight official Python versions and **16 actual wheel/sdist artifacts** passed downloaded byte-size/SHA256 and non-yanked checks. Expected versions came from the checkout; artifact hashes do not claim a build SHA that official metadata does not provide. Helper/output/config hashes and exact expected matrix are retained in the independent destination peer proof.

### Data and source limits

No manual directory republication or data reload was required. Actual GSA Per Diem remote D1 inspection reported43,665 place rows, the current places part complete, all accepted fiscal-year part identities, and **zero writes**. Seven fresh official Per Diem raw files match the existing source manifest. SAM's unchanged data provenance uses actual accepted mirror counts and conditional304 source identity; BLS retains its bundled May2025 dataset. These are explicit source checks, not universal freshness claims.

Regulations.gov's NOAA2026-20019 provider closing time remains11:59PMEastern while the actual notice controls at4:30PMAlaska/8:30PMEastern. The app explicitly reports `controlling_deadline_established:false` and actual linked-notice recovery exposes the earlier cutoff; no corrected raw timestamp or time-parity pass is claimed. Two agenda dates remain unverified. SAM old active records, narrative/date conflicts and secured attachments remain source followups. USA grouped totals/report dates, loans versus subsidy/obligations and recipient rollups remain distinct. FR publication text is not current legal enforceability. CALC ceilings are not paid prices; Per Diem agency eligibility and exceptions are caller/agency decisions; BLS illustrative burdens are not observed contractor prices.

### Published documentation and website

Round5 source/audit PRs[151](https://github.com/1102tools-dev/federal-contracting-mcps/pull/151)–[160](https://github.com/1102tools-dev/federal-contracting-mcps/pull/160) are merged after exact-head independent review and CI. Runtime fixes are PR152(nativeSAM),153(USA) and156(eCFR); CALC PR159 is documentation only. USA publication records[PR161](https://github.com/1102tools-dev/federal-contracting-mcps/pull/161) merged at `f2fc56aae208a9c23743faf819099a3372a235ed` after SAM peer review and CI38087494539 passed. eCFR publication records[PR162](https://github.com/1102tools-dev/federal-contracting-mcps/pull/162) merged at `590193ab` after independent38-file hash/byte and content review and CI38088196145 passed. Later documentation commits preserve immutable runtime release SHAs.

Website source[PR5](https://github.com/1102tools-dev/federal-contracting-prompts/pull/5) merged at `e340e6295f70c00769b3f4d32e5e0be324c64235`, reviewed head `505b0c31c4cdccfbd9a456adc38958616aa79662`. Independent FR review passed70assertions and bothCI38088262753/38088265940 passed. The review corrected mixed Dell transport wording before publication; the earlier source head remains in history. Deployment snapshot[PR7](https://github.com/1102tools-dev/1102tools-deploy/pull/7) merged at `7f171fb66499a097190c4a598de7d254e6dbc7c9`; independent CALC review passed114assertions at head `8e889010ae88c269e74a87916e28afe024dccfb0` and bothCI38088343485/38088345695 passed. All14 source files match exact source/stamp bytes; the staged51-file inventory contains14source,7demo and30brand files. Exactlyfive snapshot files changed. All57prompt objects,25protected source files, Acquisition entry, directory links, navigation, PDF, demos and brand assets remain unchanged.

Cloudflare Pages `03e19a24` published to[1102tools.com](https://1102tools.com/). Actual public checks passed49servedassets and two configuration files, allfour copy gates and a real browser reload/expanded-nine-card acceptance. HTML comparisons remove only the injected Cloudflare analytics script; this is not a rawHTMLbyte-parity claim. The browser shows6,092product/5,837goal collected tests, USA1.0.21/eCFR1.1.7,66fixed findings, precise mixedDell evidence and explicitUSA855/FR60/GPD16fresh-suite limitations. No failed Round5 website attempt was needed. Evidence: `coordinator/website-round5-pages-deploy.log`, `website-round5-public-assets.json`, `website-round5-copy-proof.json`, `website-round5-browser-proof.json`.

The root coordinator publishes the measured README inventory, reviewed native release guide and this record in a separate documentation-only PR after actual website/content gates pass. Independent exact-head root documentation review and actual19servedGitHub-file checks after merge are recorded in the final closure manifest before any Round6 dispatch. No path-filteredCI pass is invented for documentation-only changes.

### New runtime releases and all-five Dell acceptance

| Runtime | Immutable source | Actual publication | Cloudflare version |
|---|---|---|---|
|USAspending1.0.21|`e694331f1161c557ac5f11e48076b7c3500dc2ea`|[38086492060](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38086492060), all13jobs succeeded|`12fa692a-e3f5-4ee5-bfef-438314819381`|
|eCFR1.1.7|`916d6efb07b0a87c2c5fec1fff4a81d5f9f01999`|[38087180501](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38087180501), all13jobs succeeded|`ddef1a68-d5da-421a-b65f-d2c6d5b39471`|
|SAMnative1.0.4|`e81411afed154e04f79c74865acedaeb45b7f40f`|Actual established native deployment; Python1.0.14 unchanged|`e6c66d38-c6b1-4c38-9322-e1fc9284c8b3`|

Scoped USA21 completed before the eCFR7 tag was pushed; no queued release was canceled or replaced. Registry jobs succeeded automatically; directory/client propagation remains unobserved and no manual directory republication is required. Full original/followup published acceptance passed: SAM127, USA153(143new plus ten prior replays), eCFR95 per CLI/public surface. Independent actual fresh acceptance passed USA six unique workflows and eCFR five; attempt counts remain distinct.

| Configured Dell backend | Actual version | Final checks | Matching immutable source |
|---|---|---:|---|
|USAspending|1.0.21|9/9PASS|`e694331f1161c557ac5f11e48076b7c3500dc2ea`|
|eCFR|1.1.7|9/9PASS|`916d6efb07b0a87c2c5fec1fff4a81d5f9f01999`|
|CALC|1.0.16|9/9PASS|`4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`|
|Federal Register|1.0.14|9/9PASS|`b379d69b3ac505d5f1f1ae255896acb2b5f0d866`|
|Regulations.gov|2.0.6|9/9PASS|`c0553538fca43e13a8c7db5a6ecd77a887303c32`|

The45checks combine actual publicGET/POST routing headers, originHTTPSGEThealth and authenticatedSSH container-local HTTP initialization/health. Physical backend identity is established separately from public routing; no originHTTPSPOST initialization is claimed. Independent Regulations and SAM reviews reconcile allfive results with the exact final matrix. An initial helper invocation from the wrong directory failed before requests; the corrected invocation from the integration repository produced the actual passing record. This excluded local harness attempt is preserved, not counted as a deployment defect or a passed check.

Production Per Diem D1 remains complete with43,665rows, release `ba0994b637ca8ae7`, places `2dee3470caca1a82` and allseven fiscal-year parts unchanged; actual SELECT-only inspection wrote zero rows. SAM retains64,417versions/46,083latest notices and its acceptedCSV identity. BLS retains May2025 bundle identity. No Round5 reload was required; fresh source comparisons and earlier applicable reload evidence remain explicit.

### Cumulative ledger through accepted Round5 content fixes

| MCP/shared owner | P0 | P1 | P2 | P3 | Fully fixed | Partial | Unresolved content |
|---|---:|---:|---:|---:|---:|---:|---:|
|SAM.gov|0|0|3|5|8|0|0|
|USAspending|0|0|8|7|15|0|0|
|eCFR|0|1|9|3|13|0|0|
|Federal Register|0|0|2|1|3|0|0|
|Regulations.gov|0|0|5|1|6|0|0|
|GSA CALC+|0|1|4|2|7|0|0|
|GSA Per Diem|0|0|3|5|8|0|0|
|BLS OEWS|0|0|4|1|5|0|0|
|Shared documentation|0|0|1|0|1|0|0|
|**Total**|**0**|**2**|**39**|**25**|**66**|**0**|**0**|

Independent Per Diem review reconciles this ledger with retained finding evidence and published acceptance. Fresh-suite failures remain unresolved test-lane observations; they are not erased or silently counted as content fixes. Round5 found one new P2, so a further complete eight-server audit is required after this round is fully closed. Acquisition.gov remains excluded.
