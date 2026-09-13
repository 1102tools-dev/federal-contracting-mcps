# Unified MCP releases

A versioned GitHub release builds the Python packages and the five hosted MCP
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
- `deploy/services.json` lists the five hosted services, package paths, existing
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
  live verification must succeed for all five services before PyPI starts.
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

The five baseline `tools-contract.json` files were captured from the live hosted
endpoints. Source and built-container checks must match them exactly, including
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
commit, package version, full tool list, and three real upstream tool requests.
The overall release succeeds only if PyPI, Cloudflare, and registry jobs succeed.

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
Container image together using the recorded prior deployment. Wrangler's Worker
rollback alone must not be assumed to roll back the Container image. Preserve
the existing singleton application and rate-limit settings. Never attempt to
undo a PyPI publication by overwriting a package version; ship a corrective patch.
