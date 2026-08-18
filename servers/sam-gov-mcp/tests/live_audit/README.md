# Paced live-audit harness

A rate-disciplined prober for hunting real-API behavior that mocks can never
catch. This is the harness behind the round-10 findings in
[../../testing.md](../../testing.md): offset page-index semantics, the 400k
paging ceiling, past-the-end phantom rows and hangs, dead enum values, and
the rest.

## Why it exists

SAM.gov keys carry small daily quotas (10/day on the default plan), separate
throttle locks run to the next 00:00 UTC, and the gateway punishes bursts.
An unpaced test suite once spent an entire key in 105 seconds. This harness
makes that structurally impossible:

- one request at a time, jittered 2-4 s apart (slower is fine, faster is not)
- hard per-run call budget
- first 429 kills the run instantly, no retry
- two consecutive 5xx kill the run
- timeouts are recorded as findings (some endpoints hang on bad input)
- every call lands in `ledger.jsonl` with the key masked

## Usage

```bash
SAM_AUDIT_KEY=SAM-your-key AUDIT_BUDGET=20 python paced_probe.py
```

That runs the canonical round-10 regression suite (~12 calls). To write your
own probes, import `Prober` and compose:

```python
from paced_probe import Prober
p = Prober(key, budget=15)
body = p.call("label", "/opportunities/v2/search", {"postedFrom": "05/01/2026", ...})
p.check("my verdict", total=body.get("totalRecords"))
```

## Warnings

- Runs SPEND YOUR DAILY QUOTA. Know your key's plan before budgeting.
- `ledger.jsonl` and any captured responses can contain FOUO data when run
  with a federal-role key. Both patterns are gitignored; keep them local.
- This is not pytest. The pytest suite's live tests are gated separately
  (`SAM_LIVE_TESTS=1`, paced by `tests/conftest.py`, smoke subset via
  `-m live_smoke`).
