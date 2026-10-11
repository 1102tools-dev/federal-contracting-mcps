"""Native release gate regressions, isolated from live SAM and Cloudflare."""
import copy
import io
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sam_native_release", ROOT / "scripts/verify_sam_native_release.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize("payload", [None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}])
def test_health_and_rpc_requests_identify_native_verification_client(monkeypatch, payload):
    observed = []

    def urlopen(request, timeout):
        observed.append(request)
        return io.BytesIO(b'{"status":"ok"}')

    monkeypatch.setattr(gate, "urlopen", urlopen)
    url = "https://sam.1102tools.com/health" if payload is None else "https://sam.1102tools.com/mcp"
    assert gate.request(url, payload) == {"status": "ok"}
    assert observed[0].get_header("User-agent") == "1102tools-sam-native-release-verification/1.0"
    assert observed[0].get_method() == ("GET" if payload is None else "POST")


def tools():
    return [{"name": name, "annotations": {"title": name, "readOnlyHint": True}, "inputSchema": {"type": "object"}} for name in gate.TOOL_NAMES]


def status():
    return {kind: {"available": True, "file_name": f"{kind}.ZIP", "file_date": "2026-10-11", "row_count": count} for kind, count in (("entities", 100000), ("exclusions", 10000))}


def test_contract_rejects_metadata_drift_even_with_six_tools():
    expected = tools()
    gate.verify_contract(expected, expected)
    actual = copy.deepcopy(expected)
    actual[0]["inputSchema"]["additionalProperties"] = False
    with pytest.raises(AssertionError, match="definitions"):
        gate.verify_contract(actual, expected)


@pytest.mark.parametrize("kind", ["entities", "exclusions"])
@pytest.mark.parametrize("change", [{"available": False}, {"row_count": 2}, {"file_date": None}, {"file_name": None}])
def test_status_rejects_unavailable_small_or_unattributed_extract(kind, change):
    data = status()
    data[kind].update(change)
    with pytest.raises(AssertionError):
        gate.verify_status(data)


@pytest.mark.parametrize("exclusion_identification,exclusion_argument", [
    ({"ueiSAM": "MNOPQRSTUVWX", "entityName": "EXCLUDED FIXTURE"}, {"uei": "MNOPQRSTUVWX"}),
    ({"cageCode": "ABCDE", "entityName": "EXCLUDED FIXTURE"}, {"cage_code": "ABCDE"}),
    ({"entityName": "EXCLUDED FIXTURE"}, {"entity_name": "EXCLUDED FIXTURE"}),
])
def test_release_requires_matching_real_lookup_and_provenance(monkeypatch, exclusion_identification, exclusion_argument):
    contract = tools()
    data = status()
    entity = {"entityRegistration": {"ueiSAM": "ABCDEFGHIJKL"}}
    exclusion = {"exclusionIdentification": exclusion_identification}
    calls = []
    monkeypatch.setattr(gate, "request", lambda url: {"status": "ok", "release_sha": "abc", "tools": 6})
    monkeypatch.setattr(gate, "rpc", lambda base, method, params: {"serverInfo": {"version": "1.1.0"}} if method == "initialize" else {"tools": contract})

    def call(base, name, arguments):
        calls.append((name, arguments))
        if name == "get_data_status":
            return data
        kind, field, record = ("entities", "entityData", entity) if name == "search_entities" else ("exclusions", "excludedEntity", exclusion)
        records = [record]
        if name == "search_exclusions" and "size" in arguments:
            # Individual public rows can omit every identifier searchable by the API.
            records.insert(0, {"exclusionIdentification": {"entityName": None, "ueiSAM": None, "cageCode": None, "firstName": "ALICE", "lastName": "FIXTURE"}})
        return {"file_name": data[kind]["file_name"], "file_date": data[kind]["file_date"], field: records}

    monkeypatch.setattr(gate, "call", call)
    assert gate.verify("https://fixture", "abc", "1.1.0", contract)["verified"] is True
    assert ("search_entities", {"uei": "ABCDEFGHIJKL"}) in calls
    assert ("search_exclusions", exclusion_argument) in calls
    original = call

    def empty_lookup(base, name, arguments):
        result = original(base, name, arguments)
        if name == "search_entities" and "uei" in arguments:
            result["entityData"] = []
        return result

    monkeypatch.setattr(gate, "call", empty_lookup)
    with pytest.raises(AssertionError, match="UEI lookup"):
        gate.verify("https://fixture", "abc", "1.1.0", contract)


@pytest.mark.parametrize("version", ["1.1.0", "1.2.3", "10.20.30", "0.0.1"])
def test_tag_version_follows_native_worker(version):
    assert gate.release_version(f"refs/tags/sam-gov-hosted/v{version}", f'const SERVER_VERSION = "{version}";') == version


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/tags/v1.1.0", "refs/tags/sam-gov/v1.1.0", "refs/tags/ecfr/v1.1.0", "refs/tags/sam-gov-hosted/v01.1.0", "refs/tags/sam-gov-hosted/v1.1.0-rc1", "refs/tags/sam-gov-hosted/v1.1"])
def test_tag_guard_rejects_other_scopes_and_nonstable_versions(ref):
    with pytest.raises(ValueError, match="release tag"):
        gate.release_version(ref, 'const SERVER_VERSION = "1.1.0";')


def test_tag_guard_rejects_worker_version_mismatch():
    with pytest.raises(ValueError, match="differs"):
        gate.release_version("refs/tags/sam-gov-hosted/v1.2.0", 'const SERVER_VERSION = "1.1.0";')


def test_native_workflow_is_tag_guarded_and_verifies_before_release():
    source = (ROOT / ".github/workflows/sam-gov-native-release.yml").read_text()
    workflow = yaml.safe_load(source)
    release = workflow["jobs"]["release"]
    assert release["environment"] == "cloudflare-production"
    steps = release["steps"]
    names = [step.get("name", "") for step in steps]
    assert names.index("Deploy SAM native Worker") < names.index("Verify deployed SHA, six tools, and public extracts") < names.index("Publish verified native release")
    assert "tags: ['sam-gov-hosted/v*']" in source
    assert "release_version(os.environ['GITHUB_REF'], source)" in source
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in source
    assert "--var RELEASE_SHA:$GITHUB_SHA" in source
    assert "docker " not in source and "configure_hosted_image" not in source
    assert "sam-gov/v" not in str(steps)
    assert "tests/test_sam_public_parity.py" in source
    assert "--version \"$SAM_NATIVE_VERSION\"" in source
    token_steps = [step["name"] for step in steps if "CLOUDFLARE_API_TOKEN" in step.get("env", {})]
    assert token_steps == ["Deploy SAM native Worker"]
