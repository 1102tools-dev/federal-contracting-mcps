# Hosted HTTP queue verification

Release v1.0.26, September 13, 2026. Applies to USAspending, GSA CALC+, eCFR and Federal Register. Acquisition.gov retains its previous admission settings.

Each hosted backend changes from **4 processing / 0 waiting** to **16 processing / 32 FIFO waiting**, with **48 accepted HTTP requests total per service**. The **55-second total deadline includes upload, waiting and processing**. The Worker entrance limit stays at 120 HTTP requests per minute per incoming IP and location. Provider pacing, upstream concurrency, budgets and CALC+'s persistent hourly admission counter are unchanged.

## Offline regression coverage

`tests/test_hosted_admission.py` runs against the canonical implementation and each of its four packaged copies:

- 48 accepted requests, with request 49 rejected with HTTP 429 and `Retry-After: 5`.
- FIFO promotion, immediate slot reuse, and no remaining active/waiting counts after completion.
- Cancellation and actual ASGI disconnects during processing, queueing and promotion.
- Total deadline covering waiting and processing, cancellation of unfinished work, and no second response after headers have started.
- 64 KiB request-body bound, oversized individual/chunked bodies, and disconnect during upload.
- Slot release after application exceptions and unchanged lifespan forwarding.
- Byte-for-byte consistency between the shared source and all four installed package copies.

The four package HTTP suites also exercise the real MCP SDK, tool catalog, host/origin guards, body limit and `/health` configuration. Release verification checks the deployed commit, installed package version, unchanged tool contract and exact 16/32/48/55 health metadata.

Run the queue regression suite without provider traffic:

```sh
uv run --with pytest --with pytest-asyncio --with starlette pytest -q tests/test_hosted_admission.py
```

## Representative local HTTP burst

A separate loopback HTTP test used the USAspending admission wrapper with a simulated provider, 48 simultaneous requests, 64 KiB request bodies, 1 MiB responses, 0.6-second provider start spacing, two upstream slots and 0.1-second simulated response latency. It made **zero government API requests**. **48/48 completed in 28.36 seconds. Peak backend RSS was 84.9 MiB on the local macOS test process.**

This verifies the queue under that workload, not arbitrary provider response sizes, Cloudflare CPU scheduling or client deadlines. Slow upstream calls, XML cache misses, exhausted provider budgets, process restarts and an already full queue can still prevent completion. The queue is bounded in-process work, not persistent background jobs.
