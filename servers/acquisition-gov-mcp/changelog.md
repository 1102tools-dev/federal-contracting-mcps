# Changelog

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
