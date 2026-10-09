# Caching on the five Dell servers: progress

Plan: `~/Desktop/1102tools-handoff-4-dell-caching-2026-10-08.md`. Branch `claude/hosted-cache`,
worktree `.claude/worktrees/hosted-cache`. Started 2026-10-08 (late) at James's go ("do this work").

## Checklist

- [x] 0. Setup and map the code
- [ ] 1. Count which tools get called (Worker logs, no arguments)
- [x] 2. GSA CALC+ cache
- [x] 3. Federal Register cache
- [x] 4. eCFR cache (extend the existing one)
- [x] 5. USAspending cache
- [x] 6. Regulations.gov: longer cache for detail lookups
- [ ] 7. Checks, PR, James's go, release
- [ ] 8. Verify on the Dell
- [ ] 9. Measure the gains after about a week; update the progress page

## Where each server calls the government (step 0)

Each Dell container runs one uvicorn process (`http.py` / `regulations_key.py`), so an in-memory
cache is shared by every user of that server. Memory before caching (Oct 9, `docker stats`):
57-65 MiB of 384 MiB per server.

| Server | Every tool funnels through | Pacer | Government endpoints |
|---|---|---|---|
| GSA CALC+ | `_get(params_str)` in `server.py` | `GsaCalcPacer` (`_throughput.py`): 0.6 s, 2 at once, 500 attempts/hour | one: `BASE_URL?<query>` (ceiling rates; search, suggest, aggregations) |
| Federal Register | `_get(url)` in `server.py` | `FederalRegisterPacer`: 0.6 s, 2 at once, 500 per 5 min | `documents.json` (search_documents; open_comment_periods and far_case_history call search_documents), `documents/<n>.json` and `documents/<n1,n2>.json`, `documents/facets/<facet>`, `public-inspection-documents/current.json`, `agencies.json` |
| eCFR | `_get_json(path, params)`; `_get_xml` -> `XmlCache` -> `_get_xml_uncached` | `EcfrPacer` 0.6 s, 2 at once, 500 per 5 min; XML also `EcfrXmlPacer` | `versioner/v1/titles.json` (latest date; every "current" lookup), `versioner/v1/structure/<date>/...`, `versioner/v1/ancestry/<date>/...`, `versioner/v1/full/<date>/...` (XML), `versioner/v1/versions/...`, `search/v1/results` (+ counts), `admin/v1/agencies.json`, `admin/v1/corrections...` |
| USAspending | `_post(path, json)`, `_get(path, params)`, plus one inline GET in `get_recipient_children` | `USASpendingPacer`: 0.6 s, 4 at once, 500 per 5 min | `/api/v2/...`: search/*, awards/*, idvs/*, recipient/*, agency/*, references/*, autocomplete/*, federal_accounts/*, subawards/ |
| Regulations.gov | `_get(path, params)` in `server.py` | `_reserve_hourly_upstream()` (950/hour) + `FederalApiPacer` 0.6 s on the key | `documents`, `documents/<id>`, `comments`, `comments/<id>`, `dockets`, `dockets/<id>` |

Existing caches: Regulations.gov `_cache_get/_cache_put` (one 15-minute TTL, 24 MiB, no coalescing,
no stats); eCFR `XmlCache` (5 minutes, 128 entries, 32 MiB, coalesces misses with one lock).

## Design notes

- New canonical module `shared/response_cache.py`, vendored to each of the five packages as
  `_response_cache.py` by `scripts/sync_response_cache.py` (same pattern as the pacing helper).
- It stores the raw response bytes of a good 200 answer and each hit re-parses them, so a hit runs
  exactly the code an uncached call runs after its fetch (no shared mutable objects, exact sizes).
- Off unless `MCP_RESPONSE_CACHE=1` (set only in `deploy/<slug>/Dockerfile`). PyPI users unchanged.
- Hits never enter the pacer, so they use no spacing, no in-flight slot and no budget.
- Identical misses wait for the one government call already running (per-key, not one global
  lock, so the 2-4 in-flight limits still apply to different questions).

## Log

- **Step 1 code (2026-10-09):** `toolName()` / `logToolCall()` in `deploy/shared/edge.ts`; the five
  Dell-fronted Workers log `{"event":"tool_call","service","tool","backend","status","ms"}` after each
  answer. Tool name only, never arguments; a name that isn't a plain identifier logs as "other".
  Test in `deploy/shared/edge.test.ts` (17/17). `tsc` clean on four; Regulations.gov shows only its
  pre-existing container-class type error (same on main). Not deployed on its own: it ships with
  the step 7 releases (each release redeploys that service's Worker), so one deploy per service.
- **Shared module (2026-10-09):** `shared/response_cache.py` + `scripts/sync_response_cache.py` (vendors
  `_response_cache.py` into the five packages) + `tests/test_response_cache.py` (73 pass: off by
  default, hit/miss/expiry, LRU byte and entry limits, oversized answers served but not kept,
  errors/cancellations/bad bodies never kept, 10 concurrent identical misses -> 1 call, different
  questions still run in parallel, failed shared call -> waiters retry, cancelled waiter doesn't
  cancel the shared call, key canonicalization, five copies identical).
- **Step 2 GSA CALC+ 1.0.10 (2026-10-09):** `_get` -> `_cache.get_or_fetch(...)`; `_fetch` (paced call)
  runs only on a miss; `_parse_body` is the old JSON/dict check and runs on every hit and miss.
  12 h (GSA: ceiling-rate data refreshes once a day overnight, open.gsa.gov/api/dx-calc-api).
  48 MiB / 4 MiB per answer. `/health` has `cache`. `MCP_RESPONSE_CACHE=1` in
  `deploy/gsa-calc/Dockerfile`. Package tests 275 pass; new `tests/test_response_cache_hosted.py`
  proves with the real `GsaCalcPacer` budget file that a hit adds no start to the budget.
  Live check (record GSA answers once, replay with cache off/on): **22/22 identical**, 24 live GSA
  calls, repeat pass 0 GSA calls, median 0.60 s live vs 1.1 ms cached; 24 answers = 1.9 MB.
  Finding: GSA gives a different answer to the same question a second apart (an Elasticsearch
  `took` timing field and approximate percentiles), so live off-vs-on can't match byte for byte
  without replay; the cache also makes repeat answers consistent within 12 h.
- **Step 3 Federal Register 1.0.10 (2026-10-09):** `_get` -> cache; `_fetch` paced call on a miss only.
  Times by endpoint (`_cache_seconds`): `documents/<n>.json` and batches 24 h, `agencies.json` 24 h,
  `public-inspection-documents/current.json` 10 min, everything else (search_documents,
  facet counts, open_comment_periods, far_case_history) 1 h. far_case_history stays at 1 h, not the
  plan's 6 h: it runs through search_documents' endpoint and splitting it out wasn't worth the code.
  open_comment_periods keys on today's date, so its "as_of" always matches its data.
  48 MiB / 4 MiB. Tests 149 pass (4 old fakes now carry `.content` bytes like a real response).
  Live record/replay: **22/22 identical**; repeat pass made 1 call, the deliberate 404
  (errors are never kept); median 0.60 s live vs 0.5 ms cached.
- **Step 4 eCFR 1.0.11 (2026-10-09):** `_get_json` -> `ResponseCache` (24 MiB); `_fetch_json` keeps the
  exact old error messages (validates with `r.json()`), `_parse_json_body` runs on hits and misses.
  XML keeps `XmlCache` (it already coalesces; XML misses are serialized by the 3 s XML lane): locally
  unchanged (5 min, 128 entries, 32 MiB; it was already on for PyPI users), hosted it gets
  per-call times and 4096 entries / 40 MiB / 4 MiB per answer. Total 64 MiB. Times
  (`_cache_seconds`): dated full/structure/ancestry 24 h, or 6 h if the date is within the last
  7 days (what "current" resolves to); titles.json (latest date) 15 min; agencies 24 h; search,
  recent changes, versions, corrections 1 h. `/health` cache = JSON + XML counts. Tests 208 pass.
  Live record/replay: **22/22 identical**; 33 live calls with cache off vs 23 with it on (the
  latest-date lookup repeats inside one session); repeat pass 1 call (the deliberate 404);
  median 1.04 s live (up to 6.1 s on XML) vs 0.5 ms cached.
- **Step 5 USAspending 1.0.10 (2026-10-09):** `_post`, `_get`, and the inline GETs in
  `get_recipient_children` and `list_states` all go through `_cached()` -> `_send()` (the paced
  call, miss only). Key includes the canonical POST body. Times (`_cache_seconds`): references,
  autocompletes and the state list 24 h; `awards/last_updated` 15 min; `search/*`, `subawards/`,
  `awards/count/*`, recipient search and federal-account list 1 h; everything else (award, IDV,
  recipient, state profile, agency, federal-account details) 6 h. State *profile* is 6 h (it's
  spending data, like details); the state *list* is 24 h as the plan says. 48 MiB / 4 MiB.
  GETs keep their exact old call shapes (`list_states` sends no params argument). 11 old test
  fakes now carry `.content` bytes. Tests 1,806 pass. Live record/replay: **23/23 identical**;
  repeat pass 1 call (the deliberate missing award, errors never kept); median 0.60 s live (up to
  4.4 s) vs 0.1 ms cached.
- **Step 6 Regulations.gov 2.0.1 (2026-10-09):** old `_cache_get/_cache_put` replaced by the shared
  cache. `_fetch` (key, 950/hour reservation, pacer) runs only on a miss; it returns the answer
  re-serialized *after* key redaction, so the cache never holds the key. Details 6 h, searches and
  open comment periods 15 min. Null bodies answer {} and are never kept. 48 MiB / 2 MiB.
  `MCP_RESPONSE_CACHE=1` replaces `MCP_RESPONSE_CACHE_SECONDS=900` in the Dockerfile. Old cache
  tests ported (hit adds nothing to the hourly budget; key never stored). Tests 125 pass.
  Live record/replay: **22/22 identical**; repeat pass 3 calls (three IDs that don't exist; errors
  are never kept); median 0.81 s live vs 0.5 ms cached. Used the Keychain key
  `com.1102tools.api.REGULATIONS_GOV_API_KEY` (its own 1,000/hour bucket: 999 left at the probe),
  not the Worker's publisher key. api.data.gov `DEMO_KEY` was exhausted (429, retry in ~20 h).
- CI: `publish-pypi.yml` shared-safety-tests runs `sync_response_cache.py --check` and
  `tests/test_response_cache.py`; `release-guard-checks.yml` too. New repo test: the five hosted
  Dockerfiles set `MCP_RESPONSE_CACHE=1`.
- **Step 7 checks (2026-10-09):** `test_release_guards.py` 64 pass; `test_hosted_admission.py` 97 pass;
  `sync_pacing.py --check` and `sync_response_cache.py --check` clean; `validate_versions.py` 9 ok;
  `check_hosted_contract.py` unchanged for all five (8, 8, 13, 55, 9 tools) under Python 3.11 like
  CI. (Under this Mac's Python 3.14 every tool shows "changed": 3.13+ strips docstring
  indentation. Environmental, not a tool change.) All five package suites and the shared tests
  also pass on 3.11. Release versions: gsa-calc 1.0.10, federal-register 1.0.10, ecfr 1.0.11,
  usaspending 1.0.10, regulations-gov 2.0.1.
