# Federal Register throughput and keyless test findings

Federal Register 1.0.8 uses a 500-attempt rolling
300-second budgets, minimum 0.6-second request starts, and two in-flight slots.
The previous implementation serialized requests and waited three seconds after
completion. This policy is a tested 1102tools safeguard, not an agency quota.
It does not promise 500 completed tool calls: upstream latency, retries initiated
by callers, and tools that make multiple requests affect useful throughput.

The service retains its existing pacing identity and common `_pacing.py`.
A service-specific `_throughput.py` reserves an attempt under a short state
lock, then releases that lock before network I/O. Separate OS locks enforce
concurrency and recover when a process exits. Failed and cancelled attempts
remain counted, Retry-After cooldowns are shared, and corrupt history fails
closed. Positive environment overrides cannot accelerate beyond 0.6 seconds;
explicit zero remains an opt-out for offline or externally paced clients.

Local processes using the same pacing directory share a budget. Independent
computers do not. Each hosted singleton has its own budget shared by that
service's users. Container replacement can reset local pacing history. Upgrade
local processes together rather than sharing a directory between old and new
pacing implementations.

## Hosted configuration

Federal Register changes from 60 to 120 HTTP requests per minute.
These are separate Worker bindings, not a global Cloudflare setting and not the
upstream budgets. The entrance limiter is approximate, per IP and Cloudflare
location, and includes protocol traffic. Singleton hosting, four-call HTTP
admission, 64 KiB request bodies, and 55-second request timeouts remain in place.
The eCFR and CALC+ Workers retain their existing limits and pacing policies in this change.

## September 13, 2026 validation

Short trials used the real MCP HTTP application and upstream APIs with small
mixed queries. A test-only scheduler compared the current three-second gap,
one-second starts and 0.6-second starts, with at most two concurrent callers.
A subsequent sustained trial counted 500 upstream attempts per service,
including one setup request for Federal Register. All returned valid HTTP 200
payloads without tool errors or retries.

| Service | Sustained workload | Elapsed | Upstream p95 |
| --- | --- | --- | --- |
| GSA CALC+ | 500 calls | 300.61 s | 0.553 s |
| Federal Register | 499 calls plus one setup call | 299.71 s, excluding setup | 0.073 s |

The workload varied search pages and small query terms; it did not test every
tool, large downloads, cold-cache behavior for every response, or indefinite
load. Repeated responses may benefit from upstream caching. Stop conditions
include HTTP or tool errors, invalid payloads, and material latency regression.
Five-minute quiet periods separate trials; this is an experimental precaution,
not a claimed agency reset period.

The new pacer has tests for rolling windows, attempt accounting, minimum start
spacing, overlap, multiple processes, crash recovery, cancellation, Retry-After,
legacy state and corruption. Source tool contracts must match the published
baselines. Release uses the existing tagged pipeline with all package tests,
container contract checks, hosted rollout/verification, PyPI and MCP registry
verification. Hosted verification uses bounded protocol and real-tool workloads.

## eCFR finding

eCFR did not pass the same acceleration experiment. Filtered section XML
responses remained valid but grew substantially slower. A separate XML trial
had upstream p95 of 0.153 seconds with six seconds after completion, then 4.081
seconds with three-second starts. The trial stopped on latency regression.
This suggests upstream queuing or soft throttling but does not establish its
cause or a numeric quota. Do not accelerate its mixed JSON/XML workload based
on successful HTTP status alone.

## CALC+ finding

CALC+ passed the initial five-minute trial, but the actual candidate-code trial
received HTTP 429 at upstream attempt 425, after 424 successes. The provider
returned Retry-After: 2221 seconds. Testing stopped immediately, including a
queued second caller which never reached the upstream API. No automatic retry
was made. Across the recorded pilot and sustained trials there had been 991
upstream attempts, including this rejection. This is consistent with an
additional longer-window quota, but does not prove its exact size, scope or
window type. The indicated wait ended around 09:00 UTC on September 13, 2026.

The CALC+ acceleration candidate was withheld. Do not infer sustainable
500-per-five-minute capacity from the first successful run. A future CALC+
policy needs an independently checked longer-window budget as well as fast
short-batch spacing. The current public CALC+ documentation does not specify a
numeric quota: https://open.gsa.gov/api/dx-calc-api/.

## Actual Federal Register candidate confirmation

The real production pacer then completed all 500 upstream requests (one setup
and 499 workload calls), with no upstream or tool errors. The workload took
300.64 seconds, with upstream p95 0.077 seconds and end-to-end local MCP p95
3.020 seconds. This test used the file-backed rolling budget and concurrency
locks, not the test-only scheduler. The Federal Register package suite passed
144 tests with 100 opt-in tests skipped; its nine pacing regressions passed.
Shared safety and release checks passed 31 tests. Published tool definitions
were unchanged, version validation passed, and the Worker type check and
production dry-run passed with the separate 120-per-minute entrance binding.
