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
