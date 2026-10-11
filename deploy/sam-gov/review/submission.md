# SAM.gov MCP (hosted) publication

Publisher: James Prentiss Jenrette (individual). Brand: 1102tools.

Endpoint: https://sam.1102tools.com/mcp
Transport: Streamable HTTP (stateless, JSON responses).
Authentication: none. Users need no account or API key, and the service holds no SAM.gov key: every tool answers from Cloudflare D1 copies of the Contract Opportunities, Entity Registration/Public V2, and Exclusions/Public V2 files that SAM.gov publishes for public download. No request reaches SAM.gov or any other third party.
Support: https://sam.1102tools.com/support
Privacy: https://sam.1102tools.com/privacy
Terms: https://sam.1102tools.com/terms
Source: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/deploy/sam-gov
Documentation: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/sam-gov-mcp
Category: Data & Analytics.

Status: **Claude: approved and listed October 6, 2026** at https://claude.ai/directory/sam-gov-by-1102tools. ChatGPT: in review.

Earlier status: deployed 2026-09-27 (Worker `sam-gov-mcp`, D1 `sam-gov-opportunities`). The nightly load (`.github/workflows/sam-opportunities-load.yml`, 10:15 UTC) mirrors SAM.gov's daily file: it adds new notices, updates changed ones and deletes the ones SAM.gov archives.

## Open before submission

1. **Icons: done.** `review/assets/sam-gov-directory-{light,dark}.png` (512 px) and `sam-gov-composer-{light,dark}.png` (256 px) are independent 1102tools art (a notice with a magnifier), not the SAM.gov or GSA logo. The Claude form's single icon URL uses `docs/directory-icons/sam-gov.png` (light). Editable SVGs are in `Workspace/Artifacts/1102tools-samgov-logo/`.
2. **Production tool test (Claude Code CLI): done 2026-09-27**, 9/9; see the verification record.
3. **claude.ai custom connector test: not yet run.**
4. ~~**Public copy:** the README badge, the SAM.gov README and 1102tools.com still say the hosted edition is "coming soon". Switch them once the listing is live.~~ Done October 6, 2026.
5. **Portal attestations.** API ownership: the service calls no API. It serves copies of SAM.gov's public download files. Answer the data-source question that way, and do not attest control of SAM.gov systems.

## Listing copy

Name: 1102tools for SAM.gov (Claude slug `sam-gov-by-1102tools`)

One-liner (≤200): Search SAM.gov contract opportunities, public entity registrations, and exclusions without an API key

Description (≤2,000):
Search the federal contract opportunity notices published on SAM.gov: solicitations, combined synopses, presolicitations, sources sought, special notices, award notices and justifications. Search keywords across titles and full descriptions, and filter by NAICS or PSC code or prefix, set-aside, notice type, agency, place-of-performance or contracting-office state, solicitation number, and posted or response-deadline dates. Read one notice in full, with its description, deadline, set-aside, contracting office, points of contact, award details for award notices, related notices under the same solicitation, and the public sam.gov link. Count notices by agency, office, NAICS, PSC, set-aside, notice type, state or posted month. Look up public entity registrations by UEI or CAGE, or search by name, NAICS, state, business/SBA certification codes, and active registration status. Check exclusions by UEI, CAGE, or name. Use six read-only tools, with no account or API key.

Answers come from SAM.gov's public files: Contract Opportunities and Exclusions/Public V2 are published daily, Entity Registration/Public V2 monthly. The service checks daily for newer files. Entity and exclusion answers report the source file name and date. Entities that opted out of public display are not included in the hosted public mirror; a missing result does not establish that an entity is unregistered. Confirm current registration status on SAM.gov before relying on a result. By default, results show only the latest version of each amended notice and leave out notices whose response deadline has passed. Archived notices and attachments are not included; each result links to the notice on sam.gov.

This independent 1102tools integration is not a federal agency service and does not alter government records.

## Tools and annotation justifications

The server publishes no `instructions`. Every tool is `readOnlyHint: true`, `destructiveHint: false` and `openWorldHint: false`: it reads the service's own database and reaches no outside system.

| Tool | What it returns |
|---|---|
| search_opportunities | Active notices matching keywords and filters, soonest deadline first (or newest, or best keyword match), up to 100 per call with a total count and paging |
| get_opportunity | One notice in full by notice ID or solicitation number, plus related notices under the same solicitation |
| summarize_opportunities | Notice counts grouped by agency, sub-tier, office, NAICS, PSC, set-aside, notice type, state or posted month, with the same filters as search |
| search_entities (Search Entities) | Public registrations by UEI or CAGE, or matching name, NAICS, state, business/SBA certification codes, and active status, with source file name/date and registration/public-display caveats |
| search_exclusions (Search Exclusions) | Public exclusions by UEI, CAGE, or name, with source file name and date |
| get_data_status | SAM.gov source file dates, names, load times, and row counts for all three datasets, plus active notice counts by type and the last opportunities load's changes |

## Starter prompts

1. Find open solicitations under NAICS 541512 due in the next two weeks.
2. What construction solicitations are open in Virginia right now?
3. Which agencies posted the most sources sought notices this quarter?
4. Find active public entity registrations in Virginia under NAICS 541512 and show the source file date.
5. Check public exclusions for UEI [UEI], and show the source file name and date.

## Use cases (form)

1. **Find open work.** List open solicitations for a NAICS or PSC code, set-aside or agency, sorted by response deadline.
2. **Read a notice properly.** Pull one notice's full description, deadline, contacts and related amendments or award by notice ID or solicitation number.
3. **Size the market.** Count active notices by agency, set-aside, NAICS, notice type or month to see who is buying what.
4. **Research public registrations.** Look up UEI or CAGE identifiers and shortlist entities by NAICS, state, business/SBA certification codes, and active registration status. Confirm current registration on SAM.gov before relying on results.
5. **Check exclusions.** Search dated public exclusion records by UEI, CAGE, or name, then verify material findings on SAM.gov.

Prerequisites: None. No account, sign-in, or API key is needed.
Capability: Read only.

## Review test cases

Setup: add `https://sam.1102tools.com/mcp` as a custom connector with no authentication. Source files change on daily or monthly schedules, so the expected results describe what to look for rather than fixed counts, except for stable long-deadline notices.

Positive:
1. "How current is the SAM.gov data?" → `get_data_status` → source file names/dates and row counts for opportunities, entities, and exclusions; entity freshness reflects the monthly source schedule.
2. "Pull solicitation DARPA-PA-26-08 and summarize it." → `get_opportunity` (solicitation_number) → DARPA Research Solutions Opening, response deadline 2027-06-01, NAICS 541715, full description and contacts, sam.gov link.
3. "Find open solicitations and combined synopses under NAICS 541512 due in the next 14 days." → `search_opportunities` with `notice_types` [Solicitation, Combined Synopsis/Solicitation], `naics_codes` [541512] and a deadline range → notices sorted by deadline, each with agency, deadline, set-aside and link.
4. "Which agencies posted the most sources sought notices since July 1?" → `summarize_opportunities` (group_by agency, notice_types [Sources Sought], posted_from) → Department of Defense first, with counts and a total.
5. "Find open opportunities that mention zero trust." → `search_opportunities` (keywords `"zero trust"`) → matches from titles or full descriptions.
6. "What construction solicitations are open in Virginia?" → `search_opportunities` (place_of_performance_state VA, NAICS 23) → matches, plus a note on how many more have a Virginia contracting office, which the client may follow with `office_state`.
7. "Find award notices under NAICS 236220 posted in the last 7 days." → `search_opportunities` (notice_types [Award Notice], posted_from) → awardee, amount, award date and link for each.

8. "Find active public entity registrations in Virginia under NAICS 541512." → `search_entities` → matching registrations, source file name/date, public-display limitation, and instruction to confirm current registration on SAM.gov.
9. "Check public exclusions for UEI [a real public extract UEI]." → `search_exclusions` → matching exclusion records and source file name/date.

Negative (expected explanation, no invented notices):
1. "Show opportunities archived in 2019." → no tool result can supply them. The client explains that archived notices aren't included.
2. "Get notice 00000000000000000000000000000000." → `get_opportunity` → `found: false`, with a pointer to check sam.gov.
3. `search_opportunities` with `sort: relevance` and no keywords → a tool error explaining that relevance sorting needs keywords.
4. A public entity lookup with no match → no registration invented; explain that opted-out entities are not included in the hosted public mirror and direct the user to confirm on SAM.gov.

## Verification record

- **Build (PRs 1102tools-dev/federal-contracting-mcps#28, #29, merged 2026-09-27):**
  - Loader pytest: 10 passed.
  - Worker `node:test` over `node:sqlite` with the production schema: 17 passed.
  - `tsc` and the `tools-contract.json` check passed, as did a `wrangler deploy --dry-run`.
- **First load 2026-09-27:** SAM.gov file of Sep 26, 71,507 active notice rows (47,936 latest versions), with 12,187 rows past their archive date skipped. The first GitHub Actions nightly run succeeded, and a rerun on the same file changed 0 rows.
- **Production:**
  - `/health` ok with 4 tools. `/support`, `/privacy` and `/terms` return 200.
  - A cross-origin `Origin` header is rejected with 403, and GET `/mcp` returns 405.
  - Tool calls take 100–400 ms.
- **Connector test 2026-09-27:** Claude Code CLI 2.1.281 with the connector installed at user scope (headless, SAM.gov tools only, no web or shell): 9/9 passed. The 9 prompts were the seven positive cases above, the archived-2019 negative, and a NAICS 541511 sources sought search with deadline flags. There were no tool errors.
