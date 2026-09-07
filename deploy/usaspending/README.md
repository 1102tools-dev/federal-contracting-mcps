# USAspending remote pilot

Full 55-tool deployment of the existing Python server. Source stdio behavior remains unchanged. No public deployment or OpenAI approval is implied by this package.

## Architecture

A Cloudflare Worker routes `/mcp` to one named Python container. MCP uses stateless Streamable HTTP and JSON responses. The single container preserves the existing cross-process filesystem pacing: three seconds between upstream requests, plus provider-directed cooldowns. Four concurrent HTTP requests are admitted; additional requests receive 429. Requests time out after 55 seconds and bodies are capped at 64 KiB. The edge adds a per-IP 60-request/minute limit. Cloudflare rate limits are local protection, not a global quota or a spending cap.

The container runs as an unprivileged user. The Worker strips cookies and authorization headers and validates browser origins. Python application logging is suppressed because SDK errors may include input arguments. Worker logs contain only generic backend-unavailable events; invocation logs are disabled. Check account-level logging before publishing the draft privacy notice.

`/health` indicates backend readiness and tool count; it does not prove upstream availability. No periodic monitor has been scheduled.

## Hosting

Workers Paid was activated on September 7, 2026 with the user's approval. The plan is $5/month plus usage exceeding included allowances. The pilot uses one `lite` container, sleeps after two idle minutes, and caps instances at one. This limits resource scale but does not impose a hard dollar cap.

Pricing: https://developers.cloudflare.com/containers/platform/pricing/

## Development and deployment

From this directory:

```sh
npm ci
npx wrangler types
npm run check
npm run dry-run
npx wrangler dev --env production --port 8787
```

A working Docker daemon and buildx plugin are required. The Docker image uses the existing frozen Python lockfile and packages local source, not the old PyPI image. Both base images are pinned by digest. Review and update those digests deliberately.

For subsequent deployments after local validation:

```sh
npm run deploy
```

The production configuration binds `usaspending.1102tools.com`. It does not replace the main Pages website. Validate the deployed endpoint using `review/live_check.py` and a supported MCP client before submitting it for review.

From the repository root:

```sh
uv run --project servers/usaspending-gov-mcp pytest servers/usaspending-gov-mcp/tests -q
uv run --project servers/usaspending-gov-mcp python deploy/usaspending/review/live_check.py https://usaspending.1102tools.com/mcp
```

## Rollback

Record the deployed Worker version and container image digest. Revert to the last validated Git commit and redeploy its matching Worker/container configuration; verify health and MCP calls. For this first pilot, temporarily remove the custom domain route if no prior known-good deployment exists. Do not assume a Worker-only rollback also restores a compatible container image.

## Submission

`review/submission.md` contains listing copy, five positive and three negative cases, annotation rationale, and remaining portal steps. `review/website-copy.md` contains unpublished support/privacy/terms drafts. `review/live-results.json` records the actual test endpoint and outcomes. It must not be described as production evidence when it names localhost.

## Initial production deployment

The first production deployment used Wrangler to upload the Worker, then the existing authenticated Cloudflare MCP connection to push the container image and attach the application/domain because the shell API token lacks container-registry permissions. Registry credentials were short-lived and used in a temporary Docker config that was removed after upload. No persistent credential was added to this repository. Future `npm run deploy` calls require a deployment credential with Containers/registry access or the same connector-assisted workflow. Do not treat the shell token's Worker upload permission as complete deployment access.

See `review/deployment.json` for the deployed version and image digest. The live endpoint is https://usaspending.1102tools.com/mcp.

API-based Worker updates must preserve `containers: [{class_name: "USASpending"}]` in upload metadata as well as the Durable Object binding. Omitting that declaration can interrupt the Worker/container link. The Wrangler configuration already includes it.
