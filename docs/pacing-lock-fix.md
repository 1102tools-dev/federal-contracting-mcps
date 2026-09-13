# Pacing lock fix (v1.0.20)

Issue [#10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)
reported requests hanging after FileLock acquisition and release ran on different
executor threads. All nine Python packages shared the affected helper.

The fix keeps non-blocking lock acquisition and release on the event-loop thread,
with cancellable async polling while another process holds the lock. Existing
minimum intervals and Retry-After cooldowns remain in effect. Merely disabling
FileLock thread-local state is insufficient with newer thread-local deadlock
bookkeeping, so the release uses the same-thread fix previously deployed in the
Cloudflare hosting branch (92ff4b5).

## Updated packages

| Package | Fixed version |
|---|---|
| acquisition-gov-mcp | 1.0.3 |
| bls-oews-mcp | 1.0.10 |
| ecfr-mcp | 1.0.7 |
| federal-register-mcp | 1.0.6 |
| gsa-calc-mcp | 1.0.6 |
| gsa-perdiem-mcp | 1.0.10 |
| regulationsgov-mcp | 1.0.9 |
| sam-gov-mcp | 1.0.13 |
| usaspending-gov-mcp | 1.0.6 |

Upgrade the package in the environment that launches your MCP server, then
restart or reconnect the MCP client to replace any already-wedged process.
Update any explicitly pinned version in the client configuration. For uvx-based
setups, use `uvx --refresh --from ecfr-mcp==1.0.7 ecfr-mcp` (substitute the package
and executable for your server). For pip installations, use
`python -m pip install --upgrade ecfr-mcp` in the server environment.

Hosted ChatGPT connections use separately deployed Cloudflare images and do not
install these PyPI packages on the user's computer. The hosting branch already
contained this pacing fix before this package release.

## Regression coverage

The shared tests exercise repeated requests while forcing executor-thread
changes, upstream exceptions, cancellation inside a request, state-write errors,
cancellation while waiting for a held lock, and cross-process serialization.
The release workflow runs shared tests on Linux and Windows with filelock 3.13.1
and the current release, then runs the offline suite for every server before
publishing packages.
