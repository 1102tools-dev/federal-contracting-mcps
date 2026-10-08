# Dell move progress

Moves USAspending, eCFR, Federal Register, GSA CALC+ and Regulations.gov to
govnode (James's Dell), behind the same Workers, with the Cloudflare containers
kept as the automatic fallback. Plan: `~/Desktop/1102tools-handoff-2-dell-server-move-2026-10-08.md`.
Branch: `claude/dell-origin`. Commit after every step.

## Decisions

- **Same release commits as the containers.** The Dell builds each server from
  the newest tag that releases it (`v*` or `<slug>/v*`, by date): v1.0.32
  (e63cc60) for four, regulations-gov/v2.0.0 (0691651) for Regulations.gov.
  These match each live `/health` `release_sha` on 2026-10-08.
- **Images run unchanged.** A small nginx gateway in front sets
  `Host: container.internal`, so the release ENV (`MCP_ALLOWED_HOSTS`) works
  as is. It routes by origin hostname, checks the Worker's secret header, and
  strips client IP headers. `GET /health` is open (same data as public
  `/health`) so monitoring needs no new GitHub secret.
- **New tunnel, separate config.** govnode has an old stopped tunnel
  "workspace" (d0bcbd63) whose DNS still points jobwatch, tsp, finance,
  portal and timecard at it, with `/etc/cloudflared/config.yml`. Removed
  2026-10-08 at James's request (see log). The MCP tunnel uses `/etc/cloudflared-mcp/` and its own unit, so
  the old config is never read.
- **Fallback trigger.** Tool responses are JSON (headers arrive only when the
  tool finishes), so a 5 s header timeout would cut slow calls. Instead the
  Worker probes the origin `/health` with a 5 s timeout, caches the result
  per isolate for 30 s, and falls back to the container when the probe fails
  or the origin call fails at the transport level.

## Steps

- [x] 0. Branch, progress file
- [x] 1. Build the five images on govnode (`/opt/mcp-origin`, `update.sh`)
- [x] 2. Docker Compose (gateway on 127.0.0.1:8790, 384 MB / 0.75 CPU / weight 256 each)
- [x] 3. LAN isolation (`firewall.sh`, `mcp-origin-firewall.service`)
- [x] 4. cloudflared, tunnel `mcp-origin` (b0c30636), origin DNS
- [x] 5. Regulations.gov key via header (Dell side: `regulations_key.py`; Worker side in step 6)
- [x] 6. Worker origin-first code + tests (`originFirst` in `deploy/shared/edge.ts`)
- [x] 7. Pull-based updater (`mcp-origin-update.timer`, every 15 min)
- [x] 8. Monitoring (`check_hosted_health.py` "Dell origin" row; cron unchanged)
- [x] 9. Privacy pages (effective October 8, 2026; adjust if the deploy slips)
- [x] 10. Tests: tunnel calls, burst, live fallback, listen, full monitor
- [x] 11. Worker-only deploys (approved by James 2026-10-08)
- [x] 12. README badge, progress page

## Log

- 2026-10-08: started. Live SHAs: usaspending/ecfr/federal-register/gsa-calc
  e63cc605, regulations-gov 0691651c.
- Steps 1–3 done on govnode. All five healthy at the live SHAs, ~60 MB
  each. Gateway: `/mcp` without secret 403, unknown host 404. Secret in
  `/etc/mcp-origin/origin.env` (root:james 640). Regulations.gov key header
  verified with a dummy value, then the container was restarted to clear it.
  Firewall verified: router, govnode and other Docker networks blocked;
  ecfr.gov and regulations.gov open.
- Step 4: cloudflared 2026.10.0 from pkg.cloudflare.com (apt, so it gets
  security updates). Tunnel `mcp-origin` b0c30636-7240-4799-bf48-66a90daf3b77,
  locally managed; credentials `/etc/cloudflared-mcp/credentials.json` (root
  600, passed to a DynamicUser service via LoadCredential); unit
  `cloudflared-mcp.service`. Five proxied CNAMEs `<slug>-origin.1102tools.com`
  created with the one token. Checked from outside: `/health` 200 in ~0.1 s,
  `/mcp` without secret 403. Old "workspace" tunnel and its five DNS records
  left as they were.
- Step 6: `originFirst` probes `<ORIGIN_URL>/health` (5 s, cached 30 s per
  isolate, shared by concurrent requests), sends `/mcp` and `/health` to the
  Dell with `X-Origin-Auth` and without client IP/location/UA headers, and
  falls back to the container (with `fetchWithRetry`) on a thrown fetch, a
  58 s timeout, or a non-JSON 403/404/502–504/52x. JSON errors from the
  server itself are returned as is. Responses carry
  `X-1102tools-Backend: origin|container`; each call logs
  `{"event":"backend",...}`. `ORIGIN_URL` is a production var in each
  wrangler.jsonc; `ORIGIN_SECRET` is a Worker secret (set at deploy time).
  Regulations.gov also sends `X-Regulations-Key` from its existing secret.
  14/14 edge tests pass; five Workers type-check; release dry-run shows the
  binding. Preview URLs don't work for Durable Object Workers, so the live
  Worker-to-Dell test happens right after the step 11 deploy.
- Step 7: `mcp-origin-update.timer` runs `update.sh` as james every 15 min
  (first run a no-op, success).
- Release safety: `configure_hosted_image.py` now also writes
  `vars.RELEASE_SHA` for Workers with `ORIGIN_URL` (D1 logic kept). The
  Worker uses the Dell only when the Dell's `/health` `release_sha` matches,
  so after a release the new container serves until the Dell rebuilds, and
  `verify_hosted_release.py` still sees the new commit.
- Step 8: services.json gets `origin` for the five; the monitor adds a
  "Dell origin" row that fails (opening the usual issue) when a Dell origin is
  unreachable or the public endpoint is answered by the container. Kept the
  30-minute cron: these checks now hit the Dell, not the containers, so they
  no longer cost container time (only Acquisition.gov's still wakes).
  **Merge the PR only after the step 11 deploy**, or the row fails on the old
  Workers (they send no `X-1102tools-Backend`). 64/64 release guard tests pass.
- Step 9: the five `/privacy` pages now say requests are usually answered by
  a 1102tools-operated server through an encrypted Cloudflare Tunnel, with a
  Cloudflare-hosted copy as fallback; IP, location and user-agent headers are
  removed first; that server keeps no request logs; Worker logs note which
  server answered. Regulations.gov's cache wording no longer implies the
  2-minute idle stop applies to every copy.
- Step 10 (pre-deploy, simulating the Worker through Cloudflare): real tool
  calls eCFR 0.30 s, USAspending 0.58 s, Federal Register 0.43 s; wrong
  secret 403. Burst of 300 `tools/list` at 30 concurrent across the five:
  300/300 200, avg 0.11 s, max 0.42 s (~210 req/s; busiest server peaks at
  ~50/min). Servers stayed ~60 MB; Frigate unaffected.
- **Next (needs James's go):** push the branch and open the PR; per slug
  record the current Worker version, `wrangler secret put ORIGIN_SECRET
  --env production` (value piped from govnode), `configure_hosted_image.py
  <slug> <live sha>`, Worker-only deploy; then live tests (backend header,
  stop a Dell container to prove fallback, listen stream, full monitor);
  merge the PR after the deploy.
- Old "workspace" tunnel removed (James: no longer needed): tunnel d0bcbd63
  deleted at Cloudflare with its five DNS records (finance, jobwatch, portal,
  timecard, tsp). Its files moved to `/root/retired-workspace-tunnel-2026-10-08/`
  on govnode (`/etc/cloudflared`, `/root/.cloudflared`). Five Cloudflare
  Access apps for those hostnames remain (inert without DNS). `mcp-origin` is
  the only tunnel and stays healthy.
- **Step 11, live 2026-10-08 (UTC 2026-10-09 ~00:10).** Worker-only deploys,
  images unchanged (wrangler: "no changes" for every container). Rollback =
  redeploy the previous version (`npx wrangler rollback <id> --env production`
  in `deploy/<slug>`):

  | Worker | New version | Previous (rollback) | Image |
  |---|---|---|---|
  | ecfr-mcp | 9b1369ba-a734-4cd2-863c-d77bc1240637 | 02c2beb6-469f-499b-923a-7039f9072c8d | e63cc605 |
  | usaspending-mcp | 62703778-0dec-401a-a352-70672c6c2648 | 79064608-d366-4350-a198-57663d5dc44d | e63cc605 |
  | federal-register-mcp | c2179de3-c4a4-4cad-875d-0f3653af1314 | 88d337e8-5114-451e-b04a-fb38ab0d4f31 | e63cc605 |
  | gsa-calc-mcp | 2adbd078-0b14-4403-8a31-fb04cff10f9a | a3343b52-aebc-4625-a192-bc100c063b82 | e63cc605 |
  | regulations-gov-mcp | b41de64e-6a4c-459a-b353-d864eff0db73 | 90fff5ec-48dc-44dd-9c03-6fcd68d34f31 | 0691651c |

  `ORIGIN_SECRET` set on all five (piped from govnode, never printed).
- Step 10 live: eCFR `/health` and tool calls answered by `origin` in
  0.1–0.25 s; listen stream still acknowledged at the edge; new privacy page
  live. Fallback: stopped the Dell eCFR server, three tool calls answered by
  `container` with real results; restarted it and traffic returned to
  `origin` within the 30 s probe cache. Full `check_hosted_health.py`: all
  nine ok, "Dell origin" ok (5/5), Regulations.gov in publisher-key mode with a
  real upstream call through the Dell.
