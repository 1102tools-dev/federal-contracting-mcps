# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.0.19

`search_documents` and `get_documents_batch` describe what they do without ranking themselves: no more "the primary tool" or "more efficient than individual calls." Tools and answers are unchanged.

## 1.0.18

The PyPI page now links to this server's 1102tools page, and the MCP registry entry lists the hosted endpoint. Tools and answers are unchanged.

## 1.0.17

Hosted cache counts on `/health` now cover real users only; 1102tools' own health checks and release checks are counted separately under `monitor`.

## 1.0.16

Input mistakes (for example, a FAR part without a CFR title, or page 51) again return a specific message saying how to fix the request under MCP SDK 2.3, instead of a generic error.

## 1.0.15

Open-comment answers now explain that counts and deadlines are as indexed by the Federal Register, and point you to the docket or document to confirm a deadline, since a reopening notice can list a later date than the index.

## 1.0.14

Open-comment answers say whether every matching document was scanned (`complete`, `truncated`) and warn when an unscanned document could close sooner. FAR Council answers keep their scan details. The 500-document scan is unchanged.

## 1.0.13

Adds FAR Council co-filing searches, presidential document fields and filters, and parent-agency matching in public inspection. Rejects pages above 50, shows capped counts, keeps batch results in the order requested, and labels where each FAR case-history match came from.

## 1.0.12

Hosted service only: the answer cache size can be raised with `MCP_RESPONSE_CACHE_MB` and `MCP_RESPONSE_CACHE_ENTRIES`. The PyPI package is unchanged.

## 1.0.11

Hosted service only: cached answers are tied to the newest Federal Register issue date (checked at most every 15 minutes). Searches, open comment periods, FAR case history and facet counts are kept 24 hours or until the next daily issue; published documents 24 hours; public inspection 10 minutes. The PyPI package is unchanged.

## 1.0.10

Hosted service only: repeat questions are answered from a bounded in-memory cache (published documents and the agency list 24 hours; searches, facet counts, open comment periods and FAR case history 1 hour; public inspection 10 minutes). Errors are never cached. Off unless `MCP_RESPONSE_CACHE=1`, so the PyPI package is unchanged.

## 1.0.8

Faster request pacing: a shared budget of 500 requests per rolling five minutes, at least 0.6 seconds between starts, and two requests in flight. The hosted entrance limit rises from 60 to 120 per minute. Tools are unchanged.

## 1.0.7

The hosted service and the PyPI package now build from the same source.

## 1.0.6

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.5

Published under the MCP Registry name `com.1102tools/federal-register-mcp`. No tool changes.

## 1.0.4

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.3

Safety release: every request waits at least 3 seconds after the last one, and `Retry-After` is honored without automatic retries.

## 1.0.2

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.1

Correctness fixes: pre-2011 document numbers (such as `E9-12940`) work again, open comment periods now return the soonest deadlines first with the true total, FAR case history returns complete results with a `truncated` flag, and RULE-type documents with open comments are included. Adds `cfr_title`/`cfr_part` filters and daily through yearly facet counts.

## 1.0.0

Requires MCP Python SDK 2 (`mcp>=2.0.0,<3`). No tool changes. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip`, or Docker.

## 0.2.2

Searches with no filter, empty filters, or control characters now return an error instead of silently returning the 10,000 most recent documents.

## 0.2.1

Misspelled parameter names now return an error instead of being silently ignored.

## 0.2.0

Hardening release: fixes a crash on every `list_agencies` call, trims oversized responses, and adds date and input validation across all 8 tools.

## 0.1.0

Initial release.
