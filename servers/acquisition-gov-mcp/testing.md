# Acquisition.gov MCP test record

## Version 1.0.6 hardening — 2026-09-13

### What this server retrieves

The server reads official Acquisition.gov HTML pages and indexed PDFs. It does not query a government JSON API, a CSV database or a private mirrored dataset. The five tools turn the RFO index, model-part pages, agency deviation PDFs and three allowlisted guidance resources into structured, source-linked results.

### Verified coverage

The previous source baseline passed **23 offline tests**. This release passes **181 offline tests**, with **3 opt-in live tests skipped** during offline runs:

| Tier | Passing cases | Scope |
| --- | ---: | --- |
| P0 | 27 | URL/redirect allowlist, byte/complexity limits, subprocess cancellation, PDF deadlines and parser concurrency |
| P1 | 60 | Response-policy parity, fallback regression, parsing correctness and fail-closed source validation |
| P2 | 68 | MCP-dispatched tool paths, filters, pagination, metadata and invalid inputs |
| P3 | 3 | Real stdio startup/discovery/shutdown, packaged parser modules and HTTP MCP smoke checks |
| Legacy baseline | 23 | Existing captured HTML, generated PDF, pacing and tool-contract tests |

### Direct coverage by tool

| Public tool | Direct offline test cases | Recorded live tool calls |
| --- | ---: | ---: |
| `list_rfo_parts` | 21 | 2 |
| `get_rfo_part` | 25 | 3 |
| `list_rfo_agency_deviations` | 20 | 2 |
| `get_rfo_agency_deviation` | 23 | 1 |
| `get_rfo_guidance` | 20 | 4 |

These are **108 distinct direct-tool cases plus 73 shared cases = 181 offline tests**. One case calls both deviation-listing and PDF-retrieval tools, so the direct-tool rows sum to 109. Each parametrized case counts separately; repeating calls within a single case does not increase its count. Shared parser/transport tests are not credited once per tool. The per-tool rows include successful results, invalid inputs, actual MCP dispatch, transport-failure propagation and tool-specific boundary cases; they are not line-coverage percentages.

The initial 114-case hardening pass was expanded with **65 additional direct-tool scenarios**, 13 per tool, without further runtime changes. These cover 404/429/MIME/redirect/timeout propagation, agency/date filters, duplicated and cross-part records, whole-result pagination, section boundaries, document metadata, encrypted/blank/malformed/partially extractable PDFs, and default/maximum PDF page ranges.

[Collected case inventory](tests/evidence/2026-09-13-test-inventory.json) lists the exact test IDs behind these counts. [tests/README.md](tests/README.md) includes the inventory command.

The priorities describe the tested failure modes; they are not a claim that every possible failure has been covered. The shared release, pacing and hosted-admission suites also passed **95 tests** locally. Linux CI runs the Acquisition.gov offline suite before release, including the isolated PDF parser under its Linux resource limits.

### Failures reproduced and fixed

- A cached system-curl fallback skipped response handling on subsequent calls. Both transports now enforce status codes, exact MIME types, redirect validation, body limits and Retry-After handling.
- Unrecognized index HTML could look like a successful empty result; mismatched part pages could be labeled as the requested part. Both cases now fail explicitly.
- Section `10.1` could match `10.10`, and section traversal could escape the selected main content. Matching and traversal now respect those boundaries.
- Encrypted PDFs could crash before an extraction status was returned. PDF parsing is isolated, bounded and cancellable, with explicit failure metadata.
- A generic date label could misread an effective date as an issuance date. Date labels now distinguish those fields.
- Invalid cursors, blank headings and bad PDF ranges could trigger unnecessary upstream calls. Validation runs first.
- Selected PDF pages and oversized applicability text now carry explicit scope/truncation warnings.

### Follow-up found by broader live testing

The actual Part 52 page contains **52,529 tags in 3,187,131 bytes**, exceeding the first hardening pass's 20,000-tag threshold. Version 1.0.6 raises the tag limit to **75,000**, retaining the 5 MiB download, per-tag and nesting limits. A compressed snapshot of that official page now exercises full parsing and cursor continuation through MCP dispatch. Locally the snapshot parsed in **0.46 seconds**, with **133 MiB peak process RSS**; these measurements are observations, not a service guarantee.

Part 52 currently has no agency-deviation links in the source index. An empty filtered listing is valid when the index itself is recognized; the expanded live check distinguishes that case from an unrecognized or blocked page.

A hosted two-page extraction of the 128,522-byte NSF Part 1 PDF hit the initial 10-second parser deadline, while the same document completed locally in 0.09 seconds. Version 1.0.6 allows **30 seconds** for the isolated parser within the existing 55-second HTTP deadline; Linux CPU/memory, content and output caps remain in force. That actual PDF is now a regression fixture.

The release verifier also allows up to **90 seconds** for a successfully uploaded version to appear in PyPI's JSON endpoint. It waits only on a missing release and still fails immediately on package identity, payload or digest mismatches. Three regression tests cover delayed visibility, timeout and mismatch behavior.

### Resource boundaries

| Boundary | Limit |
| --- | --- |
| HTML / PDF downloads | 5 MiB / 25 MiB |
| Redirects | 3; each destination revalidated |
| HTML complexity | 75,000 tags, 16,384 bytes per tag, nesting depth 128 |
| PDF pages selected per call | 25 |
| Decoded PDF page stream | 2 MiB before text extraction |
| Extracted PDF text / applicability field | 200,000 / 8,192 characters |
| PDF worker output | 2 MiB |
| Concurrent PDF parser children | 1 per server process |
| PDF parser deadline | 30 seconds wall time |
| Linux parser address space / CPU | 160 MiB / 8 seconds |
| Public text chunk | Up to 40,000 characters |

The Linux address-space and CPU limits apply to the hosted Linux runtime. macOS and Windows retain subprocess isolation, cancellation, the parent deadline and explicit input/output/content limits, but do not apply those Linux resource limits. A rejected or partial document is reported as such; no OCR is performed.

### Serialized live evidence

Two new opt-in test functions completed **12 real MCP tool calls** on September 13, 2026, using the production three-second completion delay. These covered all five tools, all three guidance resources, a section lookup, a cursor continuation, agency filtering, an indexed NSF PDF page and two successive requests through the actual system-curl transport. The first gate completed in **31.41 seconds** and the curl gate in **3.87 seconds**. These are observed test durations, not throughput guarantees.

The current index returned **51 model parts**. Part 10 had **38 indexed agency deviations**; the filtered NSF record resolved to a **four-page PDF**, and the FAR Council guidance PDF had **three pages**. Both PDF samples extracted successfully. [Machine-readable observations](tests/evidence/2026-09-13-live.json) contain source URLs, UTC retrieval times, hashes, results and warnings.

This is sampled live coverage, not a claim that every agency PDF or model part was tested. Hashes are observations, not permanent expected fixtures. No load test was performed against Acquisition.gov. The upstream pacing remains one request at a time followed by a three-second delay; hosted admission remains four active requests and no waiting queue.

See [tests/README.md](tests/README.md) for reproducible offline, smoke and opt-in live commands.

## Historical evidence

The earlier records below are retained with their original versions and dates.

Version: `1.0.0`

## Deterministic suite

Run:

```bash
uv sync --dev
uv run pytest -q
uv build
```

The offline suite covers:

- captured RFO index, model-part, and guidance HTML;
- duplicate and multi-part agency-deviation entries;
- invalid parts, dates, cursors, filters, and output limits;
- native-text, multi-page, blank/image-only, and malformed PDFs;
- page ranges and document-labeled issuance, effective, expiration, and applicability text;
- redirect allowlisting, SSRF targets, content type, response size, and 429 `Retry-After` behavior;
- bounded system-`curl` compatibility fallback after a Python transport failure;
- exact tool inventory and strict rejection of unknown parameters.

Local stdio startup and discovery also returned server `acquisition-gov` version `1.0.0` with exactly the five documented tools.

The fixtures are parser contracts, not current-policy evidence.

## Live gate

Run only as a serialized release check:

```bash
ACQUISITION_GOV_LIVE_TESTS=1 uv run pytest tests/test_live.py -q
```

The live gate retrieves the official deviation index, one model part, one indexed agency PDF page, and the FAQ. It records the page hashes returned by the tools, so upstream changes are observable. Live content must be reviewed before release when fixture and upstream hashes or structure diverge.

On 2026-08-22, the serialized live gate passed. The index, Part 10 model page, an indexed four-page NSF deviation PDF, and the FAQ each returned HTTP 200 with complete text extraction. A second serialized evidence capture also passed and recorded these upstream hashes:

- deviation index: `a62f55032e15bc1a3cc1e01df6ba8a7f30fc3056f7cbec4aacb4b4cad6402989`
- Part 10 model page: `65a41a3e8235cd0ceac42a8e8aaf4027459ce201fc1237357ecbf27437046c3a`
- indexed NSF deviation PDF: `eb571869435327f78fd683212f5ebe956b6547a84dcf939f2fe7c83e84d02417`
- FAQ: `b29b815050c94f5bb205ffd915dac4a02300c3da292b1ef8b15ab7f9472c7670`

These hashes are observations, not permanent expected values. A future hash change requires source review rather than automatic rejection.

## Release boundary

Package tests establish deterministic parsing and current upstream reachability. They do not establish that a deviation applies to a particular acquisition. That determination remains outside the server.

## RC5 pacing remediation (2026-08-22)

Version 1.0.1 carries the suite-wide asynchronous pacing-lock correction. The full offline lane passed (20 tests; 1 live-gated test skipped), including deterministic same-process concurrency coverage. The published PyPI wheel was then installed in an isolated cache and completed MCP startup and `tools/list` with 5 tools.
