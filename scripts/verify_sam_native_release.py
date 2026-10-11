"""Gate the native SAM Worker release against its own contract and public D1 data."""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = {
    "search_opportunities", "get_opportunity", "get_data_status",
    "search_entities", "search_exclusions", "summarize_opportunities",
}


def release_version(ref, source):
    """Accept only the native stable tag family and its matching Worker version."""
    tag = re.fullmatch(r"refs/tags/sam-gov-hosted/v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))", ref)
    version = re.search(r'const SERVER_VERSION = "([^"]+)";', source)
    if tag is None:
        raise ValueError("Use a sam-gov-hosted/vX.Y.Z release tag")
    if version is None or version[1] != tag[1]:
        raise ValueError("Native Worker version differs from release tag")
    return tag[1]


def request(url, payload=None):
    headers = {"Accept": "application/json, text/event-stream"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def rpc(base, method, params):
    response = request(base + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if response.get("error"):
        raise RuntimeError(f"MCP error for {method}: {response['error']}")
    result = response["result"]
    if result.get("isError"):
        raise RuntimeError(f"Tool failed: {params.get('name')}")
    return result


def call(base, name, arguments):
    result = rpc(base, "tools/call", {"name": name, "arguments": arguments})
    data = result.get("structuredContent")
    if data is None:
        data = json.loads(result["content"][0]["text"])
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError(f"Invalid result from {name}")
    return data


def verify_contract(actual, expected):
    assert len(actual) == len(expected) == 6, "Expected exactly six native tools"
    assert {tool["name"] for tool in actual} == TOOL_NAMES, "Native tool names differ"
    assert sorted(actual, key=lambda t: t["name"]) == sorted(expected, key=lambda t: t["name"]), "Published definitions differ"
    for tool in actual:
        annotations = tool.get("annotations", {})
        assert (tool.get("title") or annotations.get("title")) and annotations.get("readOnlyHint") is True, f"Missing directory metadata: {tool['name']}"


def verify_status(status):
    for kind, minimum in (("entities", 100000), ("exclusions", 10000)):
        extract = status[kind]
        assert extract.get("available") is True, f"{kind} data unavailable"
        assert extract.get("row_count", 0) >= minimum, f"{kind} public load too small"
        assert extract.get("file_name") and extract.get("file_date"), f"{kind} provenance missing"


def verify_provenance(result, status):
    assert result.get("file_name") == status["file_name"], "Source filename differs"
    assert result.get("file_date") == status["file_date"], "Source file date differs"


def verify(base, sha, version, contract):
    health = request(base + "/health")
    assert health.get("status") == "ok" and health.get("release_sha") == sha, "Release SHA differs"
    assert health.get("tools") == 6, "Health does not report six tools"
    init = rpc(base, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "sam-native-release-check", "version": "1"}})
    assert init["serverInfo"]["version"] == version, "Native server version differs"
    tools = rpc(base, "tools/list", {})["tools"]
    verify_contract(tools, contract)
    status = call(base, "get_data_status", {})
    verify_status(status)
    entities = call(base, "search_entities", {"size": 10})
    verify_provenance(entities, status["entities"])
    records = entities["entityData"]
    assert records, "Entity search returned no real records"
    uei = records[0]["entityRegistration"]["ueiSAM"]
    entity = call(base, "search_entities", {"uei": uei})
    verify_provenance(entity, status["entities"])
    assert any(row["entityRegistration"]["ueiSAM"] == uei for row in entity["entityData"]), "Real entity UEI lookup failed"
    exclusions = call(base, "search_exclusions", {"size": 10})
    verify_provenance(exclusions, status["exclusions"])
    assert exclusions["excludedEntity"], "Exclusion search returned no real records"
    candidates = [row["exclusionIdentification"] for row in exclusions["excludedEntity"]]
    identification, field = next(((record, key) for record in candidates
                                  for key in ("ueiSAM", "cageCode", "entityName") if record.get(key)), (None, None))
    assert field and identification, "Real exclusion sample has no searchable identifier"
    argument = {"ueiSAM": "uei", "cageCode": "cage_code", "entityName": "entity_name"}[field]
    exclusion = call(base, "search_exclusions", {argument: identification[field]})
    verify_provenance(exclusion, status["exclusions"])
    assert any(row["exclusionIdentification"].get(field) == identification[field] for row in exclusion["excludedEntity"]), "Real exclusion lookup failed"
    return {"version": version, "release_sha": sha, "tools": len(tools), "data_status": status,
            "entity_probe_uei": uei, "exclusion_probe": {argument: identification[field]}, "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--base", default="https://sam.1102tools.com")
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    contract = json.loads((ROOT / "deploy/sam-gov/tools-contract.json").read_text())
    deadline = time.monotonic() + args.wait_seconds
    while True:
        try:
            evidence = verify(args.base.rstrip("/"), args.sha, args.version, contract)
            break
        except (AssertionError, RuntimeError, OSError, ValueError, KeyError) as error:
            if time.monotonic() >= deadline:
                raise SystemExit(f"SAM native release verification failed: {error}") from error
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    output = json.dumps(evidence, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
