# Validation record — September 7, 2026

- Existing Python suite: 1,788 passed, 375 skipped (live-only and conditional tests).
- New HTTP transport suite: 3 passed. Verifies 55-tool catalog, annotations, unknown arguments for every tool, host/origin/body-size guards, and bounded admission.
- Tool-profile regression: 3 passed; existing 55-tool default and 20-tool optional profile preserved.
- Live HTTP calls: 55 distinct tools passed, using the real USAspending API behind the local HTTP service. See local-live-results.json. This is transport/live smoke coverage, not an exhaustive correctness audit of every possible filter combination.
- Test fixture corrections: PSC autocomplete changed from a one-character guarded input to D3 for a real lookup; federal account snapshot now uses account_id returned by list_federal_accounts.
- Official Python MCP ClientSession through local Cloudflare Worker/container: initialized, discovered 55 tools, successfully called awards_last_updated.
- Local Worker checks: cross-origin request rejected with 403; rate limiter returned 429 after 60 method-check requests in the test window.
- TypeScript check: passed using generated Wrangler types.
- Production configuration dry run: passed, including Linux amd64 Docker build.
- Dependency audit: zero npm vulnerabilities reported.
- Git whitespace check and common credential-pattern scan: passed. This is not a comprehensive independent security audit.

## Remaining directory gates

Workers Paid is active and the endpoint and support/privacy/terms URLs are deployed. OpenAI portal sign-in, domain challenge, production tool scan, supported-client review cases, demo recording, approval, and directory publication remain outstanding. No directory submission has been made.

## Local setup

Started the existing Colima Docker VM and installed the missing Homebrew docker-buildx plugin to build the image. Added the Docker CLI plugin symlink. These local development changes do not affect the website. Local test servers are stopped at handoff.

## Hosting activation

On September 7, 2026, Cloudflare checkout displayed “Purchase complete” and confirmed the subscription is active. Continued setup from that screen. No additional card information was entered by the agent. The Containers API then returned success.

Checkout terms: Workers Paid is $5/month; additional usage beyond included allowances is billed monthly. Recurring usage charges continue until cancellation, which is effective at the end of the current billing period. Checkout linked Cloudflare Terms of Service and Privacy Policy. The displayed included allowances were 10 million Worker requests/month, 30 million CPU ms/month, 6,000 build minutes/month, and Durable Objects allowances of 1 million requests, 400,000 GB-seconds, and 1 GB storage. These are selected allowances, not a comprehensive billing schedule or a hard spending cap.

## Production findings and corrections

The first production tests exposed filelock ownership and per-thread deadlock bookkeeping problems when acquisition and release ran through separate asyncio executor threads. A thread_local=False intermediate fix was insufficient. The final implementation acquires the file lock nonblockingly on the event-loop thread, polls asynchronously under contention, and releases on that same thread. This also avoids an orphaned executor acquisition after cancellation. The canonical shared helper and all nine distributed copies were synchronized; no other server was deployed or released. New tests cover executor-thread variation and cancellation during cross-thread contention.

The unsuccessful intermediate production run is retained in initial-production-failures.json. Local predeployment evidence is in local-live-results.json. Final public results are recorded separately in live-results.json.

Support, privacy, and terms are now published at the /support, /privacy, and /terms paths on usaspending.1102tools.com. OpenAI's portal requires user sign-in; no domain challenge token has been obtained and no submission made.

## Final deployment verification

- Expanded regression suite after the pacing fix: 1,803 passed, 375 skipped.
- Public support, privacy, and terms URLs returned HTTP 200.
- Public HTTPS health endpoint returned status ok and 55 tools.
- Public DNS resolvers (Cloudflare and Quad9) resolved the custom hostname. This Mac continued returning a cached DNS miss through its system resolver, so these production tests used the published Cloudflare address for connection resolution, with the original hostname and normal certificate validation. A separate curl test using DNS-over-HTTPS also succeeded. No certificate verification was disabled.
- The official MCP Python client initialized against the production hostname and discovered 55 tools.

The intermediate Worker update temporarily omitted the containers metadata declaration; the final update restored it. The transition test is retained in rollout-transition-results.json. Final tests are run against the settled deployment without concurrent code updates.

- Final settled production run: all 55 distinct tools passed (56 successful calls, including two award bootstrap fixtures), with zero failures. See live-results.json.
- Official MCP Python client also successfully called awards_last_updated against production.
- Final Worker TypeScript check and git diff --check passed.
