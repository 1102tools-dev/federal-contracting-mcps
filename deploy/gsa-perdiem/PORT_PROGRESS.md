# GSA Per Diem Worker + D1 port: progress

Branch: `worktree-agent-a22db7e792f1d6e15`
Latest commit: (see `git log -1`; updated at each milestone)

Port of the hosted GSA Per Diem MCP from Worker -> Durable Object -> Python
container to Worker + D1 (SAM.gov pattern). No push, no deploy, no Cloudflare
changes from this branch.

## Status

- [x] Study SAM.gov Worker, loader, workflows; Python server; hosted checks
- [ ] Analysis notes (this file)
- [ ] schema.sql + scripts/load_gsa_perdiem.py
- [ ] Worker tools (src/tools.ts) + index.ts rewrite
- [ ] node:test tests
- [ ] Parity harness + results
- [ ] CI + load workflows
- [ ] Final report

## Key findings so far

- Python hosted env (deploy/gsa-perdiem/Dockerfile): `PERDIEM_HOSTED=1`,
  `MCP_RESPONSE_CACHE_SECONDS=86400`, key from Worker secret `PERDIEM_API_KEY`.
- serverInfo name `gsa-perdiem` (MCPServer("gsa-perdiem")), version = pyproject
  version `1.2.0`.
- tools-contract.json is sorted by name (check_hosted_contract.py writes it
  sorted); verify_hosted_release.py compares sorted lists.
- `scripts/verify_hosted_release.py` asserts `/health.admission ==
  {"processing":16,"waiting":32,"total":48,"deadline_seconds":55}` for every
  slug except acquisition-gov, and `init.instructions` absent. The Worker
  /health must keep `admission` (plus `status`, `tools`, `release_sha`).
- `scripts/check_hosted_health.py` needs: `get_data_status.live_lookup_access
  == "hosted_publisher_key"`, `lookup_zip_perdiem 22201` without `error`, and
  a rotating `lookup_city_perdiem` that returns `status: resolved` with
  `source.kind == gsa_per_diem_api`.
- Task text says the SAM loader uses "the D1 HTTP API"; it actually shells out
  to `wrangler d1 execute` (CLOUDFLARE_API_TOKEN from secret
  CLOUDFLARE_D1_TOKEN). This port's loader calls the D1 HTTP API directly
  (`/accounts/{acct}/d1/database/{id}/query`) because the database id must
  come from an env var/argument and wrangler.jsonc holds a placeholder.

## Resume

```
cd deploy/gsa-perdiem && npm ci --ignore-scripts && npm run check && npm test
```
