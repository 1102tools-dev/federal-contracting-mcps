# Validation record — September 7, 2026

- Existing Python suite: 1,788 passed, 375 skipped (live-only and conditional tests).
- New HTTP transport suite: 3 passed. Verifies 55-tool catalog, annotations, unknown arguments for every tool, host/origin/body-size guards, and bounded admission.
- Tool-profile regression: 3 passed; existing 55-tool default and 20-tool optional profile preserved.
- Live HTTP calls: 55 distinct tools passed, using the real USAspending API behind the local HTTP service. See live-results.json. This is transport/live smoke coverage, not an exhaustive correctness audit of every possible filter combination.
- Test fixture corrections: PSC autocomplete changed from a one-character guarded input to D3 for a real lookup; federal account snapshot now uses account_id returned by list_federal_accounts.
- Official Python MCP ClientSession through local Cloudflare Worker/container: initialized, discovered 55 tools, successfully called awards_last_updated.
- Local Worker checks: cross-origin request rejected with 403; rate limiter returned 429 after 60 method-check requests in the test window.
- TypeScript check: passed using generated Wrangler types.
- Production configuration dry run: passed, including Linux amd64 Docker build.
- Dependency audit: zero npm vulnerabilities reported.
- Git whitespace check and common credential-pattern scan: passed. This is not a comprehensive independent security audit.

## Unfinished gates

The Cloudflare Containers API rejected access because Workers Paid is required. No plan change was made. No production endpoint exists yet. Website pages remain drafts; no domain challenge, OpenAI scan, supported-client production review cases, demo recording, portal submission, approval, or publication has been completed. Re-run the public transport checks after hosting is enabled.

## Local setup

Started the existing Colima Docker VM and installed the missing Homebrew docker-buildx plugin to build the image. Added the Docker CLI plugin symlink. These local development changes do not affect the website. Local test servers are stopped at handoff.
