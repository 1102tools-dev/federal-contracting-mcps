# October 10, 2026 MCP content audit and release record

**Rounds 1 and 2: all43 cumulative findings fully fixed; actual PyPI, Cloudflare, all-five Dell, applicable data and published website checks passed.** This record distinguishes executed checks, collected tests and source limitations. Round2 found five newP2 issues, so the zero-new-P0/P1/P2 stopping condition remains unmet. Round3 starts only after this record's final GitHub publication is verified. Evidence paths are relative to `Artifacts/mcp-e2e-20261010/`.

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

Round 3 covered the same eight servers; Acquisition.gov remains excluded. All eight owners completed new ordinary-user and power-user content coverage and independent reviews. Nine new findings were confirmed: **P0=0, P1=0, P2=6, P3=3**. Source PRs [116](https://github.com/1102tools-dev/federal-contracting-mcps/pull/116), [117](https://github.com/1102tools-dev/federal-contracting-mcps/pull/117), [118](https://github.com/1102tools-dev/federal-contracting-mcps/pull/118), [119](https://github.com/1102tools-dev/federal-contracting-mcps/pull/119), [120](https://github.com/1102tools-dev/federal-contracting-mcps/pull/120) and [121](https://github.com/1102tools-dev/federal-contracting-mcps/pull/121) merged. Five scoped package releases use frozen source `7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336`; all five package, Cloudflare and automated registry workflows succeeded sequentially. Final content and documentation acceptance remains pending in this working draft.

| Server | New P0 / P1 / P2 / P3 | Corrected ordinary-user behavior | Final target |
|---|---:|---|---|
| SAM.gov | 0 / 0 / 0 / 1 | Summary discovery permits older active notices while explaining incomplete historical coverage. | Python 1.0.13 unchanged; native mirror 1.0.3, source `0d87bdcf9d0c645428a57271736e4c35891bca53` already live. |
| USAspending | 0 / 0 / 1 / 0 | Grouped subaward totals explicitly cover the full prime record; fiscal filters select primes. Date-filtered, fully paged subaward followups recover reported subaward amounts for the requested dates; these do not establish a global subaward ranking or net-new spending. | 1.0.17 |
| GSA CALC+ | 0 / 0 / 1 / 0 | Fresh MCP 2.3 installations preserve anticipated unsupported-worksite recovery guidance instead of a generic error. | 1.0.15 |
| BLS OEWS | 0 / 0 / 0 / 0 | No new defects in 58 realistic questions, 431 measure/benchmark objects and 28 current official source cells. | 1.1.4 unchanged |
| GSA Per Diem | 0 / 0 / 1 / 1 | Correct UTF-8 county geography and accent normalization resolve Doña Ana/White Sands; registry setup guidance correctly permits bundled keyless city-plus-county workflows. | 1.2.4 |
| eCFR | 0 / 0 / 2 / 1 | History groups by section and sorts dates before pagination; catalog explains older history; available pre-2017 text comparisons work, with source-specific unavailable-date recovery. | 1.1.5 |
| Federal Register | 0 / 0 / 0 / 0 | No new defects in 54 realistic public/installed-CLI questions and current primary-source comparisons. | 1.0.14 unchanged |
| Regulations.gov | 0 / 0 / 1 / 0 | Provider closing timestamps are qualified source metadata; users follow controlling notices, eligibility conditions and later extensions before relying on a deadline. | 2.0.5 |

The eCFR result supersedes any earlier universal 2017 snapshot floor claim: actual 36 CFR 1194.1 text exists for December 13, 2016. Older availability depends on the title and section. Regulations.gov's provider conflict remains a disclosed source limitation; the corrected application no longer presents the raw timestamp as an established controlling deadline. The OSHA notice's October 30, 2025 extension applies to timely NOITA filers. Direct credentialed provider checks remain unavailable under quota/key constraints; captured-provider adapter checks are not claimed as live keyed CLI calls.

### Independent regression inventory

At frozen source `7e8c4132`, an independent coordinator collection measured **6,064 product package tests**, including Acquisition's 255, and **5,809 for the eight-server goal**. All nine collection commands exited successfully. These are collected tests, not an all-passed claim. Worker, loader, contract, parity, current-source and realistic-content checks are separate lanes.

| Server | Collected | Saved complete offline lane: passed / skipped | New content coverage |
|---|---:|---:|---|
| SAM.gov | 1,155 | 781 / 374 (earlier execution) | 110 final public/source comparisons, 345 raw row checks; actual fresh Python CLI catalog/access verification. Nineteen keyed workflows unexecuted without SAM_API_KEY. |
| USAspending | 2,306 | 1,927 / 379 | 130 new cases across all 55 tools, 134 source captures; date-filtered followups. |
| GSA CALC+ | 435 | 314 / 121 | 132 registered-tool and public cases, 3,200 source/workflow assertions; original errors and corrected followups separately through actual stdio. Registered calls are not all stdio calls. |
| BLS OEWS | 298 | 297 / 1 | 58 actual fresh published CLI and public calls; 28 official source cells. |
| GSA Per Diem | 583 | 316 / 267 | 101 realistic cases; 98 primary numeric checks after the two corrections, 18 ZIP memberships. Two no-key workflows are expected guidance, not successful API source calls. |
| eCFR | 451 | 333 / 118 | Candidate 80 actual CLI calls / 83 source checks; final published rerun pending. |
| Federal Register | 286 | 181 / 105 | 54 actual fresh published CLI/public/source cases; four complete agency deadline sets and four inspected source texts. |
| Regulations.gov | 295 | 176 / 119 | 115 public calls, 110 comparison rows and 70 primary captures (68 JSON plus two XML); four occurrences of one OSHA conflict qualified, with the linked controlling-notice workflow verified; two agenda dates unverified. |

Root version consistency passed for all nine packages after refreshing stale local editable installations; no runtime code change was needed for that local environment repair. All nine wheel/sdist builds and published-payload guards passed. The unchanged versions matched official PyPI payloads; five corrected versions were confirmed new. All 67 release guard regressions passed. Individual source PR CI and independent peer reviews passed before publication.

### Applicable production data reload

GSA Per Diem serves its public route from a native Worker and D1. A retained container configuration does not establish the active request backend. Automatic atomic loader [38074915107](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38074915107) succeeded after the merged bundle change. An actual remote production D1 query independently confirmed release `ba0994b637ca8ae7`, places part `2dee3470caca1a82`, complete flag 1 and **43,665 actual rows**, loaded `2026-10-10T18:13:46Z`. Corrected `NM|dona ana` and `NM|white sands` mappings are present. All seven fiscal-year parts remain unchanged. Evidence: `coordinator/gpd-round3-actual-d1.json`. Package/native deployment and original $396 two-night estimate acceptance remain pending in this working draft.

SAM mirror 1.0.3 deployment `1b4b44a6-95eb-416e-992b-788d69afa06f` is live at source `0d87bdcf9d0c645428a57271736e4c35891bca53`: all 110 final realistic questions plus status passed against the fresh official CSV. Python 1.0.13, its data loader and schema are unchanged. Status retains 64,417 active notices / 46,083 latest versions and `2026-10-10T15:52:32Z` load time.

**Round 3 closure remains pending** until all five sequential package workflows, actual fresh installed published content, final eight-server identity matrix, all five physical Dell origins, automatic registry metadata, published GitHub docs and website acceptance pass. Round 4 is required because this round found new P2 issues, and will start only after those gates close. No manual directory republication is required for these compatible corrections; registry publication and unobserved client directory review remain distinct.


### Cumulative ledger through confirmed round-3 findings

This table counts each confirmed finding once. Its nine round-3 findings include one already published and verified SAM correction and eight merged corrections awaiting final published acceptance in this working draft; it does not label merged-only fixes fully shipped. The earlier 43 findings remain fully fixed. Acquisition's separate five findings are excluded.

| MCP / shared owner | P0 | P1 | P2 | P3 | Total confirmed |
|---|---:|---:|---:|---:|---:|
| SAM.gov | 0 | 0 | 2 | 4 | 6 |
| USAspending | 0 | 0 | 6 | 3 | 9 |
| eCFR | 0 | 1 | 7 | 3 | 11 |
| Federal Register | 0 | 0 | 2 | 1 | 3 |
| Regulations.gov | 0 | 0 | 4 | 0 | 4 |
| GSA CALC+ | 0 | 1 | 3 | 1 | 5 |
| GSA Per Diem | 0 | 0 | 3 | 5 | 8 |
| BLS OEWS | 0 | 0 | 4 | 1 | 5 |
| Shared documentation | 0 | 0 | 1 | 0 | 1 |
| **Total** | **0** | **2** | **32** | **18** | **52** |


### Round-3 publication and actual backend acceptance

All five scoped releases completed successfully at frozen source `7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336`, with no overlapping or replaced release runs:

| Scoped tag | Successful workflow | Cloudflare Worker deployment UUID |
|---|---|---|
| gsa-perdiem/v1.2.4 | [38075460793](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38075460793) | `2f637dc9-eea4-43b7-9632-8e471fb406a4` |
| gsa-calc/v1.0.15 | [38075712974](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38075712974) | `3fbb9010-0395-4560-8c47-13baf47a7743` |
| ecfr/v1.1.5 | [38076027377](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076027377) | `92925fb3-a4db-44c5-a2b5-b5202d88ad95` |
| usaspending/v1.0.17 | [38076343015](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076343015) | `6ab00396-e9e6-4951-96a2-059343201cb5` |
| regulations-gov/v2.0.5 | [38076645801](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076645801) | `3a91c410-cb7a-4214-a6f9-b48defda9924` |

Root actual final acceptance passed for all eight public health/source/version identities, absence of unexpected server instructions, and all **112 exact tool definitions**. Unchanged Federal Register remains `b379d69b3ac505d5f1f1ae255896acb2b5f0d866` / 1.0.14; BLS remains `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f` / 1.1.4; SAM retains its independent `0d87bdcf9d0c645428a57271736e4c35891bca53` / mirror 1.0.3. These are explicit per-service identities, not a single uniform SHA assertion. Evidence: `coordinator/eight-server-round3-final-contracts.json`.

Root independently downloaded **16 actual official wheel/sdist artifacts for all eight goal packages** and verified published version, byte count, official SHA-256 and non-yanked status. Expected-version checkout provenance is distinct from an assertion that unchanged artifacts were rebuilt at the new release SHA. Evidence: `coordinator/round3-pypi-artifacts.json`.

**All five configured Dell origins passed 45 actual checks.** USAspending 1.0.17, eCFR 1.1.5, CALC+ 1.0.15 and Regulations.gov 2.0.5 use the frozen new source SHA; unchanged Federal Register 1.0.14 uses `b379d69b3ac505d5f1f1ae255896acb2b5f0d866`. For each service, public GET health and POST initialization returned `x-1102tools-backend: origin`, the HTTPS origin reported the expected health identity, and SSH-authenticated direct physical-container health and initialization verified the matching SHA/version and no unexpected instructions. No backend conclusion relies solely on retained configuration. Evidence: `coordinator/dell-round3-final-verified.json`.

Brief official simple-index propagation delays affected initial fresh by-name installs; bounded retries used only official PyPI and retained the failed attempts. No candidate wheel was substituted. Final content acceptance remains separate from these publication and routing gates.
