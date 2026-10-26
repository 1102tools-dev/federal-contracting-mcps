# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.0.17

The PyPI page now links to the hosted edition in the ChatGPT directory. Tools and answers are unchanged.

## 1.0.16

The PyPI page now links to this server's 1102tools page, and the MCP registry entry lists the hosted endpoint. Tools and answers are unchanged.

## 1.0.15

When an entity search or lookup finds nothing, the answer now says that SAM.gov lets registrants hide their record from public view, so no match does not mean the entity is unregistered. `vendor_responsibility_check` now flags `NO_PUBLIC_RECORD` instead of `NOT_REGISTERED` for the same reason.

## 1.0.14

Input mistakes (for example, award dates copied in the opportunity file's format, or a three-digit hierarchy agency code reused for assistance subawards) again return a specific message saying how to fix the request under MCP SDK 2.3. Tools and results are unchanged.

## 1.0.13

Fixes request pacing locks that could stay held, or be abandoned when a waiting request was cancelled. Pacing intervals are unchanged. See [issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10).

## 1.0.12

Debug logging no longer records request URLs that carry your SAM.gov key. Tools and results are unchanged.

## 1.0.11

Adds `get_access_status`, which checks whether `SAM_API_KEY` is set (without revealing it) before any SAM.gov data call. Missing-key, rejected-key, rate-limit and network failures now reach the AI as clear, actionable messages instead of a generic error. The SAM.gov key link now points to SAM.gov Help.

## 1.0.10

Published under the `com.1102tools/sam-gov-mcp` MCP Registry name, with project links moved to the `1102tools-dev` GitHub account. No tool behavior changed.

## 1.0.9

Your SAM.gov key is redacted from every error, upstream response and tool result the AI can see, including URL-encoded forms.

## 1.0.8

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.7

The missing-key message now names the `SAM_API_KEY` environment variable and points to your own app's MCP settings, instead of naming one specific desktop app. No tool behavior changed.

## 1.0.6

Every SAM.gov request, including those inside combined tools, is spaced 3 seconds apart per key by default, across processes. `Retry-After` is honored without automatic retries, and the 429 message no longer assumes your daily quota is used up.

## 1.0.5

The server now reports its real version number (1.0.4 had reported 1.0.2).

## 1.0.4

From a paced live campaign against SAM.gov:

- Contract Awards `fiscal_year` now reaches back to FY1970 (was 2008); two-digit years are rejected because the API silently returns nothing for them.
- `registration_status` accepts only A and E; D and I always returned zero records.
- API errors sent as HTTP 200 now raise errors instead of looking like empty results.
- Assistance subaward `agency_code` must be four digits (9700, not CGAC 075), with a clear message.
- Documented: `offset` is a zero-based page number on Opportunities and Contract Awards; Contract Awards stops paging at 400,000 records; Opportunities pages past the end return a stray record; Subaward pages past the end hang; a UEI can return more than one registration record.

The paced probe harness is in `tests/live_audit/`.

## 1.0.3

No code changes; republished to verify the publishing pipeline after the repository moved to the 1102tools-dev account.

## 1.0.2

- **Reps and certs fixed.** `get_entity_reps_and_certs` summary mode had returned empty FAR and DFARS clause lists for every entity because it read the wrong field names. It now returns the real answers.
- All 18 Opportunities set-aside codes are accepted, including LAS, IEE, ISBEE and BICiv.
- `business_type_code` accepts any well-formed two-character code from SAM.gov's data dictionary; SBA certification codes still redirect to `sba_business_type_code`.
- `purpose_of_registration` accepts Z1-Z5, with Z5 correctly labeled All Awards and IGT.
- Date ranges in Opportunities single-date fields are rejected with guidance instead of crashing.
- `lookup_award_by_piid` sorts modifications and notes when more than 100 exist.
- Leading zeros are kept: `zip_code=6511` searches 06511 and `cgac=75` searches 075.

## 1.0.1

Fixes the SBA certification code table (XX is HUBZone, A6 is 8(a); also JT, A4, A9 WOSB and A0 EDWOSB). Adds `sba_business_type_code` to `search_entities`, so 8(a) and HUBZone searches now work; passing an SBA code to `business_type_code` returns a message pointing to the new parameter.

## 1.0.0

First stable release. Requires MCP Python SDK 2.x (`mcp>=2.0.0,<3`); installs pinned to SDK 1.x should stay on the 0.x line. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip` or Docker. `lookup_psc_code` now explains that a retired PSC needs `active_only='ALL'` instead of calling it invalid. Supports Python 3.10 through 3.14.

## 0.4.0

Adds four tools (15 to 19): `search_federal_organizations`, `get_organization_hierarchy`, `search_acquisition_subawards` and `search_assistance_subawards`. Live testing caught three Subaward parameters whose documented casings SAM.gov silently ignores (`PIID`, `referencedIdvPIID`, `referencedIDVAgencyID`), which would have returned every subaward in the system; the server sends the working casings. `fh_org_type` accepts real values like `Department/Ind. Agency`. Subaward PIIDs with hyphens are rejected by SAM.gov itself, and that error is passed through. Wage determinations were evaluated and not added, because SAM.gov offers no public API for them.

## 0.3.7

Fixes two rare crashes found by property-based testing: an infinite or NaN record count, and an empty response from Contract Awards.

## 0.3.6

`search_exclusions` name searches now work; the server had sent `entityName`, which SAM.gov rejects, instead of `exclusionName`. Adds live tests for every tool.

## 0.3.5

Test-only release: broad input-validation coverage for every tool. No code changes.

## 0.3.1

- Company names with apostrophes and similar characters (McDonald's, L'Oreal, O'Brien) are no longer wrongly blocked; only null bytes and control characters are rejected.
- Misspelled parameter names now raise an error instead of being silently dropped (a typo had returned all 700,000+ entities).
- `lookup_award_by_piid` rejects an empty PIID.
- PSC "not found" responses now come with a readable explanation.

## 0.3.0

Hardening release: fixes crashes on unusual SAM.gov responses, adds input checks across all tools (UEI, CAGE, NAICS, dates, the 364-day Opportunities span, set-aside and business-type codes, state and country codes), and strips HTML from error messages. `get_entity_reps_and_certs` now returns a summary by default, with `clause_filter` and `summary_only=False` for full detail; this changes its default response shape.

## 0.2.0

Adds Contract Awards (the FPDS replacement): `search_contract_awards`, `lookup_award_by_piid` and `search_deleted_awards`, with a consistent response shape and readable errors. 15 tools.

## 0.1.0

Initial release: 12 tools covering Entity Management, Exclusions, Opportunities and PSC lookup, plus `vendor_responsibility_check` (FAR 9.104-1 entity and exclusion check). The key is read from `SAM_API_KEY` and never enters the conversation; expired keys get regeneration instructions.
