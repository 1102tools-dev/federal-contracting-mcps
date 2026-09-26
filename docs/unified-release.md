# Unified MCP releases

A versioned GitHub release builds the Python packages and the seven hosted MCP
services from the same canonical checkout. Ordinary commits and documentation
edits do not deploy production.

```text
release tag -> shared tests + package tests + hosted image/contract checks
                 -> published-version guard for all nine packages
                 -> Cloudflare hosted services -> live verification
                 -> PyPI packages -> verify published wheels
                 -> MCP registry
                 -> final release and destination summary
```

The static 1102tools website has its own repository and deployment. This workflow
does not publish website content or submit directory listings.

## Source and release rules

- `servers/` is the source for both local packages and hosted services.
- `deploy/services.json` lists the seven hosted services, package paths, existing
  application names, endpoints, and tool counts. Other packages only go to PyPI.
- `deploy/<service>/` owns the Worker wrapper, frozen container build, and npm lock.
- Keep the existing `publish-pypi.yml` filename: PyPI Trusted Publishers refer to it.
- Patch package versions, manifests, and Docker install pins for changed packages.
  `scripts/validate_versions.py` checks internal version consistency. Before any
  deployment, `scripts/check_published_version.py` compares each built wheel
  against the same version on PyPI: installed payload, dependency/Python metadata,
  extras, entry points, and wheel compatibility must match. Changed packages must
  use a new version above the latest PyPI release. Unchanged packages may be
  skipped safely. ZIP timestamps, builder metadata, and README prose do not force
  a bump. This compares declared package dependencies, not hosted lockfile pins.
  PyPI outages, missing artifacts for an existing version, yanked matching wheels,
  or checksum failures stop release. The guard is repeated after publication with
  `--require-published`, including skipped versions, to check actual PyPI contents.
- Push a new `v*` tag only after review and tests. Manual workflow dispatch on a tag
  supports retries. Never overlap a legacy release with the first unified release.
- The workflow serializes unified production releases. Cloudflare deployment and
  live verification must succeed for every service in the release (all seven for
  a `v*` tag, one for a scoped tag) before PyPI starts.
  A partial failure is reported as a failed release.
  It is not a transaction, and PyPI versions cannot be overwritten or rolled back.

## Credentials and first activation

The `cloudflare-production` GitHub environment needs an encrypted Actions secret
named `CLOUDFLARE_API_TOKEN`. GitHub's hosted runners cannot read a Mac's Keychain.
Use a dedicated Cloudflare account token with Account Settings Read, Workers
Scripts Write, and Workers Containers Write for account
`846d3e41e48446abcd3570c0959f9fb5`, plus Zone Read and Workers Routes Write scoped
to the `1102tools.com` zone. The read-only preflight verifies container-list
access, not every deployment permission. Successful deployment and live
verification are the enforced gate before any PyPI upload.
Do not copy the broader interactive Keychain token into CI, log credentials, or
commit them. PyPI continues using OIDC Trusted Publishing, without a PyPI API key.
The existing `mcp-registry-publish` environment retains its own registry secret.

Configure the credential before merging this change and triggering its first
release. Finish or explicitly cancel the older PyPI-only release first; its
workflow snapshot cannot gain the new Cloudflare job from a later commit.
The first release should be a new tag, not a rewrite of an existing public tag.

## Published ChatGPT metadata

The five original baseline `tools-contract.json` files were captured from the live hosted
endpoints; GSA Per Diem and Regulations.gov baselines were generated from source at their first hosted release (v1.0.32). The GSA Per Diem baseline was regenerated for 1.1.0 (bundled data, `openWorldHint`, no instructions) with `uv run --python 3.12 --frozen --project servers/gsa-perdiem-mcp python scripts/check_hosted_contract.py gsa-perdiem --write` (Python 3.13+ strips docstring indentation, so always regenerate under 3.12); review the diff before committing any regenerated baseline. Source and built-container checks must match them exactly, including
tool names, descriptions, schemas, annotations, and metadata. Containers use
Python 3.12, matching the currently hosted runtime; newer Python versions can
format docstrings differently. No server instructions are currently published;
the transport check also rejects unexpected instructions.

For a compatible backend fix, deploy to the same existing endpoint. If reviewed
tool metadata changes, complete the relevant directory review before approving
a new baseline and releasing that change. Do not regenerate baselines merely
to make the check pass. See the official
[OpenAI maintenance rules](https://developers.openai.com/plugins/deploy/app-review#how-published-mcp-metadata-versions-work).

## Verification and recovery

Each image is built once and passed as an artifact to deployment. Its health
response reports the release commit. After rollout, the pipeline verifies that
commit, package version, full tool list, and a representative tool call repeated
three times (plus service-specific checks: the publisher-key mode for the two
operator-keyed services, a live city lookup for GSA Per Diem, and compacted
search results for Regulations.gov). The overall release succeeds only if PyPI,
Cloudflare, and registry jobs succeed.

Between releases, `.github/workflows/hosted-health.yml` runs
`scripts/check_hosted_health.py` every 30 minutes against every hosted service
(health, initialize, one upstream tool call, publisher-key mode). For GSA Per
Diem, whose representative ZIP lookup uses bundled files, each run also makes
one GSA API city lookup, rotating through a list longer than the 24-hour
response cache, so a revoked publisher key (HTTP 403, reported as
`UpstreamKeyRejected`) or an exhausted rate limit (HTTP 429,
`UpstreamRateLimited`) fails the check. It opens one issue while anything fails
and closes it when all services pass again. Run it
locally with `python3 scripts/check_hosted_health.py [slug ...]` (Python 3.11+).

If Cloudflare deployment or verification fails, PyPI and registry publication
are skipped. Inspect the failed service and rerun failed jobs on the same tag.
If PyPI or registry publication fails afterward, hosted services may already
serve the new release; retry the failed publication jobs. Existing PyPI versions
are skipped only after the content guard has passed, and checked again afterward.
Do not overwrite a published version. A successful Cloudflare deployment does
not make the two destinations transactional.
Do not mark the release synchronized based only on a successful upload or health
check. Do not remove or rename a Worker, Container application, or endpoint to
work around a failed deployment.

For a broken production deployment, restore the last known-good Worker and its
Container image together. The preferred path keeps them in sync: dispatch this
workflow on the service's previous release tag (for example
`gsa-perdiem/v1.1.0`) with `services` set to that slug. It rebuilds that commit's
image and Worker and redeploys both; PyPI (`skip-existing`) and the registry
(duplicate versions are skipped) do not change. The deploy job also uploads the
prior Worker deployment list and Container description as the `previous-<slug>`
artifact (kept 30 days) for manual recovery. Wrangler's Worker rollback alone
must not be assumed to roll back the Container image. Preserve the existing
singleton application and rate-limit settings. Rolling back past a release that
changed tool metadata also rolls back reviewed directory metadata. Never attempt
to undo a PyPI publication by overwriting a package version; ship a corrective
patch.

## Operator-keyed services

GSA Per Diem and Regulations.gov call api.data.gov with a key held by 1102tools, one key per service. Each key is stored as a Worker secret (`PERDIEM_API_KEY` on `gsa-perdiem-mcp`, `REGULATIONS_GOV_API_KEY` on `regulations-gov-mcp`) and passed to the container at start. Secrets persist across deploys; rotate one with `wrangler secret put <NAME> --name <worker>` (a running container keeps the old value until it restarts, which happens after two idle minutes or on the next deploy). Both images set a hosted flag (`PERDIEM_HOSTED=1`, `REGULATIONS_HOSTED=1`): the server refuses to start without its key rather than falling back to the shared DEMO_KEY, and reports `hosted_publisher_key`, which release verification and the health check both require. The servers cap upstream calls at 950 per rolling hour, and hosted containers cache identical responses in memory (up to a day for Per Diem; 15 minutes and 24 MiB for Regulations.gov; the cache is lost when an idle container sleeps), so release verification's repeated call reaches upstream once per key.

From 1.1.0, GSA Per Diem answers ZIP, state, and M&IE lookups for bundled fiscal years from GSA's published files in the image (`servers/gsa-perdiem-mcp/src/gsa_perdiem_mcp/data/`); only city lookups and unbundled years use the key. Its release verification therefore adds one live `lookup_city_perdiem` call. Refresh the bundled data when GSA posts or corrects a file: run `scripts/build_snapshot.py`, run the live parity tests (`MCP_LIVE_TESTS=1 uv run pytest tests/test_live_parity.py` with a registered key), bump the package version, and release.

## Releasing one service

A `v*` tag push (for example `v1.0.33`) releases every package and hosted service. A scoped tag `<slug>/v<version>` (for example `gsa-perdiem/v1.1.0`, slugs from `deploy/services.json`) releases only that service and its package. A manual dispatch on a release tag can also set `services` to comma-separated slugs. `scripts/release_plan.py` scopes the build, deploy, PyPI, and registry jobs; unrelated services are not rebuilt or redeployed.
