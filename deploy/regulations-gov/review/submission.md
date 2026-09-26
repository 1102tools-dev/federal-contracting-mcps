# Regulations.gov MCP publication

Publisher: James Prentiss Jenrette (individual). Brand: 1102tools.

Endpoint: https://regulations-gov.1102tools.com/mcp
Transport: Streamable HTTP (stateless, JSON responses).
Authentication: none. Users need no account or API key. Every data call goes to the Regulations.gov v4 API with a publisher key held as a Cloudflare Worker secret; the hosted server refuses to start without it.
Support: https://regulations-gov.1102tools.com/support
Privacy: https://regulations-gov.1102tools.com/privacy
Terms: https://regulations-gov.1102tools.com/terms
Source: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/regulations-gov-mcp
Category: Government / legal and regulatory.

Status: prepared, not submitted. Requires package 1.1.0 deployed (health `release_sha` equal to the release commit; `get_access_status` reports `hosted_publisher_key`) before any portal scan.

## Listing copy

Name: Regulations.gov by 1102tools

One-liner (≤200): Search federal rulemaking on Regulations.gov: dockets, proposed and final rules, public comments, open comment periods, and FAR case histories.

Description (≤2,000):
Research federal rulemaking through the official Regulations.gov API. Search dockets, documents (proposed rules, final rules, notices, supporting materials), and public comments by agency, keyword, docket, and date; open a docket, document, or comment for its details and attachment links; list documents open for comment now, soonest deadline first; and trace a FAR or DFARS case from its first notice to its latest action.

Built for acquisition and regulatory work: agency codes such as FAR, DARS, and GSA are first-class, and results report the true match count so large searches can be split by date. Results name the document, docket, and comment IDs to cite, and link to the public pages on Regulations.gov.

Read-only: the service cannot submit comments or change anything on Regulations.gov. Data is public; material withheld from the public docket (for example confidential business information) is not available. Results may be up to 15 minutes old. Independent service, not endorsed by GSA or any agency.

## Tools and annotations

Every tool is read-only (`readOnlyHint: true`) and non-destructive (`destructiveHint: false`).

| Tool | openWorldHint | Reason |
|---|---|---|
| search_documents, get_document_detail | true | Regulations.gov API |
| search_comments, get_comment_detail | true | Regulations.gov API |
| search_dockets, get_docket_detail | true | Regulations.gov API |
| open_comment_periods, far_case_history | true | Regulations.gov API (several calls) |
| get_access_status | false | Reports local configuration only |

The server publishes no `instructions`. Public search results are capped at 100 rows per page (about 70K characters worst case) and carry compact facet counts instead of the API's full aggregation lists.

## Starter prompts

1. Which FAR rules are open for public comment right now?
2. Give me the history of FAR case docket FAR-2023-0008.
3. Find recent GSA dockets on Regulations.gov.

## Review test cases

Positive:
1. "Search Regulations.gov for proposed rules about cybersecurity from the FAR Council." → `search_documents` (agency FAR, Proposed Rule) → FAR-2019-0014, FAR-2021-0017, FAR-2021-0019 among results.
2. "What is docket FAR-2023-0008 about?" → `get_docket_detail` → FAR Case 2023-008, Prohibition on Certain Semiconductor Products and Services, RIN 9000-AO56.
3. "Show me a few public comments on docket FAR-2023-0008." → `search_comments` (docket) → recent comments with IDs and submitters.
4. "Which DoD (DARS) documents are currently open for comment?" → `open_comment_periods` (DARS) → open documents with deadlines.
5. "Give me the history of FAR case docket FAR-2023-0008." → `far_case_history` → timeline from the 2024 notice to the 2026 proposed rule.

Negative:
1. "Submit a public comment on docket FAR-2023-0008 saying I support the rule." → declined: read-only tools; explains how to comment on Regulations.gov.
2. "Find documents from agency code XYZQ." → zero results explained; suggests real agency codes from `agency_codes_with_most_records`.
3. "Show me the confidential business information submitted in FAR-2023-0008." → declined: withheld from the public docket; points to FOIA.

## Verification record

Offline suite: 117 passed (236 collected; live-gated tests skipped). Release guards: 45 passed.
Mock directory review on 2026-09-26 (Claude Code 2.1.281, hosted 1.0.11, 11 cases above): all behaved as expected. 1.1.0 then fixed the gaps it found: missing `openWorldHint`, oversized results (a 250-row page was 217K characters), and key-setup wording shown to hosted users.
Local hosted entry point with `REGULATIONS_HOSTED=1` passed `scripts/verify_hosted_release.py regulations-gov` (publisher-key mode, live upstream calls, compacted results) and refuses to start without the key.
Production checks: pending deployment.

## Remaining user steps

1. Merge, then push tag `regulations-gov/v1.1.0` (scoped release).
2. Confirm the workflow's production verification passed and the scheduled health check is green.
3. Test every tool on production in Claude (custom connector) and ChatGPT (Developer Mode).
4. OpenAI: create the plugin draft, obtain the domain-challenge token, add it to `deploy/regulations-gov/src/public-docs.ts` as `/.well-known/openai-apps-challenge`, release, then enter the listing copy, test cases, starter prompts, and icons from `review/assets/`. No screenshots (no UI).
5. Claude: submit at claude.ai/directory/manage with the listing copy, `docs/directory-icons/regulations-gov.png`, the three starter prompts, and the support/privacy URLs. On the data-handling step, state that the server proxies the public Regulations.gov API with a registered api.data.gov key.
6. Review and accept each portal's attestations yourself.
