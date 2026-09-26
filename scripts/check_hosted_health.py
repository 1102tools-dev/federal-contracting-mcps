"""Scheduled production check for every hosted MCP service.

For each service in deploy/services.json: /health is ok, initialize answers,
one representative tool call succeeds upstream, and operator-keyed services
report that they run on the publisher key (not a DEMO_KEY fallback).
Prints a Markdown report; exits 1 if any service fails. Read-only.
"""
import argparse, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify_hosted_release", ROOT / "scripts/verify_hosted_release.py")
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)
KEY_MODE = {"gsa-perdiem": ("get_data_status", "live_lookup_access"),
            "regulations-gov": ("get_access_status", "status")}


def check(slug, service):
    base = service["endpoint"].removesuffix("/mcp")
    health = _verify.request(base + "/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"/health status {health.get('status')!r}")
    ident = [0]

    def rpc(method, params):
        ident[0] += 1
        data = _verify.request(base + "/mcp", {"jsonrpc": "2.0", "id": ident[0], "method": method, "params": params})
        if data.get("error") or data.get("result", {}).get("isError"):
            raise RuntimeError(f"{method} returned an error")
        return data["result"]

    init = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                              "clientInfo": {"name": "1102tools-health-check", "version": "1"}})
    if slug in KEY_MODE:
        name, field = KEY_MODE[slug]
        mode = rpc("tools/call", {"name": name, "arguments": {}}).get("structuredContent", {}).get(field)
        if mode != "hosted_publisher_key":
            raise RuntimeError(f"credential mode is {mode!r}, expected hosted_publisher_key")
    name, arguments = _verify.CASES[slug]
    result = rpc("tools/call", {"name": name, "arguments": arguments})
    data = result.get("structuredContent")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"{name} returned an error result")
    return f"{init['serverInfo']['version']} at {health.get('release_sha', '?')[:7]}"


def main():
    p = argparse.ArgumentParser(); p.add_argument("slugs", nargs="*"); args = p.parse_args()
    services = json.loads((ROOT / "deploy/services.json").read_text())
    rows, failed = [], []
    for slug in args.slugs or list(services):
        try:
            rows.append(f"| {slug} | ok | {check(slug, services[slug])} |")
        except Exception as e:  # noqa: BLE001 - report every service
            failed.append(slug)
            rows.append(f"| {slug} | **FAILED** | {type(e).__name__}: {str(e)[:160]} |")
    print("| Service | Result | Detail |\n|---|---|---|\n" + "\n".join(rows))
    if failed:
        print(f"\nFailing: {', '.join(failed)}. Check the service's /health, its Worker secret, and "
              "upstream API status; see docs/unified-release.md for rollback.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
