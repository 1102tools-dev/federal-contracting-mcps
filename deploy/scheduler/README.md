# Load scheduler

This Cloudflare Worker has only a scheduled handler: no route, workers.dev address, preview URL, or fetch handler. It dispatches existing GitHub Actions workflows on `main`. GitHub cron remains a backup, and the loaders retain their existing concurrency groups, change-only imports, cost caps and locks.

| Workflow | Cloudflare cron (UTC) | Central time |
| --- | --- | --- |
| SAM opportunities | `15 */2 * * *` | Every two hours at :15 (odd hours CDT, even hours CST) |
| SAM public entities/exclusions | `15 */4 * * *` | Every four hours at :15 (03/07/11/15/19/23 CDT; 02/06/10/14/18/22 CST) |
| SAM public additional checks | `10 10 * * *`, `10 11 * * *` | 05:10 and 06:10 CDT; 04:10 and 05:10 CST |
| Acquisition.gov | `40 9 * * *` | 04:40 CDT; 03:40 CST |
| Hosted health | `7,37 * * * *` | Every hour at :07 and :37 |

Before dispatch, the Worker checks for queued, in-progress, requested, waiting and pending runs. An active run or an unreadable status response prevents dispatch. The workflow concurrency controls protect the remaining race between checking and dispatching.

The sole secret is `GITHUB_DISPATCH_TOKEN`, an existing fine-grained GitHub token restricted to Actions read/write on `1102tools-dev/federal-contracting-mcps`. Supply it through the existing macOS Keychain item directly to Wrangler stdin. Never place its value in a file, command argument or log. Production configuration declares it required; ordinary deployment preserves existing secret bindings.

Logs contain only workflow filenames and HTTP status codes. A `0` status indicates a missing credential, transport failure or malformed status response. The final POST normally returns `204`; GET checks normally return `200`. No response body, request headers, credential or exception message is logged. Hosted health retains its own alerting.

Run `npm ci`, `npm test`, `npm run check` and `npm run dry-run`. Deploy with `npm run deploy`; deploy and secret-management operations require the existing Cloudflare credentials. This Worker never reads or writes D1.
