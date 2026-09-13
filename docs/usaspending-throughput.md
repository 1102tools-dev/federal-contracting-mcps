# USAspending throughput update

> Historical throughput test record. Hosted HTTP admission was subsequently raised to 16 processing plus 32 FIFO waiting slots in v1.0.26. See [current pacing and queue limits](pacing.md).

USAspending 1.0.8 replaces completion-serialized three-second pacing with a
500-attempt rolling 300-second budget, 0.6-second start spacing, and four
cross-process in-flight slots. Other providers keep their existing policies.

The existing common `_pacing.py` remains synchronized and unchanged. The new
USAspending-only `_throughput.py` reuses its identity, atomic state writer,
Retry-After handling and same-loop lock registry. The state lock protects
reservations only. Four separate OS locks protect concurrent requests and
recover automatically if a process dies. Failed and cancelled attempts retain
their reservation. Corrupt history fails closed instead of resetting a budget.
Positive interval overrides cannot speed starts beyond the default; the explicit
zero opt-out remains for offline tests and externally controlled applications.

The hosted entrance binding changes from 60 to 120 requests per 60 seconds.
This per-IP, per-location approximate limiter includes protocol traffic and is
separate from the upstream budget. The existing singleton container, four-call
admission guard, 64 KiB body guard and 55-second request timeout remain.
Pacing state is shared within the backend, not across independently hosted
machines. Container replacement can reset the local on-disk history. Upgrade
local processes together; old and new pacing implementations must not share the
state directory concurrently.

## Verification

Run the package suite and `tests/test_throughput.py` for rolling windows,
failed-attempt accounting, start spacing, real overlap, cross-process
coordination, crash recovery, cancellation cleanup, shared Retry-After and
corrupt-state rejection. Existing shared pacing and release-guard tests apply.
The hosted tool contract must remain exactly equal to its published baseline.

A bounded transport test sends 120 protocol requests over roughly one minute;
a separate workload sends 500 read-only calls over roughly five minutes.
Stop on upstream or application failure; do not retry automatically. Verify
hosted commit, version, tool contract, errors and latency after release.

Release through the existing version-tag workflow: source and image checks,
Cloudflare deployment and live verification, PyPI content verification, then
the MCP registry. Restore both Worker and Container image if production fails;
Worker rollback alone does not restore the backend image.
