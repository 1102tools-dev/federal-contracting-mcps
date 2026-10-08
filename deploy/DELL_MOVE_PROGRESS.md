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
- [ ] 1. Build the five images on govnode
- [ ] 2. Docker Compose (gateway + five servers, 127.0.0.1, caps)
- [ ] 3. LAN isolation (DOCKER-USER + INPUT rules)
- [ ] 4. cloudflared, tunnel, origin DNS
- [ ] 5. Regulations.gov key via header
- [ ] 6. Worker origin-first code + tests
- [ ] 7. Pull-based updater (systemd timer)
- [ ] 8. Monitoring (`check_hosted_health.py`, `hosted-health.yml`)
- [ ] 9. Privacy pages
- [ ] 10. Tests: health via Dell, fallback, load burst, listen
- [ ] 11. Worker-only deploys (needs James's approval)
- [ ] 12. README badge, progress page

## Log

- 2026-10-08: started. Live SHAs: usaspending/ecfr/federal-register/gsa-calc
  e63cc605, regulations-gov 0691651c.
