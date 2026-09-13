# Changelog

## 1.0.8 — 2026-09-13

- Replace repeated CSS-selector scans with one document walk and reuse full text when no heading is requested. Preserve extraction output, source guards, process isolation and the 40-second parser deadline.
- Address the live Part 52 parser timeout found during post-release verification of 1.0.7. All 236 offline cases pass; a three-run local comparison retained identical output and reduced parsing time by approximately 28 percent. Hosted verification is recorded in testing.md.

## 1.0.7 — 2026-09-13

- Tie each stateless HTTP request to its own MCP lifespan, cancelling underlying tool work on timeouts and disconnects before releasing its slot. Reject GET/DELETE at the local stateless endpoint.
- Isolate HTML parsing in one cancellable child process, with a 40-second wall deadline, Linux 192 MiB address-space / 8 CPU-second limits and an 8 MiB output cap; retain existing HTML input/complexity limits.
- Preserve visible section text across HTML layouts, avoid duplicate headings, retain main content inside an outer form, and prefer primary part headings.
- Preserve PDF page counts in out-of-range errors; normalize PDF heading whitespace and additional explicit date formats.
- Keep usable index entries with explicit warnings when a deviation link is outside the source allowlist; retain the allowlist and warn how to refine truncated searches.
- Preserve full provider Retry-After deadlines while failing fast when a call would wait more than 30 seconds.
- Add 55 independent-review regressions (236 offline cases total); verify real HTTP subprocess cancellation and actual Part 52 responsiveness.
- Keep the HTML child independent of MCP server startup, share one parser memory slot across HTML/PDF, and extend the constrained production-image check to actual Part 52 HTML.
- Normalize agency punctuation/acronym variants; update Smithery and standalone Docker pins to 1.0.7 and validate pin consistency.

## 1.0.6 — 2026-09-13

- Accept the legitimate full Part 52 HTML page by raising the bounded tag limit from 20,000 to 75,000; retain byte, tag-size and nesting limits.
- Add the actual Part 52 snapshot as a full-tool parsing and pagination regression.
- Allow a 30-second isolated PDF deadline within the 55-second hosted request timeout, retaining CPU/memory and content caps; add the actual NSF Part 1 PDF regression.
- Complete 181 offline tests, including at least 20 direct cases per tool.

## 1.0.5 — 2026-09-13

- Fix cached system-curl requests bypassing shared response validation; retain status, MIME, redirect, byte and Retry-After checks on both transports.
- Isolate PDF extraction in a cancellable subprocess with a 10-second deadline, bounded input/output, and Linux memory/CPU limits.
- Bound HTML complexity, decoded PDF streams and extracted metadata; explicitly report encrypted, malformed, partial and unextractable documents.
- Fix section-number matching, selected-content boundaries, issuance-date labels, page-range warnings and wrong-part detection.
- Validate cursors, headings, source IDs and page ranges before unnecessary upstream requests; fail explicitly on an unrecognized source index.
- Expand offline coverage from 23 to 179 passing tests, with P0–P3 cases, real stdio/HTTP smoke checks and serialized live evidence across all five tools.
- Preserve the five-tool interface, three-second upstream completion delay and existing hosted admission limits.

## 1.0.4

Unifies the hosted HTTP wrapper and existing published tool annotations with the
canonical package source. Releases can now build PyPI packages and Cloudflare
images from the same commit, with contract and live version checks.

## 1.0.3

Fixes shared request pacing locks that could remain held when background
executor threads changed. Lock acquisition now uses non-blocking attempts with
async polling, and release stays on the same event-loop thread. This also avoids
abandoned lock acquisitions when a waiting request is cancelled. Pacing intervals
and provider cooldowns are unchanged. Regression coverage includes repeated calls,
upstream errors, cancellation, state-write failures, and cross-process contention.
See [issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10).

## 1.0.2

Publishes the package under the domain-verified
`com.1102tools/acquisition-gov-mcp` MCP Registry identity and updates
project links to the `1102tools-dev` GitHub repository. No tool behavior
changed.

## 1.0.1

Serializes concurrent same-process requests by API identity before acquiring
the existing cross-process file lock. This preserves configured pacing while
preventing same-process lock contention from deadlocking concurrent calls.

## 1.0.0 — 2026-08-21

- Added five read-only tools for RFO model text, the official agency-deviation index, indexed PDFs, and approved guidance.
- Added host and redirect allowlisting, response limits, shared request pacing, and `Retry-After` preservation.
- Added content hashes, retrieval timestamps, extraction statuses, duplicate preservation, and page-numbered PDF text.
- Added deterministic fixtures, hardening tests, and an opt-in serialized live release gate.
