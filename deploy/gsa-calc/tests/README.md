# Hosted hourly budget tests

`npm test` runs the deterministic SQLite and bounded-request tests. `npm run
check` includes those tests, so hosted build CI runs them before deployment.

For a real local workerd check without Docker or upstream API traffic:

```sh
npx wrangler dev --local --config tests/wrangler.jsonc --ip 127.0.0.1 --port 8789 --persist-to /path/to/test-state
```

The local-only harness accepts `{"now":1000000}` to reserve at a simulated time
in milliseconds, and an optional `cooldown` in seconds to record provider
backoff. Its clock controls and endpoint are never imported by production.
Send 510 concurrent reservations at the same time: exactly 500 must be admitted.
Stop and restart Wrangler with the same persistence directory: the next request
must still be denied. Advancing `now` by 3,600,000 must free the expired budget.
A recorded cooldown must likewise survive restart and must not be shortened by
a later, smaller cooldown. Use a fresh test-state directory for an independent
run; never reset production state for a benchmark.
