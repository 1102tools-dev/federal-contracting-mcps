# Acquisition.gov MCP test record

## Version 1.0.8 hosted parsing follow-up — 2026-09-13

The 1.0.7 production acceptance test caught a Part 52 HTML parsing timeout at the unchanged 40-second parser deadline, despite its earlier constrained-image check passing. Version 1.0.8 removes repeated full-tree CSS-selector matching and duplicate text extraction. Source guards and parser deadlines are unchanged. All **236 offline tests** pass. Three local runs returned identical output: before **0.6492, 0.6579, 0.6565 seconds**; after **0.4721, 0.4792, 0.4619 seconds**. These local timings are not hosted throughput promises. Final deployment and hosted outcomes are recorded in the follow-up evidence.

### Final production verification

Version **1.0.8** is published on PyPI and deployed from commit `dffaadaa654bbd8e54dde9105b2e720d00c8dc0c` ([successful release](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/34756879409)). The five published tool schemas remain unchanged.

The actual `lite` deployment still exceeded the 40-second parser limit after the optimization. Only Acquisition.gov was moved to **basic: 1/4 vCPU, 1 GiB RAM, 4 GB disk**, with **one instance** and **two-minute idle sleep**. The stricter synthetic 1/16-CPU test did not predict production latency accurately; actual hosted acceptance is the deciding evidence. Configuration is committed separately in `2293ab4202ddf74d42f3f17c62a4703a58da2436`. Parser security caps and HTTP admission limits remain unchanged.

All **14 hosted HTTP requests / 10 tool calls** passed, covering all five tools, initialization, exact catalog, agency aliases, Part 10 section lookup, Part 52 continuation, NSF PDF extraction and both HTML/PDF guidance. Observed Part 52 times were **15.590 and 17.494 seconds**; NSF PDF retrieval/extraction took **10.880 seconds**. These are dated observations, not latency guarantees. There are **236 passing offline package cases** and **104 passing shared safety/release cases**.

The production release gate now also requires actual Part 52 HTML and NSF PDF text extraction; a successful lightweight index response alone is insufficient. Its regressions explicitly reject HTML errors and metadata-only PDF results. The manual constrained-image workflow now uses the production basic allocation.

At Cloudflare's published rates, the basic-versus-lite memory/disk increment is approximately **$0.73 per 100 awake hours before included allowances**, plus usage-based CPU differences. This is a calculation, not a bill forecast or cap. [Pricing](https://developers.cloudflare.com/containers/platform/pricing/). Existing one-instance and idle-sleep controls remain in place.

## Version 1.0.7 independent-review fixes — 2026-09-13

Fable 5.1 at extra-high effort independently reviewed the immutable 1.0.6 snapshot. It reproduced two P1 issues: HTTP timeouts/disconnects did not cancel SDK-owned tool tasks, and synchronous HTML parsing blocked the event loop. No P0 finding was identified in that review. Its 84 adversarial cases included expected-behavior hypotheses and test-harness failures; those failures are not a count of confirmed defects.

Version 1.0.7 binds each stateless request to its own SDK lifespan and cancels its work before releasing the HTTP slot. HTML parsing now runs in a separate, bounded process. HTML and PDF parsing share **one process slot**, so both parsers cannot consume the container's memory allowance simultaneously. The parser module excludes MCP server startup code. The five published tool definitions and source URL allowlist are unchanged.

### Current offline coverage

**236 passed, 3 opt-in live tests skipped**, including **55 new review regressions**. P0/P1/P2/P3 below classify test scenarios, not outstanding findings.

| Tier | Cases |
| --- | ---: |
| P0 | 33 |
| P1 | 79 |
| P2 | 97 |
| P3 | 4 |
| Original unranked cases | 23 |

| Tool | Direct offline cases |
| --- | ---: |
| `list_rfo_parts` | 31 |
| `get_rfo_part` | 33 |
| `list_rfo_agency_deviations` | 30 |
| `get_rfo_agency_deviation` | 25 |
| `get_rfo_guidance` | 21 |

There are **129 distinct direct-tool cases and 107 shared cases**. Multi-tool cases appear in more than one row. The [case inventory](tests/evidence/2026-09-13-fable-test-inventory.json) records each ID; shared helper tests are counted once.

### Confirmed issues addressed

- Actual MCP HTTP timeouts, client cancellation and disconnects now cancel the upstream task and real HTML/PDF subprocesses. Four simultaneous stalled calls return 504, the fifth receives 429, all four slots are released after cleanup, and a later call succeeds.
- Large HTML parsing no longer blocks health checks, admission or deadline timers. Actual Part 52 content exercises parsing and loop responsiveness.
- Section extraction retains div, blockquote, preformatted, definition-list and bare text, without duplicate nested headings or leaking into the next section. Known Favorites UI and duplicate hidden part headings are removed.
- Agency filtering normalizes punctuation and includes posted labels sharing an explicit acronym. Live checks returned all **49 DOE entries** for both `Energy (DOE)` and `DOE`, and all **50 GSA entries** for the full name and acronym. These counts are dated observations and may change upstream.
- An unsupported deviation link is skipped with an explicit completeness warning; valid allowlisted records remain usable. No additional hosts are permitted.
- Long provider cooldowns fail fast with the remaining delay rather than occupying a request indefinitely. **The full Retry-After deadline remains persisted and honored**; it is not shortened to send requests sooner. A wait longer than 30 seconds produces an explicit error without an upstream request.
- Invalid PDF start pages preserve the document's page count and a useful range error. PDF heading whitespace, additional explicit date formats and non-UTF-8 curl diagnostics are handled consistently.
- Smithery and standalone Docker installation pins match the package version. Version validation and a regression test check these pins. The root release workflow publishes this monorepo; the nested workflow is a standalone subtree template.

### Constrained container verification

The production image passed with **1/16 CPU and 256 MiB RAM**, without network access. The NSF two-page PDF extraction completed in **6.101 and 6.404 seconds**; full Part 52 HTML parsing completed in **27.800 and 27.996 seconds**, within its 40-second parser deadline. These are observed test times, not throughput promises. [CI run](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/34755554864).

### Boundaries that remain intentional

- Hosted admission remains **4 active requests, no waiting queue, 55-second HTTP deadline**, with **60 HTTP requests/minute/IP** at the Worker entrance. This release does not change the other MCP services' limits.
- HTML: **5 MiB input, 75,000 tags, 16 KiB per tag, depth 128; 40-second parser wall deadline, 192 MiB Linux address-space limit, 8 CPU seconds, 8 MiB worker output**. PDF limits remain **25 MiB input, 30-second parser wall deadline, 160 MiB Linux address space, 8 CPU seconds, 25 selected pages**. The HTTP deadline can expire before a parser's individual deadline when earlier work used the request's time budget.
- Broad deviation searches stop at **250 records** and return `total_matches` plus an explicit warning. Narrow the agency filter or query individual FAR parts; there is no cursor parameter. Every record in the live 608-result `Department` search remains reachable using narrower queries. Adding a pagination parameter would change the published tool contract.
- Dates from an index card are separate from dates stated in a document. Undated model pages retain null date fields and direct the caller to `list_rfo_parts` for index-card dates.
- Deliberately strict URL and HTML complexity checks remain: explicit URL ports and excessively nested parser output are rejected. HTML with omitted closing tags can be interpreted as deep nesting by the selected parser. No current live page was found to require relaxing this guard.
- Large, scanned, encrypted or complex PDFs can still hit extraction limits. Check `text_extraction_status` and warnings; request fewer pages when needed. Metadata-only results do not mean text extraction succeeded.
- Continuations still retrieve and parse the source again. A parsed-text cache was not added in this correctness release.

The earlier 1.0.6 record below is preserved as historical evidence. Current release verification is recorded separately in [the follow-up evidence](tests/evidence/2026-09-13-fable-remediation.json).

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
| `list_rfo_parts` | 21 | 7 |
| `get_rfo_part` | 25 | 12 |
| `list_rfo_agency_deviations` | 20 | 7 |
| `get_rfo_agency_deviation` | 23 | 11 |
| `get_rfo_guidance` | 20 | 10 |

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

### Expanded local and hosted live round

The September 13 audit completed **47 successful live MCP calls: 21 local and 26 hosted**. These covered eight model parts (**1, 2, 10, 12, 15, 39, 52 and 53**), filters, cursor continuation, six agency PDFs across **NSF, OPM, PBGC, FMC and DoD**, and all three guidance resources. This is sampled source coverage, not an exhaustive audit of every agency document.

Broader hosted checks found the full-Part-52 tag-limit failure once and the NSF parser-deadline failure twice. Both were fixed and retested on **hosted version 1.0.6**. The final round passed **11/11 calls**, including Part 52's first chunk and continuation, five different agencies' PDFs, all guidance resources, and the valid zero-deviation count for Part 52. Failed attempts are recorded separately and are not counted as successful calls.

The production-image check also passed twice with networking disabled at **1/16 CPU and 256 MiB RAM**: the NSF PDF took **7.80 and 7.60 seconds**. [Cloudflare documents these limits for the configured lite instance](https://developers.cloudflare.com/containers/platform/limits/). This demonstrates why local parser timings do not predict hosted latency.

Part 52 took **33.8 seconds** for its first hosted chunk and **30.6 seconds** for its continuation. The previously failing NSF PDF completed in **17.9 seconds**, including source retrieval. Large documents remain slower on the small hosted instance; the test confirms successful retrieval, not a speed guarantee.

[Expanded machine-readable evidence](tests/evidence/2026-09-13-expanded-live.json) includes every successful call, runtime, source hash, timing, the failures and retests, and CI links. The [reproducible hosted probe](tests/live_hosted_probe.py) performs 24 sequential sampled calls with a three-second pause between requests.

### Initial serialized live evidence

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
