# Regulations.gov MCP publication

Publisher: James Prentiss Jenrette (individual). Brand: 1102tools.

Endpoint: https://regulations-gov.1102tools.com/mcp
Transport: Streamable HTTP (stateless, JSON responses).
Authentication: none. Users need no account or API key. Every data call goes to the Regulations.gov v4 API with a publisher key held as a Cloudflare Worker secret and sent in the `X-Api-Key` header; the hosted server refuses to start without it.
Support: https://regulations-gov.1102tools.com/support
Privacy: https://regulations-gov.1102tools.com/privacy
Terms: https://regulations-gov.1102tools.com/terms
Source: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/regulations-gov-mcp
Category: Government / legal and regulatory.

Status: prepared, **not ready to submit**. 2.0.0 is released and verified in production (tag `regulations-gov/v2.0.0`, commit `0691651`, 2026-09-26). Resolve every item under "Open before submission" first.

## Open before submission

1. **Third-party API eligibility (both portals). This is the highest risk for this service.** OpenAI does not approve plugins that primarily act as unofficial pass-through connectors, and this service is a key-backed relay of the public Regulations.gov API with workflow tools on top. Anthropic's policy section 3(F) asks developers to verify control of the API endpoints their software connects to; 1102tools controls `regulations-gov.1102tools.com`, not `api.regulations.gov`. Do not attest ownership or control of government endpoints. Ask each platform, or GSA's eRulemaking Program, how these rules apply before accepting the attestation. The statement below describes the service's own functionality.
2. **OpenAI demo recording URL.** Record the principal tools (document search, docket detail, open comment periods with paging, FAR case history) on production 2.0.0.
3. **OpenAI domain verification.** The portal issues the `/.well-known/openai-apps-challenge` token; add it to `deploy/regulations-gov/src/public-docs.ts` and release.
4. **Production tool scan** in each portal after the final deployment.
5. **Capacity and origin testing** through each platform's connector: cold start, representative concurrency, p95 latency, 429/503 counts, and use of the 950-per-hour upstream budget. The Worker rejects a cross-origin `Origin` header (403 for `https://claude.ai` and `https://chatgpt.com` in the audit); server-side connector calls send none. Add allowed origins only if a supported client needs them. Measured directly on 2026-09-26 (not through a platform connector): 40 requests at 10 concurrent returned all 200 with no tool errors, p95 0.74 s; the service's own Origin returns 200.
6. **Cloudflare retention.** The privacy notice states Cloudflare's documented 7-day maximum for Workers Logs. Confirm the account has no Logpush or other log export before accepting a privacy attestation.
7. **Portal access.** Recheck on the publishing account that the Claude directory portal is open to it (announced September 25 for paid Claude plans).

Independent functionality (for eligibility questions): responses are compacted, with API aggregation lists replaced by the top facet counts and self-links removed. `open_comment_periods` makes one comma-joined query across the procurement agencies, sorted by soonest deadline, with honest totals and paging. `far_case_history` summarizes a docket, including docket-wide counts by document type and of documents open for comment, before its paged document list. Inputs are validated against the API's case-sensitive filters, and unknown agency codes return the agencies with the most records. The service uses a registered api.data.gov key under api.data.gov's terms.

## Listing copy

Name: Regulations.gov by 1102tools

OpenAI short description (≤30): Federal rulemaking research

One-liner (≤200): Search federal rulemaking on Regulations.gov: dockets, proposed and final rules, public comments, open comment periods, and FAR case histories.

Description (≤2,000):
Research federal rulemaking through the official Regulations.gov API. Search dockets, documents (proposed rules, final rules, notices, supporting materials), and public comments by agency, keyword, docket, and date; open a docket, document, or comment for its details and attachment links; list documents open for comment now, soonest deadline first; and trace a FAR or DFARS case from a docket summary to its latest action.

Built for acquisition and regulatory work: agency codes such as FAR, DARS, and GSA are first-class, and results report the true match count and return long lists a page at a time. Results name the document, docket, and comment IDs to cite, and link to the public pages on Regulations.gov.

Read-only: the service cannot submit comments or change anything on Regulations.gov. Data is public; material withheld from the public docket (for example confidential business information) is not available. Results may be up to 15 minutes old. Independent service, not endorsed by GSA or any agency.

## Tools and annotation justifications

The server publishes no `instructions`. Public search tools return at most 100 rows per page, and the two workflow tools default to 25 (maximum 100). Results carry compact facet counts instead of the API's full aggregation lists.

| Tool | `readOnlyHint: true` | `destructiveHint: false` | `openWorldHint` |
|---|---|---|---|
| search_documents | Returns matching public documents. | Creates, changes, or deletes nothing, locally or on Regulations.gov. | `true`: queries the Regulations.gov API. |
| get_document_detail | Returns one public document. | No side effects. | `true`: Regulations.gov API. |
| search_comments | Returns matching public comments. | No side effects. | `true`: Regulations.gov API. |
| get_comment_detail | Returns one public comment. | No side effects. | `true`: Regulations.gov API. |
| search_dockets | Returns matching public dockets. | No side effects. | `true`: Regulations.gov API. |
| get_docket_detail | Returns one public docket. | No side effects. | `true`: Regulations.gov API. |
| open_comment_periods | Lists open documents, one page per call. | No side effects. | `true`: one Regulations.gov API call per page. |
| far_case_history | Returns a docket summary and one page of its documents. | No side effects. | `true`: two Regulations.gov API calls (docket and documents). |
| get_access_status | Reports credential presence without the value. | No side effects. | `false`: reads local configuration only. |

## Starter prompts

1. Which FAR rules are open for public comment right now?
2. Give me the history of FAR case docket FAR-2023-0008.
3. Find recent GSA dockets on Regulations.gov.

## Review test cases

Positive:
1. "Search Regulations.gov for proposed rules about cybersecurity from the FAR Council." → `search_documents` (agency FAR, Proposed Rule) → FAR-2019-0014, FAR-2021-0017, FAR-2021-0019 among results.
2. "What is docket FAR-2023-0008 about?" → `get_docket_detail` → FAR Case 2023-008, Prohibition on Certain Semiconductor Products and Services, RIN 9000-AO56.
3. "Show me a few public comments on docket FAR-2023-0008." → `search_comments` (docket) → recent comments with IDs and submitters.
4. "Which DoD (DARS) documents are currently open for comment?" → `open_comment_periods` (DARS) → open documents with deadlines, soonest first, with `next_page_number` when more exist.
5. "Give me the history of FAR case docket FAR-2023-0008." → `far_case_history` → docket summary with counts by document type, then the documents from the 2024 notice to the 2026 proposed rule.

Negative:
1. "Submit a public comment on docket FAR-2023-0008 saying I support the rule." → declined: read-only tools; explains how to comment on Regulations.gov.
2. "Find documents from agency code XYZQ." → zero results explained; suggests real agency codes from `agency_codes_with_most_records`.
3. "Show me the confidential business information submitted in FAR-2023-0008." → declined: withheld from the public docket; points to FOIA.

## Verification record

Source 2.0.0 (branch `claude/directory-audit-fixes`, 2026-09-26): offline suite 122 passed, 119 live-gated skipped (241 collected); release guards 57 passed; shared pacing and admission 100 passed; `scripts/validate_versions.py` passed. `tools-contract.json` was regenerated under Python 3.12. Only `open_comment_periods` and `far_case_history` changed (new `page_size`/`page_number` inputs and descriptions); annotations are unchanged.
Live checks on 2026-09-26, before the DEMO_KEY fallback was removed: `X-Api-Key` header authentication returned 5 FAR dockets of 451. Default `open_comment_periods` returned 25 of 70 open documents with `next_page_number: 2` in 9,798 characters, down from 26,870 characters of structured content at 1.1.0; page 2 returned documents 26-50. The documents-search aggregations `far_case_history` summarizes (`documentType`, `withinCommentPeriod`) were confirmed live for FAR-2023-0008. `far_case_history` was then verified end to end, first on the release image with a registered key and then on production (FAR-2023-0008: 5 documents, 4 Proposed Rule and 1 Supporting & Related Material).
Mock directory review on 2026-09-26 (Claude Code 2.1.281, hosted 1.0.11, the 11 cases above) found gaps that 1.1.0 fixed: missing `openWorldHint`, oversized results, and key-setup wording shown to hosted users. **The cases have not been rerun on 1.1.0 or 2.0.0.** Say that they found defects that were fixed, not that the final release passed them.
Production 1.1.0 on 2026-09-26: `/health` ok at `001e536` with 9 tools; `scripts/check_hosted_health.py regulations-gov` passed.
Production 2.0.0 on 2026-09-26 (release run 36269434859, all jobs passed): `/health` ok, 9 tools, `0691651`; PyPI and the MCP Registry list 2.0.0; the health check passed; all 9 tools called on production returned results, with `get_access_status` reporting `hosted_publisher_key`; the new privacy notice is served.

## Remaining user steps

1. Resolve "Open before submission" above, and rerun the mock directory cases against production 2.0.0.
2. Test every tool on production in Claude (custom connector) and ChatGPT (Developer Mode).
3. OpenAI: create the plugin draft, enter the short description, listing copy, annotation justifications, test cases, starter prompts, demo URL, and icons from `review/assets/`. No screenshots (no UI).
4. Claude: submit at claude.ai/directory/manage with the listing copy, `docs/directory-icons/regulations-gov.png`, the three starter prompts, and the support/privacy URLs. On the data-handling step, state that the server relays the public Regulations.gov API with a registered api.data.gov key and does not control the Regulations.gov endpoint.
5. Review and accept each portal's attestations yourself.
