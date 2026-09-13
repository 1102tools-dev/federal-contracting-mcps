# Changelog

## 1.0.6 — 2026-09-13

- Accept the legitimate full Part 52 HTML page by raising the bounded tag limit from 20,000 to 75,000; retain byte, tag-size and nesting limits.
- Add the actual Part 52 snapshot as a full-tool parsing and pagination regression.
- Complete 180 offline tests, including at least 20 direct cases per tool.

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
