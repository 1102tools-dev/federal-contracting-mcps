# Fast Acquisition.gov re-parse and publish

From this repository on the Mac, run:

```sh
uv run --frozen --project servers/acquisition-gov-mcp python scripts/reparse_and_publish_acquisition_gov.py
```

The Mac needs the existing `govnode` SSH connection and `CLOUDFLARE_D1_TOKEN` or `CLOUDFLARE_API_TOKEN` in its environment. The Dell needs the seeded raw cache at `/var/lib/acquisition-gov-raw`, the isolated source checkout at `/var/lib/acquisition-gov-raw/work`, and `/usr/local/bin/uv`. Do not run this during another load or publication.

This command re-extracts every cached resource offline on the Dell, checks that requests and downloads are both zero, and makes a consistent parsed SQLite backup. It copies only that parsed snapshot and timing statistics to the Mac. The existing Mac publisher verifies the uploaded rows before switching the current D1 snapshot. A failed parse or transfer stops before publishing; a failed upload leaves the prior hosted snapshot serving.

The Cloudflare token stays on the Mac. Cloudflare environment variables are removed from SSH and SCP processes and the Dell parser. Raw PDFs and their URL/hash manifest remain on the Dell. There is no download mode in this command. New or changed PDFs require the separate cached loader; actual download requests retain three-second spacing.

The command prints re-parse and publication timings plus output paths. `--output /absolute/path` retains parsed data and statistics in a chosen local folder; otherwise they remain in a new system temporary folder. Each run uses its own directory beneath `/var/lib/acquisition-gov-raw/output` and does not replace the seed backup or the active local database. These parsed output directories can be removed later when their evidence is no longer needed.

This workflow leaves `/opt/mcp-origin`, its compose configuration and containers, the five Dell serving caches, the Worker serving code, the D1 data shape, and the nightly GitHub Actions loader unchanged. The nightly loader remains the fallback. README and testing.md are unchanged.

## Nightly raw-cache synchronization

On `govnode`, `acquisition-gov-raw-sync.timer` starts `acquisition-gov-raw-sync.service` every night at 03:30 `America/Chicago`, including daylight-saving changes. The Dell's system timezone remains `Etc/UTC`; the timer explicitly names the user's local timezone. `Persistent=true` catches up a missed run after the timer starts again. The service runs as `james`, who owns `/var/lib/acquisition-gov-raw`, using the isolated checkout and virtual environment beneath its `work` directory. The unit templates are in `deploy/acquisition-gov/cache-sync/`.

The standalone sync command reuses the 1.0.13 loader's downloader and three-second request spacing. It refreshes the FAR Overhaul index and uses conditional requests to retain unchanged PDFs, downloading only new or changed bodies when the origin supports validators. Without validators, downloaded bytes are compared by SHA-256. This nightly operation does not extract PDF text, create a parsed snapshot, or publish to D1. Cloudflare credentials remain on the Mac. Re-parse and publish still use the Mac command above.

Files are written through temporary files and atomic renames. PDFs removed from the index are retained beneath `/var/lib/acquisition-gov-raw/_removed/`. If the index has fewer than 80% of the previous PDF count, synchronization exits unsuccessfully and does not prune the cache. Do not start synchronization while the initial seed is running; later sync and re-parse commands share a cache lock.

To run a synchronization by hand from the Mac:

```sh
ssh govnode 'sudo systemctl start acquisition-gov-raw-sync.service'
```

That command waits for the service to finish. Conditional checks still obey three-second spacing, so a complete nightly sync takes about as long as the original download pass; cached re-parsing remains fast. The timer will not start a second instance while the service is already running.

For a short acceptance check of the index and the first 25 PDFs, run this as the cache owner on the Dell:

```sh
env -u CLOUDFLARE_API_TOKEN -u CLOUDFLARE_D1_TOKEN -u CF_API_TOKEN FEDERAL_API_PACING_DIR=/var/lib/acquisition-gov-raw/pacing /var/lib/acquisition-gov-raw/work/servers/acquisition-gov-mcp/.venv/bin/python /var/lib/acquisition-gov-raw/work/scripts/sync_acquisition_gov_raw_cache.py --raw-cache /var/lib/acquisition-gov-raw --limit 25
```

The limit applies only to that manual check; the timer has no limit and checks the full index nightly. A limited run does not archive removed PDFs. Its status reports the checked sample separately from the full index count.

Read the completed run's status and timer schedule:

```sh
ssh govnode 'cat /var/lib/acquisition-gov-raw/_sync-status.json'
ssh govnode 'systemctl list-timers acquisition-gov-raw-sync.timer --no-pager'
ssh govnode 'journalctl -u acquisition-gov-raw-sync.service -n 30 --no-pager'
```

The status file records `finished_at`, `index_count`, `cached_count`, `added`, `changed`, `removed`, and `errors`. A healthy unchanged run has `changed=0` and `errors=0`. A failed run returns a nonzero service exit status; inspect the journal and status file before running the Mac publisher. The sync command and units are operational scripts outside the Python package, so they do not require another PyPI release.
