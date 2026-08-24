# Changelog

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
