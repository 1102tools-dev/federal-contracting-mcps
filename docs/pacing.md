# MCP request pacing and hosted limits

Verified against repository commit `4bbabe781bf23740b95327393372be90b53b4ea9`, September 13, 2026.

## Default request pacing

These numbers describe the MCP's configured safeguards. They are not agency-published quotas or guaranteed response times. An upstream request is a request from the MCP to its government data source. One tool call may require multiple upstream requests.

| MCP and package version | Minimum time between upstream request starts | Maximum upstream requests in flight | Rolling upstream attempt budget |
| --- | --- | --- | --- |
| USAspending 1.0.8 | 0.6 seconds | 4 | 500 per 300 seconds (5 minutes) |
| GSA CALC+ 1.0.8 | 0.6 seconds | 2 | 500 per 3,600 seconds (1 hour) |
| eCFR 1.0.9, JSON requests | 0.6 seconds | 2 across JSON and XML combined | 500 per 300 seconds (5 minutes), across JSON and XML combined |
| Federal Register 1.0.8 | 0.6 seconds | 2 | 500 per 300 seconds (5 minutes) |

A 0.6-second minimum start interval permits approximately 1.67 request starts per second, or 100 per minute, while budget and concurrency slots remain available. It does not mean two or four requests start every 0.6 seconds. The concurrency number is how many requests may still be awaiting responses at once.

A rolling window counts attempts during the immediately preceding 300 or 3,600 seconds; it does not reset at a fixed clock boundary. Failed and cancelled upstream attempts remain counted. Slow upstream responses and provider cooldowns can reduce the achieved rate.

CALC+ can serve a short batch at the 0.6-second pace, but it cannot sustain 500 requests every five minutes. Its default hourly budget is 500. If those attempts are consumed in approximately five minutes, the earliest attempts begin leaving the hourly window approximately 55 minutes later.

### eCFR XML requests and repeated text retrieval

- **Uncached XML:** one XML fetch at a time, with a minimum three-second wait after the previous XML fetch completes. XML misses also use the shared 500-attempt/five-minute budget and one of the two upstream concurrency slots.
- **Cached XML:** an eligible response is retained for up to 300 seconds (five minutes). A cache hit makes zero additional XML downloads and skips the XML pacing wait. A tool may still need JSON requests, for example to resolve the latest date.
- **Cache bounds:** 128 entries, 32 MiB total, and 2 MiB per entry. Entries may be evicted before five minutes when capacity is needed. Larger XML responses are not cached.
- **Cache identity:** the date, URL path and filters identify a cached response. Repeated requests for different dates or sections are separate entries. Concurrent duplicate misses reuse one download.
- **Freshness:** errors are not cached. An upstream correction to cached content can take up to five minutes to appear, or sooner after eviction/restart.

## Local installation versus the hosted plugin

The following hosting table applies to USAspending, GSA CALC+, eCFR and Federal Register. Acquisition.gov retains a separate 60-request/minute entrance limit, as documented below.

The default upstream pacing above is the same code in both installation methods. The difference is who shares its budget and which additional hosting limits apply. Connecting any AI client to a 1102tools hosted URL has the hosted behavior, even if that client runs on your computer.

| Limit or resource | Local process / stdio installation | 1102tools hosted endpoint, including ChatGPT plugins |
| --- | --- | --- |
| Upstream budget and concurrency | Shared by processes using the same pacing directory and pacing identity; independent installations do not share that local counter | Shared by all users of that particular hosted MCP, regardless of their incoming IP addresses |
| Cloudflare entrance limit | Does not apply to a local process calling the data source directly | 120 HTTP requests per 60 seconds, per incoming IP seen by Cloudflare, per Cloudflare location, per MCP service |
| Hosted backend admission | Does not apply to stdio | At most 4 active MCP HTTP requests across the service's users |
| Hosted backend processing timeout | Does not apply to stdio; the package/client's own timeouts still apply | 55 seconds per admitted backend request; startup/network time may add latency |
| Hosted request-body limit | Does not apply to stdio | 65,536 bytes (64 KiB) |

The four services in the first table have separate hosted budgets, concurrency slots and Cloudflare rate-limit counters. USAspending use does not consume eCFR, CALC+ or Federal Register capacity.

**Example:** ten people using the hosted USAspending MCP share its 500-attempt/five-minute budget and four upstream slots. They do not each receive 500 attempts and four slots. Two independent local installations each maintain their own MCP budget, although the government API may impose additional limits on traffic sharing an outbound IP or credential.

### Shared IP addresses: two different parts of the request path

1. **AI client to Cloudflare:** the 120-per-minute entrance counter uses the calling IP visible to Cloudflare. If several people share that IP and reach the same Cloudflare location, they share that entrance counter for the same MCP. For a cloud AI service, the calling IP may belong to that service rather than the user's phone or computer. Different incoming IPs still share the hosted backend's upstream budget.
2. **MCP to the government data source:** hosted requests leave through the hosting infrastructure. The data provider may impose additional limits on that outbound traffic. Local users also may share an outbound address through an office, home router or VPN. Separate local pacing files do not create separate agency allowances.

Cloudflare's entrance limit is approximate and location-specific. It is an additional admission check, not a dedicated 120-request allowance for each person. [Cloudflare rate-limiting documentation](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)

The entrance counter includes MCP initialization, tool discovery, pings, tool requests and health checks. Therefore, 120 HTTP requests/minute is not the same as 120 upstream data requests/minute. A tool can make multiple upstream calls, while an XML cache hit can avoid an upstream download.

### Budget persistence and retry behavior

Local pacing history persists in its configured directory; deleting that directory removes its history. Update local processes together rather than mixing old and new pacing implementations against one directory.

For hosted USAspending, eCFR and Federal Register, the upstream pacing history is stored on the container filesystem and can reset when the container is replaced or restarted. It is a pacing safeguard, not durable usage accounting.

CALC+ additionally reserves each hosted tool request in persistent Durable Object SQLite storage. Its 500-tool-request/hour admission counter and observed provider cooldown survive container restarts. All eight current CALC+ tools make at most one upstream request. Failed or invalid hosted tool requests consume an admission; protocol-only requests do not. The response header `X-1102tools-Hourly-Remaining` reports that hosted admission balance, not an agency allowance.

- **Cloudflare entrance limit:** HTTP 429, with `Retry-After: 60`.
- **All four backend admission slots busy:** HTTP 429, with `Retry-After: 5`.
- **Backend processing timeout:** HTTP 504 if the response has not started.
- **CALC+ hourly budget exhausted or a long provider cooldown:** an MCP tool error with a retry interval; the HTTP status can still be 200. Clients must check MCP `isError` as well as HTTP status.
- **Provider throttling:** observed `Retry-After` extends the relevant shared cooldown. The MCP does not automatically retry the failed upstream call.

## Other servers: current default pacing

These servers were not accelerated in the September 13 changes. Their pacers serialize requests and wait after completion; the next start is therefore separated by the previous request's duration plus the listed delay.

| MCP | Default wait after a request completes | Maximum requests in flight per pacing identity | Rolling attempt counter in this pacer |
| --- | --- | --- | --- |
| SAM.gov | 3 seconds | 1 | None; provider/key quotas still apply |
| BLS OEWS | 3 seconds | 1 | None; provider/key quotas still apply |
| GSA Per Diem | 4 seconds | 1 | None; provider/key quotas still apply |
| Regulations.gov | 4 seconds | 1 | None; provider/key quotas still apply |
| Acquisition.gov | 3 seconds | 1 | None; source-site limits still apply |

Pacing identities incorporate the API bucket and credential where applicable. GSA Per Diem and Regulations.gov both use the `api.data.gov` bucket: using the same credential and pacing directory makes them share the same gate. Different computers can still share provider-side limits when they use the same key.

### Acquisition.gov hosted limits

The Acquisition.gov hosted endpoint has a **60 HTTP requests per 60 seconds** entrance limit, per incoming IP and Cloudflare location. Its shared backend admits **4 active MCP HTTP requests**, with a **55-second backend processing timeout** and **64 KiB request-body limit**. All hosted users share its one-upstream-request-at-a-time gate and three-second completion delay. These settings were not changed by the four-server acceleration work.

## Configuration and evidence

The tables describe defaults. `FEDERAL_API_MIN_INTERVAL_SECONDS` can override pacing. In the four accelerated packages, positive values below 0.6 are clamped to 0.6; eCFR XML retains a three-second minimum for positive values. Explicit zero disables pacing for externally managed/offline use. The hosted deployments use 0.6 and do not expose that override to plugin users. `FEDERAL_API_PACING_DIR` determines the local coordination directory.

The other five pacers use the configured positive interval directly, with the defaults shown above. Changing this setting does not increase the government's quota.

See [USAspending throughput evidence](usaspending-throughput.md), [CALC+, eCFR and Federal Register evidence](keyless-throughput.md), individual server testing records, each service's `_throughput.py` or `_pacing.py`, and `deploy/<service>/wrangler.jsonc` for implementation and test evidence.
