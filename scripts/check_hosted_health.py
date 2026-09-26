"""Scheduled production check for every hosted MCP service.

For each service in deploy/services.json: /health is ok, initialize answers,
one representative tool call succeeds upstream, and operator-keyed services
report that they run on the publisher key (not a DEMO_KEY fallback).
Prints a Markdown report; exits 1 if any service fails. Read-only.

GSA Per Diem's representative ZIP lookup is served from bundled files, and its
status tool only proves a key is configured. So each run also looks up one city
through the GSA API, rotating through PERDIEM_CITIES so that no city repeats
within the hosted 24-hour response cache: a revoked or rate-limited publisher
key then fails the check instead of hiding behind cached or bundled data.
"""
import argparse, importlib.util, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify_hosted_release", ROOT / "scripts/verify_hosted_release.py")
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)
KEY_MODE = {"gsa-perdiem": ("get_data_status", "live_lookup_access"),
            "regulations-gov": ("get_access_status", "status")}
# Each resolved as an exact GSA API match for FY2027 on 2026-09-26. 79 runs at
# one per 30 minutes is about 39 hours, longer than the 86,400-second cache.
PERDIEM_CITIES = [
    ("Huntsville", "AL"), ("Gulf Shores", "AL"), ("Hot Springs", "AR"), ("Sedona", "AZ"), ("Tucson", "AZ"),
    ("Fresno", "CA"), ("Monterey", "CA"), ("Napa", "CA"), ("Visalia", "CA"), ("Stockton", "CA"),
    ("Santa Rosa", "CA"), ("Aspen", "CO"), ("Durango", "CO"), ("Telluride", "CO"), ("Montrose", "CO"),
    ("Hartford", "CT"), ("New Haven", "CT"), ("Lewes", "DE"), ("Key West", "FL"), ("Sarasota", "FL"),
    ("Tallahassee", "FL"), ("Pensacola", "FL"), ("Sebring", "FL"), ("Naples", "FL"), ("Savannah", "GA"),
    ("Athens", "GA"), ("Boise", "ID"), ("Bloomington", "IN"), ("Lexington", "KY"), ("New Orleans", "LA"),
    ("Nantucket", "MA"), ("Pittsfield", "MA"), ("Worcester", "MA"), ("Annapolis", "MD"), ("Ocean City", "MD"),
    ("Ann Arbor", "MI"), ("Traverse City", "MI"), ("Petoskey", "MI"), ("Midland", "MI"), ("Duluth", "MN"),
    ("Oxford", "MS"), ("Starkville", "MS"), ("Helena", "MT"), ("Missoula", "MT"), ("Asheville", "NC"),
    ("Greensboro", "NC"), ("Omaha", "NE"), ("Laconia", "NH"), ("Portsmouth", "NH"), ("Flemington", "NJ"),
    ("Taos", "NM"), ("Carlsbad", "NM"), ("Ithaca", "NY"), ("Glens Falls", "NY"), ("Binghamton", "NY"),
    ("Lake Placid", "NY"), ("Sandusky", "OH"), ("Bend", "OR"), ("Seaside", "OR"), ("Gettysburg", "PA"),
    ("Hershey", "PA"), ("State College", "PA"), ("Myrtle Beach", "SC"), ("Rapid City", "SD"),
    ("Chattanooga", "TN"), ("Knoxville", "TN"), ("Galveston", "TX"), ("Pecos", "TX"), ("Moab", "UT"),
    ("Provo", "UT"), ("Blacksburg", "VA"), ("Lynchburg", "VA"), ("Roanoke", "VA"), ("Stowe", "VT"),
    ("Montpelier", "VT"), ("Spokane", "WA"), ("Sturgeon Bay", "WI"), ("Charles Town", "WV"), ("Cody", "WY"),
]


class UpstreamKeyRejected(RuntimeError):
    """The upstream API returned HTTP 403 for the publisher key."""


class UpstreamRateLimited(RuntimeError):
    """The upstream API returned HTTP 429 for the publisher key."""


def perdiem_city(run_number=None, now=None):
    """The city for this run: by workflow run number, else by 30-minute slot."""
    run_number = run_number if run_number is not None else os.environ.get("GITHUB_RUN_NUMBER")
    slot = int(run_number) if run_number else int((time.time() if now is None else now) // 1800)
    return PERDIEM_CITIES[slot % len(PERDIEM_CITIES)]


def tool_error(name, result):
    """Classify a tool error result; the server has already redacted its text."""
    text = " ".join(c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict))[:300]
    if "HTTP 403" in text:
        return UpstreamKeyRejected(f"{name}: upstream rejected the publisher key (HTTP 403). {text}")
    if "HTTP 429" in text:
        return UpstreamRateLimited(f"{name}: upstream rate limit reached (HTTP 429). {text}")
    return RuntimeError(f"{name} returned an error. {text}".strip())


def check(slug, service):
    base = service["endpoint"].removesuffix("/mcp")
    health = _verify.request(base + "/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"/health status {health.get('status')!r}")
    ident = [0]

    def rpc(method, params):
        ident[0] += 1
        data = _verify.request(base + "/mcp", {"jsonrpc": "2.0", "id": ident[0], "method": method, "params": params})
        if data.get("error"):
            raise RuntimeError(f"{method} returned an error")
        if data.get("result", {}).get("isError"):
            raise tool_error(params.get("name", method), data["result"])
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
    detail = f"{init['serverInfo']['version']} at {health.get('release_sha', '?')[:7]}"
    if slug == "gsa-perdiem":
        city, state = perdiem_city()
        data = rpc("tools/call", {"name": "lookup_city_perdiem",
                                  "arguments": {"city": city, "state": state}}).get("structuredContent") or {}
        kind = (data.get("source") or {}).get("kind")
        if data.get("status") != "resolved" or kind != "gsa_per_diem_api":
            raise RuntimeError(f"city lookup {city}, {state} was {data.get('status')!r} from {kind!r}, "
                               "expected resolved from gsa_per_diem_api")
        detail += f"; GSA API city lookup {city}, {state} resolved"
    return detail


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
