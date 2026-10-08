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
  portal and timecard at it, with `/etc/cloudflared/config.yml`. Left
  untouched. The MCP tunnel uses `/etc/cloudflared-mcp/` and its own unit, so
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
- [ ] 10. Tests: health via Dell, fallback, load burst, listen
- [ ] 11. Worker-only deploys (needs James's approval)
- [ ] 12. README badge, progress page

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
