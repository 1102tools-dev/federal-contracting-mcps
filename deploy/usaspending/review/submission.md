# USAspending MCP submission draft

Status: deployed public pilot; all 55 tools passed production smoke tests. OpenAI draft created, identity and domain verified, and 55 tools scanned. Not submitted for review.

- Publisher: James Prentiss Jenrette (verified individual); 1102tools branding
- Name: USAspending MCP
- Short description: Explore federal spending
- Submission type: With MCP; no custom UI or uploaded skills
- Endpoint: https://usaspending.1102tools.com/mcp
- Authentication: none; public data, no user API key
- Source: https://api.usaspending.gov
- Website: https://1102tools.com
- Support URL: https://usaspending.1102tools.com/support
- Privacy URL: https://usaspending.1102tools.com/privacy
- Terms URL: https://usaspending.1102tools.com/terms
- Tool surface: all 55 existing USAspending tools

## Description
Explore publicly reported federal awards, recipients, agencies, spending trends, geography, subawards, IDVs, and federal accounts. Retrieve source data through 55 read-only tools. Results reflect USAspending's reporting coverage and update schedule. This independent 1102tools integration is not a federal agency service and does not alter government records.

## Annotation rationale
All tools read public USAspending data. Set readOnlyHint=true, destructiveHint=false, and openWorldHint=true. Server operational logs and pacing state do not create or change a user's business records. No tools submit awards, change recipients, or initiate export jobs.

## Starter prompts
1. Find FY2025 software contracts and show the largest awards with award identifiers.
2. Compare Health and Human Services contract obligations by fiscal year.
3. Look up a recipient and trace its awards, transactions, and funding.

## Positive review cases
1. Search software contracts in FY2025, limit 5. Expect search_awards, contract records with award IDs and pagination; preserve missing data.
2. Retrieve an award from case 1 and its transactions. Expect get_award_detail and get_transactions, matching the selected generated ID.
3. Find Health and Human Services and its FY2025 spending. Expect agency lookup then get_agency_overview and agency award/budget tools; do not confuse budget resources with contract obligations.
4. Find a recipient by name and retrieve its profile. Expect search_recipients followed by get_recipient_profile using the returned ID; disambiguate similar names.
5. Compare FY2025 contract spending by geography and category. Expect spending_by_geography and spending_by_category with matching dates and award types; label the measure and geographic scope.

## Negative review cases
1. Ask to delete or change a federal award. Explain that this integration only reads public data; no write tool exists.
2. Send an unknown argument or malformed identifier. Expect schema/validation error; do not silently ignore the argument or return an unfiltered success.
3. Simulate provider failure or capacity exhaustion. Expect a clear error or HTTP 429/503/504 and retry guidance; never represent unavailable data as zero.

## Release notes
Initial remote pilot of the existing 55-tool USAspending server. Adds stateless Streamable HTTP, explicit external-data annotations, request guards, bounded concurrency, and a Cloudflare container deployment. Existing stdio command remains available.

## Portal work still required
Verify publisher identity and Apps Management permission. Generate the domain challenge in the portal and host its exact token. Scan the production endpoint, address findings, run the review cases in a supported client, record the actual demo, and submit accurate attestations. Approval and publication remain separate portal events.

## Portal progress September 7

Draft: https://platform.openai.com/plugins/edit/asdk_app_6a9ee668cc248191a0bdb9911b546799/asdk_app_v_6a9ee669edd4819183ddd827ce25e6fe

Saved listing, verified individual publisher, Data & Analytics category, public URLs, no-auth MCP connection, 165 annotation explanations, three starter prompts, five positive review scenarios, three negative routing examples, and release notes. Default availability remains all supported countries. The portal confirmed domain verification and discovered all 55 tools. No skills uploaded.

Demo recording: https://1102tools.com/downloads/usaspending-demo-2026-09-07.mp4. Public HTTP 200, video/mp4, byte-identical SHA-256 9d22647480b99198b62859c3e2f572c1a2548a21bb0d982ded75d91209eb2cde; browser playback and complete decode verified. Light/dark directory and composer icons uploaded. Test case 5 uses PSC 7030 with identical FY2025 contract filters. Outstanding: final user-reviewed policy attestations. No attestations accepted and no submission sent. Negative portal examples are award-record modification, personal bank-budget analysis, and current SAM solicitations/bid submission; the error-handling tests above remain engineering coverage rather than negative routing examples.

## Submission attempt September 7

User explicitly approved all final attestations and Submit for Review. All seven policy checkboxes and the no-adult-content selection persisted after refresh. Three submission attempts returned portal save errors (first Conflict, then Please retry the request). The plugin listing still showed version 1.0.0 as Draft. No successful submission or review-queue confirmation. Authorization remains granted; no need to ask again for the same submission.

## Review confirmed September 7

The user completed submission in the portal. Browser verification confirmed USAspending MCP version 1.0.0 status Review. Earlier save errors are resolved; review approval and publication remain pending.
