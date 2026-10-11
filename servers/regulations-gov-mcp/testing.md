# Regulations.gov MCP: Testing

298 regression tests: 179 run offline on every release, and 119 call the live Regulations.gov API when you turn them on with a key.

## What is tested

All 9 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly.

- **Input checks.** Empty or whitespace-only filters (an empty `agency_id` once returned all 1,951,938 documents), control characters, misspelled parameter names, reversed or malformed dates, path characters in IDs, unknown sort fields, a document ID where `comment_on_id` needs the hex object ID, and pages past the 40-page limit. Bad input gets a specific message saying how to fix it, including under MCP SDK 2.3.
- **Filters really filter.** Live tests confirm each filter the server sends changes the results, and that the API's real limits (40 pages, multi-agency and multi-field sorts) match what the server allows.
- **Open comment periods.** Soonest-closing documents come first, with the true total and a `truncated` flag.
- **Deadlines.** Deadlines are shown in Eastern time (Regulations.gov stores them in UTC, which reads a day late), labeled as Regulations.gov metadata, and linked to the notice and docket so you can confirm the controlling date.
- **Comments.** Counts are labeled as posted publicly, not received; organization lookups that fail leave the organization unknown; comment text comes back as plain text.
- **FAR case history.** Paged docket summaries with document counts by type, open-for-comment counts, and withdrawals labeled as withdrawals.
- **Keys and errors.** The API key is never shown in errors or logs; without a key, data tools return setup instructions; `get_access_status` reports key status without calling Regulations.gov.
- **Hosted service.** Compact results, publisher-key handling, tool catalog, request pacing, hourly budget and response cache.

Realistic rulemaking questions (open comment periods, comment deadlines and extensions, FAR case histories, posted comments) were also checked against Regulations.gov and the Federal Register before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/regulations-gov-mcp`:

```sh
uv run pytest                                                     # offline suite (no key needed)
REGULATIONS_LIVE_TESTS=1 REGULATIONS_GOV_API_KEY=your-key uv run pytest                # add live tests
REGULATIONS_LIVE_TESTS=1 REGULATIONS_GOV_API_KEY=your-key uv run pytest -m live_smoke  # small one-call-per-test live set
```

Live tests need a free [api.data.gov key](https://api.data.gov/signup/) and are paced automatically. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **Key required locally.** api.data.gov keys allow 1,000 requests per hour. The server keeps itself to 950 per rolling hour (`API_DATA_GOV_HOURLY_CAP`), spaces requests 0.6 seconds apart, and honors `Retry-After` without automatic retries. `DEMO_KEY` allows only 10 requests per hour.
- **Filter values are case-sensitive.** `Proposed Rule`, `Rule`, `Notice`, `Rulemaking`, `Nonrulemaking`; lowercase values return 0 results with no error.
- **40-page limit.** Searches reach at most 40 pages (up to 4,000 records at 100 per page). Past that, results are flagged `truncated`; narrow by date (`posted_date_ge/le` for documents and comments, `last_modified_date_ge/le` for dockets).
- **Deadlines are provider metadata.** A Regulations.gov comment date can differ from the controlling date in the Federal Register notice (extensions, reopenings, conditional deadlines, or a different time zone). Check the linked notice's DATES section before relying on a deadline.
- **Posted comments are not all comments received.** Mass-mail duplicates and withheld submissions are not counted, and an organization label alone does not show an author's position.
- **Attachments are links only.** Attachment contents are not read, and some attachment links return HTTP 403.
- **Comment search rows have no organization.** Use `search_comments(include_organization=True)` (page size up to 25) to look each one up.
- **Read-only.** Posting comments and bulk downloads are out of scope.

## History

Earlier audit rounds and fixes are in this file's git history and in [changelog.md](changelog.md).
