# Public MCP rollout

The four additional keyless services reuse the USAspending HTTP/container design. Each has its own Worker, public subdomain, singleton lite container, two-minute idle sleep, three-second upstream pacing, four-request admission limit, 55-second request deadline, 64 KiB MCP body limit, and per-IP edge request limit.

## Verification

All 34 tools passed live production calls on September 7, 2026. Offline suites: GSA CALC+ 250 passed, eCFR 185 passed, Federal Register 135 passed, Acquisition.gov 23 passed. Optional historical live suites remain skipped; the dedicated production checks exercised every tool. Run `python3 deploy/shared/live_check.py <slug>` from the repository root. Initial container provisioning or a cold start can require warming `/health` before a portal scan. A successful health check alone is not an upstream-data test.

The live checker derives vendor names, document numbers, docket identifiers and deviation source IDs from provider responses. Local raw response fixtures support reproducibility; `live-results.json` records tool outcomes. These are test snapshots, not authoritative current data.

## Deployment and maintenance

Build the corresponding Dockerfile from the repository root for linux/amd64. Push the image to the Cloudflare registry and pin the returned digest in both Wrangler container configurations. Existing registry credentials from the Cloudflare connector must be short-lived, passed without printing them, and kept only in a temporary Docker config removed afterward. The local shell token can upload Workers but cannot manage container applications. Use the Cloudflare connector for container changes. Container application and namespace IDs are in each review/deployment.json.

Worker uploads through the API must retain the `containers` declaration, Durable Object binding, rate limiter, compatibility settings, and disabled invocation logging. Do not replace the singleton with randomly named containers; the singleton protects shared upstream pacing. Keep source changes backward compatible until the matching container rollout is complete. `/support`, `/privacy`, `/terms`, and each plugin-specific domain challenge are Worker routes.

## OpenAI publication

Publisher: James Prentiss Jenrette, verified individual. Branding: 1102tools. Each draft uses no-auth MCP, all tools, five positive and three negative review scenarios, three starter prompts, and distinct light/dark directory and composer icons.

Record real ChatGPT Developer Mode calls for each MCP. Upload the user-supplied recording, verify anonymous HTTP access, full video decoding and actual browser playback, then enter its URL. Obtain the user's final attestations and authorization for each submission. A saved draft, submitted review, approval, and directory publication are separate states.
