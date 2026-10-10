"""Release regression cases: silent PyPI skips and unsafe deployment ordering."""
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import zipfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "scripts/check_published_version.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def wheel(*, code=b"answer = 42\n", requirement="httpx>=0.27", python=">=3.11", entry="demo:main", prose="README", version="1.0.0", extra_file=False, generator="builder 1"):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        prefix = f"demo-{version}.dist-info/"
        archive.writestr("demo/__init__.py", code)
        if extra_file:
            archive.writestr("demo/data.json", '{"new": true}')
        archive.writestr(prefix + "METADATA", f"Metadata-Version: 2.4\nName: demo\nVersion: {version}\nRequires-Python: {python}\nRequires-Dist: {requirement}\n\n{prose}")
        archive.writestr(prefix + "WHEEL", f"Wheel-Version: 1.0\nGenerator: {generator}\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(prefix + "entry_points.txt", f"[console_scripts]\ndemo = {entry}\n")
        archive.writestr(prefix + "RECORD", "irrelevant generated record")
    return result.getvalue()


def published_fetcher(data, filename, *, yanked=False, digest=None):
    def fetch(url, **kwargs):
        if url.endswith("/json"):
            return json.dumps({"urls": [{"filename": filename, "packagetype": "bdist_wheel", "yanked": yanked, "url": "https://files.pythonhosted.org/demo.whl", "digests": {"sha256": digest or hashlib.sha256(data).hexdigest()}}]}).encode()
        return data
    return fetch


def local_wheel(tmp_path, **kwargs):
    version = kwargs.get("version", "1.0.0")
    path = tmp_path / f"demo-{version}-py3-none-any.whl"
    path.write_bytes(wheel(**kwargs))
    return path


def test_unchanged_rebuild_can_be_skipped(tmp_path):
    path = local_wheel(tmp_path, prose="new README", generator="new builder", requirement="httpx >= 0.27")
    assert guard.check_wheel(path, "demo", "1.0.0", fetcher=published_fetcher(wheel(), path.name)) == "published version matches"


@pytest.mark.parametrize("change", [
    {"code": b"answer = 43\n"},
    {"requirement": "httpx>=0.28"},
    {"python": ">=3.12"},
    {"entry": "demo:new_main"},
    {"extra_file": True},
])
def test_changed_existing_version_is_rejected(tmp_path, change):
    path = local_wheel(tmp_path, **change)
    with pytest.raises(guard.GuardError, match="increase its version"):
        guard.check_wheel(path, "demo", "1.0.0", fetcher=published_fetcher(wheel(), path.name))


def test_new_version_is_accepted_but_cannot_be_reported_as_published(tmp_path):
    path = local_wheel(tmp_path, version="1.0.1", code=b"changed")
    def fetch(url, **kwargs):
        return json.dumps({"info": {"version": "1.0.0"}}).encode() if url.endswith("/demo/json") else None
    assert guard.check_wheel(path, "demo", "1.0.1", fetcher=fetch) == "new version"
    with pytest.raises(guard.GuardError, match="not published"):
        guard.check_wheel(path, "demo", "1.0.1", fetcher=fetch, require_published=True)


def test_older_unpublished_version_is_rejected(tmp_path):
    path = local_wheel(tmp_path)
    def fetch(url, **kwargs):
        return json.dumps({"info": {"version": "1.0.1"}}).encode() if url.endswith("/demo/json") else None
    with pytest.raises(guard.GuardError, match="above the latest"):
        guard.check_wheel(path, "demo", "1.0.0", fetcher=fetch)


@pytest.mark.parametrize("options,match", [
    ({"yanked": True}, "non-yanked"),
    ({"digest": "0" * 64}, "SHA-256"),
    ({"filename": "other.whl"}, "matching"),
])
def test_invalid_published_artifact_fails_closed(tmp_path, options, match):
    path = local_wheel(tmp_path)
    options = {"filename": path.name, **options}
    with pytest.raises(guard.GuardError, match=match):
        guard.check_wheel(path, "demo", "1.0.0", fetcher=published_fetcher(wheel(), **options))


@pytest.mark.parametrize("error", [URLError("offline"), HTTPError("https://pypi.org", 503, "down", {}, None)])
def test_pypi_unavailable_is_not_treated_as_new_version(error):
    with patch.object(guard, "urlopen", side_effect=error), patch.object(guard.time, "sleep"):
        with pytest.raises(guard.GuardError, match="refusing to release"):
            guard.fetch("https://pypi.org/pypi/demo/1.0.0/json", missing_ok=True)


def test_404_is_distinct_from_auth_failure():
    for status in (404, 403):
        with patch.object(guard, "urlopen", side_effect=HTTPError("https://pypi.org", status, "error", {}, None)):
            if status == 404:
                assert guard.fetch("https://pypi.org", missing_ok=True) is None
            else:
                with pytest.raises(guard.GuardError):
                    guard.fetch("https://pypi.org", missing_ok=True)


def test_wheel_identity_must_match_project(tmp_path):
    path = local_wheel(tmp_path)
    with pytest.raises(guard.GuardError, match="identity"):
        guard.check_wheel(path, "other-package", "1.0.0")


def test_hosted_servers_send_no_instructions():
    # verify_hosted_release.py rejects initialize instructions in hosted-build,
    # after tagging. Catch them here from source, without importing servers.
    import ast
    services = json.loads((ROOT / "deploy/services.json").read_text())
    offenders = []
    for slug, service in services.items():
        path = ROOT / "servers" / service["package"] / "src" / service["module"] / "server.py"
        calls = [node for node in ast.walk(ast.parse(path.read_text()))
                 if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "MCPServer"]
        assert calls, f"{slug}: no MCPServer(...) call found in {path.relative_to(ROOT)}"
        if any(keyword.arg == "instructions" for call in calls for keyword in call.keywords):
            offenders.append(slug)
    assert not offenders, f"Hosted servers set instructions: {offenders}. Put guidance in tool results instead."


def test_release_dependency_gates_and_postpublication_verification():
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-pypi.yml").read_text())
    jobs = workflow["jobs"]
    # Default success() dependency handling must not be bypassed by always().
    for name in ("publish", "deploy-hosted", "publish-registry"):
        assert "if" not in jobs[name]
    assert "deploy-hosted" in jobs["publish"]["needs"]
    assert "test-and-build" in jobs["deploy-hosted"]["needs"]
    assert "publish" not in jobs["deploy-hosted"]["needs"]
    assert set(jobs["publish-registry"]["needs"]) == {"plan", "publish"}
    # Every matrix job takes its scope from the plan job, never a hard-coded list.
    for name in ("test-and-build", "publish", "hosted-build", "deploy-hosted"):
        assert "plan" in jobs[name]["needs"]
        matrix = jobs[name]["strategy"]["matrix"]
        assert "needs.plan.outputs" in str(matrix)
    steps = jobs["test-and-build"]["steps"]
    guard_step = next(i for i, step in enumerate(steps) if "check_published_version.py" in step.get("run", ""))
    upload_step = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert guard_step < upload_step
    assert not steps[guard_step].get("continue-on-error", False)
    assert "if" not in steps[guard_step]
    steps = jobs["publish"]["steps"]
    upload_step = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert any("--require-published" in step.get("run", "") for step in steps[upload_step + 1:])


def _release_plan():
    spec = importlib.util.spec_from_file_location('release_plan', ROOT / 'scripts/release_plan.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_plan_all_covers_every_package_and_service():
    plan = _release_plan().plan('all')
    hosted = json.loads(plan['hosted'])
    packages = json.loads(plan['packages'])
    assert set(hosted) == set(json.loads((ROOT / 'deploy/services.json').read_text()))
    assert {p['dir'] for p in packages} == {p.name for p in (ROOT / 'servers').iterdir() if (p / 'pyproject.toml').exists()}
    for p in packages:
        name = tomllib_name(ROOT / 'servers' / p['dir'] / 'pyproject.toml')
        assert p['pkg'] == name
    assert 'all hosted services' in plan['release_body']


def tomllib_name(path):
    import tomllib
    return tomllib.loads(path.read_text())['project']['name']


def test_release_plan_scopes_single_service():
    plan = _release_plan().plan('gsa-perdiem')
    assert json.loads(plan['hosted']) == ['gsa-perdiem']
    assert json.loads(plan['packages']) == [{'dir': 'gsa-perdiem-mcp', 'pkg': 'gsa-perdiem-mcp'}]
    assert plan['manifests'] == 'servers/gsa-perdiem-mcp/server.json'
    assert 'all' not in plan['release_body'].split()


def test_release_plan_rejects_unknown_service():
    with pytest.raises(SystemExit):
        _release_plan().plan('gsa-perdiem,not-a-service')


def test_release_plan_scoped_tag_limits_push_release():
    import tomllib
    rp = _release_plan()
    version = tomllib.loads((ROOT / 'servers/gsa-perdiem-mcp/pyproject.toml').read_text())['project']['version']
    assert json.loads(rp.plan('all', f'refs/tags/gsa-perdiem/v{version}')['hosted']) == ['gsa-perdiem']
    assert rp.plan('all', 'refs/tags/v1.0.33')['scope'] == 'all'
    with pytest.raises(SystemExit):
        rp.plan('all', 'refs/tags/not-a-service/v1.0.0')
    with pytest.raises(SystemExit):
        rp.plan('ecfr', f'refs/tags/gsa-perdiem/v{version}')


def test_release_plan_rejects_scoped_tag_with_wrong_version():
    with pytest.raises(SystemExit, match='pyproject.toml'):
        _release_plan().plan('all', 'refs/tags/gsa-perdiem/v0.0.1')


@pytest.mark.parametrize('ref', ['refs/tags/v9nonsense', 'refs/tags/v1.0', 'refs/tags/v01.0.1',
                                 'refs/tags/v1.0.33-rc1', 'refs/heads/main', 'refs/pull/7/merge'])
def test_release_plan_rejects_refs_that_are_not_release_tags(ref):
    with pytest.raises(SystemExit, match='not a release tag'):
        _release_plan().plan('all', ref)
    with pytest.raises(SystemExit, match='not a release tag'):
        _release_plan().plan('gsa-perdiem', ref)


def test_cloudflare_guard_matches_release_plan_tag_shapes():
    import re
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-pypi.yml").read_text())
    run = next(s["run"] for s in workflow["jobs"]["cloudflare-access"]["steps"] if "GITHUB_REF" in s.get("run", ""))
    pattern = re.search(r'=~ (\S+) \]\]', run).group(1)
    for ref in ('refs/tags/v1.0.33', 'refs/tags/gsa-perdiem/v1.1.1'):
        assert re.fullmatch(pattern, ref), ref
    for ref in ('refs/tags/v9nonsense', 'refs/tags/v1.0', 'refs/heads/main', 'refs/tags/gsa-perdiem/v1.1.1/x'):
        assert not re.fullmatch(pattern, ref), ref


def test_release_workflow_accepts_scoped_tags():
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-pypi.yml").read_text())
    trigger = workflow.get("on") or workflow.get(True)
    assert set(trigger["push"]["tags"]) == {"v*", "*/v*"}
    assert workflow["jobs"]["release"]["if"] == "startsWith(github.ref, 'refs/tags/')"


def test_post_upload_visibility_delay_preserves_payload_verification(tmp_path, monkeypatch):
    path=local_wheel(tmp_path);clock=[0];calls=[]
    matching=published_fetcher(wheel(),path.name)
    def fetch(url,**kw):
        calls.append(url)
        if url.endswith('/json') and clock[0]<10:return None
        return matching(url,**kw)
    monkeypatch.setattr(guard.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(guard.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    assert guard.check_wheel(path,'demo','1.0.0',require_published=True,fetcher=fetch,publication_wait_seconds=20)=='published version matches'
    assert clock[0]==10 and len(calls)==4


def test_post_upload_visibility_wait_is_bounded(tmp_path, monkeypatch):
    path=local_wheel(tmp_path);clock=[0]
    monkeypatch.setattr(guard.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(guard.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    with pytest.raises(guard.GuardError,match='not published'):
        guard.check_wheel(path,'demo','1.0.0',require_published=True,fetcher=lambda *a,**kw:None,publication_wait_seconds=12)
    assert clock[0]==12


def test_visibility_wait_never_retries_a_code_mismatch(tmp_path, monkeypatch):
    path=local_wheel(tmp_path,code=b'changed')
    def sleep(_):raise AssertionError('must not wait after a mismatch')
    monkeypatch.setattr(guard.time,'sleep',sleep)
    with pytest.raises(guard.GuardError,match='increase its version'):
        guard.check_wheel(path,'demo','1.0.0',require_published=True,fetcher=published_fetcher(wheel(),path.name),publication_wait_seconds=90)


@pytest.mark.parametrize("command,valid", [
    ("args: ['ecfr-mcp']", True),
    ("args: ['ecfr-mcp==1.0.10']", True),
    ("args: ['ecfr-mcp==1.0.1']", False),
    ("args: ['ecfr-mcp==1.0.10', 'ecfr-mcp==1.0.1']", False),
    ("command: 'python', args: ['-m', 'ecfr_mcp']", True),
    ("args: ['other-ecfr-mcp==1.0.1']", True),
])
def test_smithery_checks_explicit_pins_without_rejecting_latest_or_source(command, valid):
    spec = importlib.util.spec_from_file_location("versions", ROOT / "scripts/validate_versions.py")
    versions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(versions)
    assert versions.smithery_pins_match(command, "ecfr-mcp", "1.0.10") is valid

@pytest.mark.parametrize('failure', [None, 'html_timeout', 'pdf_metadata_only'])
def test_acquisition_release_gate_requires_real_html_and_pdf(monkeypatch, failure):
    spec = importlib.util.spec_from_file_location('hosted_verify', ROOT / 'scripts/verify_hosted_release.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    calls = []
    def request(url, payload=None, *, timeout_seconds=65):
        if payload is None:
            return {'release_sha': 'a' * 40}
        method = payload['method']
        if method == 'initialize':
            import tomllib
            version = tomllib.loads((ROOT / 'servers/acquisition-gov-mcp/pyproject.toml').read_text())['project']['version']
            return {'result': {'serverInfo': {'version': version}}}
        if method == 'tools/list':
            return {'result': {'tools': json.loads((ROOT / 'deploy/acquisition-gov/tools-contract.json').read_text())}}
        name = payload['params']['name']; calls.append(name)
        if name == 'get_rfo_part':
            if failure == 'html_timeout':
                return {'result': {'isError': True}}
            data = {'content': 'Part 52', 'total_characters': 1905514}
        elif name == 'list_rfo_agency_deviations':
            data = {'results': [{'source_id': 'test-official-nsf-document'}]}
        elif name == 'get_rfo_agency_deviation':
            data = {'text_extraction_status': 'error' if failure == 'pdf_metadata_only' else 'complete', 'page_numbered_text': 'actual PDF text'}
        else:
            data = {'count': 1}
        return {'result': {'structuredContent': data}}
    monkeypatch.setattr(verifier, 'request', request)
    monkeypatch.setattr('sys.argv', ['verify', 'acquisition-gov', '--sha', 'a' * 40])
    if failure:
        with pytest.raises((AssertionError, RuntimeError)):
            verifier.main()
    else:
        verifier.main()
        assert calls == ['list_rfo_parts'] * 3 + ['get_rfo_part', 'list_rfo_agency_deviations', 'get_rfo_agency_deviation']


@pytest.mark.parametrize('failure', [None, 'instructions', 'city_unresolved', 'demo_key'])
def test_perdiem_release_gate_requires_keyless_contract_and_live_city(monkeypatch, failure):
    spec = importlib.util.spec_from_file_location('hosted_verify', ROOT / 'scripts/verify_hosted_release.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    calls = []
    def request(url, payload=None, *, timeout_seconds=65):
        if payload is None:
            return {'release_sha': 'a' * 40,
                    'admission': {'processing': 16, 'waiting': 32, 'total': 48, 'deadline_seconds': 55}}
        method = payload['method']
        if method == 'initialize':
            import tomllib
            version = tomllib.loads((ROOT / 'servers/gsa-perdiem-mcp/pyproject.toml').read_text())['project']['version']
            result = {'serverInfo': {'version': version}}
            if failure == 'instructions':
                result['instructions'] = 'Call get_access_status first.'
            return {'result': result}
        if method == 'tools/list':
            return {'result': {'tools': json.loads((ROOT / 'deploy/gsa-perdiem/tools-contract.json').read_text())}}
        name = payload['params']['name']; calls.append(name)
        if name == 'get_data_status':
            data = {'live_lookup_access': 'hosted_key_missing' if failure == 'key_missing' else 'hosted_publisher_key'}
        elif name == 'lookup_city_perdiem':
            data = {'status': 'unresolved' if failure == 'city_unresolved' else 'resolved',
                    'source': {'kind': 'gsa_per_diem_api'}}
            if failure == 'demo_key':
                data['access_note'] = 'using DEMO_KEY'
        else:
            data = {'status': 'resolved', 'source': {'kind': 'bundled_gsa_files'}}
        return {'result': {'structuredContent': data}}
    monkeypatch.setattr(verifier, 'request', request)
    monkeypatch.setattr('sys.argv', ['verify', 'gsa-perdiem', '--sha', 'a' * 40])
    if failure:
        with pytest.raises((AssertionError, RuntimeError)):
            verifier.main()
    else:
        verifier.main()
        assert calls == ['get_data_status'] + ['lookup_zip_perdiem'] * 3 + ['lookup_city_perdiem']


def test_perdiem_release_gate_rejects_missing_publisher_key(monkeypatch):
    test_perdiem_release_gate_requires_keyless_contract_and_live_city(monkeypatch, 'key_missing')


@pytest.mark.parametrize('failure', [None, 'key_missing', 'uncompacted', 'demo_key', 'pre_deploy'])
def test_regulations_release_gate_requires_publisher_key_and_compact_results(monkeypatch, failure):
    spec = importlib.util.spec_from_file_location('hosted_verify', ROOT / 'scripts/verify_hosted_release.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    calls = []
    def request(url, payload=None, *, timeout_seconds=65):
        if payload is None:
            return {'release_sha': 'a' * 40,
                    'admission': {'processing': 16, 'waiting': 32, 'total': 48, 'deadline_seconds': 55}}
        method = payload['method']
        if method == 'initialize':
            import tomllib
            version = tomllib.loads((ROOT / 'servers/regulations-gov-mcp/pyproject.toml').read_text())['project']['version']
            return {'result': {'serverInfo': {'version': version}}}
        if method == 'tools/list':
            return {'result': {'tools': json.loads((ROOT / 'deploy/regulations-gov/tools-contract.json').read_text())}}
        name = payload['params']['name']; calls.append(name)
        if name == 'get_access_status':
            data = {'status': 'hosted_key_missing' if failure == 'key_missing' else 'hosted_publisher_key'}
        else:
            data = {'data': [{'id': 'FAR-2026-0001-0001'}], 'meta': {'totalElements': 1}}
            if failure == 'uncompacted':
                data['meta']['aggregations'] = {'agencyId': []}
            if failure == 'demo_key':
                data['access_note'] = 'Regulations.gov data is using the shared api.data.gov DEMO_KEY'
        return {'result': {'structuredContent': data}}
    monkeypatch.setattr(verifier, 'request', request)
    argv = ['verify', 'regulations-gov', '--sha', 'a' * 40]
    if failure == 'pre_deploy':
        argv += ['--base', 'http://localhost:8080', '--no-upstream']
    monkeypatch.setattr('sys.argv', argv)
    if failure in ('key_missing', 'uncompacted', 'demo_key'):
        with pytest.raises((AssertionError, RuntimeError)):
            verifier.main()
    else:
        verifier.main()
        expected = ['get_access_status'] if failure == 'pre_deploy' else (
            ['get_access_status'] + ['search_dockets'] * 3 + ['search_documents'])
        assert calls == expected


def _health_check():
    spec = importlib.util.spec_from_file_location('check_hosted_health', ROOT / 'scripts/check_hosted_health.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_perdiem_monitor_city_does_not_repeat_within_the_response_cache():
    hc = _health_check()
    runs_per_cache_ttl = 86400 // 1800  # scheduled every 30 minutes
    assert len(set(hc.PERDIEM_CITIES)) == len(hc.PERDIEM_CITIES) > runs_per_cache_ttl
    for start in (1, 500, 4242):
        cities = [hc.perdiem_city(run_number=n) for n in range(start, start + runs_per_cache_ttl + 1)]
        assert len(set(cities)) == len(cities)
    slots = [hc.perdiem_city(run_number='', now=1800 * n) for n in range(runs_per_cache_ttl + 1)]
    assert len(set(slots)) == len(slots)


def _mcp_stub(city_result):
    def request(url, payload=None, *, timeout_seconds=65):
        if url.endswith('/health'):
            return {'status': 'ok', 'release_sha': '001e536ae6'}
        name = payload['params'].get('name')
        if payload['method'] == 'initialize':
            return {'result': {'serverInfo': {'version': '1.1.1'}}}
        if name == 'get_data_status':
            return {'result': {'structuredContent': {'live_lookup_access': 'hosted_publisher_key'}}}
        if name == 'lookup_zip_perdiem':
            return {'result': {'structuredContent': {'status': 'resolved'}}}
        assert name == 'lookup_city_perdiem' and set(payload['params']['arguments']) == {'city', 'state'}
        return {'result': city_result}
    return request


def _error(text):
    return {'isError': True, 'content': [{'type': 'text', 'text': text}]}


def test_perdiem_monitor_requires_a_live_gsa_city_lookup(monkeypatch):
    hc = _health_check()
    service = {'endpoint': 'https://perdiem.example/mcp'}
    ok = {'structuredContent': {'status': 'resolved', 'source': {'kind': 'gsa_per_diem_api'}}}
    monkeypatch.setattr(hc._verify, 'request', _mcp_stub(ok))
    assert 'GSA API city lookup' in hc.check('gsa-perdiem', service)
    bundled = {'structuredContent': {'status': 'resolved', 'source': {'kind': 'gsa_bundled_snapshot'}}}
    monkeypatch.setattr(hc._verify, 'request', _mcp_stub(bundled))
    with pytest.raises(RuntimeError, match='expected resolved from gsa_per_diem_api'):
        hc.check('gsa-perdiem', service)


@pytest.mark.parametrize('text, error', [
    ("HTTP 403: the GSA Per Diem API rejected this service's credential.", 'UpstreamKeyRejected'),
    ('HTTP 429: the GSA Per Diem API rate limit was reached. Retry later.', 'UpstreamRateLimited'),
    ('Network error calling GSA Per Diem API: timed out', 'RuntimeError'),
])
def test_perdiem_monitor_reports_rejected_and_rate_limited_keys_separately(monkeypatch, text, error):
    hc = _health_check()
    monkeypatch.setattr(hc._verify, 'request', _mcp_stub(_error(text)))
    with pytest.raises(RuntimeError) as caught:
        hc.check('gsa-perdiem', {'endpoint': 'https://perdiem.example/mcp'})
    assert type(caught.value).__name__ == error and text in str(caught.value)


@pytest.mark.parametrize('failure', [None, 'pre_deploy', 'instructions', 'not_bundled', 'wrong_source'])
def test_bls_release_gate_requires_bundled_source(monkeypatch, failure):
    spec = importlib.util.spec_from_file_location('hosted_verify', ROOT / 'scripts/verify_hosted_release.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    calls = []
    def request(url, payload=None, *, timeout_seconds=65):
        if payload is None:
            return {'release_sha': 'a' * 40,
                    'admission': {'processing': 16, 'waiting': 32, 'total': 48, 'deadline_seconds': 55}}
        method = payload['method']
        if method == 'initialize':
            import tomllib
            version = tomllib.loads((ROOT / 'servers/bls-oews-mcp/pyproject.toml').read_text())['project']['version']
            result = {'serverInfo': {'version': version}}
            if failure == 'instructions':
                result['instructions'] = 'Call get_access_status first.'
            return {'result': result}
        if method == 'tools/list':
            return {'result': {'tools': json.loads((ROOT / 'deploy/bls-oews/tools-contract.json').read_text())}}
        name = payload['params']['name']; calls.append(name)
        if name == 'get_data_status':
            data = {'status': 'limited_fallback' if failure == 'not_bundled' else 'bundled', 'api_key_required': False}
        else:
            kind = 'bls_public_api' if failure == 'wrong_source' else 'bundled_bls_oews_files'
            data = {'wages': {'Annual Mean Wage': {'numeric': 148100}}, 'source': {'kind': kind}}
        return {'result': {'structuredContent': data}}
    monkeypatch.setattr(verifier, 'request', request)
    argv = ['verify', 'bls-oews', '--sha', 'a' * 40]
    if failure == 'pre_deploy':
        argv += ['--base', 'http://localhost:8080', '--no-upstream']
    monkeypatch.setattr('sys.argv', argv)
    if failure in ('instructions', 'not_bundled', 'wrong_source'):
        with pytest.raises((AssertionError, RuntimeError)):
            verifier.main()
    else:
        verifier.main()
        expected = ['get_data_status', 'get_wage_data']
        if failure is None:
            expected += ['get_wage_data'] * 3
        assert calls == expected


def test_bls_monitor_requires_the_bundled_source(monkeypatch):
    hc = _health_check()
    service = {'endpoint': 'https://bls.example/mcp'}
    def stub(kind):
        def request(url, payload=None, *, timeout_seconds=65):
            if url.endswith('/health'):
                return {'status': 'ok', 'release_sha': '8f87c41aaa'}
            if payload['method'] == 'initialize':
                return {'result': {'serverInfo': {'version': '1.1.0'}}}
            assert payload['params']['name'] == 'get_wage_data'
            return {'result': {'structuredContent': {'source': {'kind': kind, 'release': 'May 2025'}}}}
        return request
    monkeypatch.setattr(hc._verify, 'request', stub('bundled_bls_oews_files'))
    assert 'bundled May 2025 OEWS release' in hc.check('bls-oews', service)
    monkeypatch.setattr(hc._verify, 'request', stub('bls_public_api'))
    with pytest.raises(RuntimeError, match='expected bundled_bls_oews_files'):
        hc.check('bls-oews', service)


def test_monitor_fails_the_dell_row_when_the_container_is_serving(monkeypatch):
    hc = _health_check()
    services = {'ecfr': {'endpoint': 'https://ecfr.example/mcp', 'origin': 'https://ecfr-origin.example'},
                'usaspending': {'endpoint': 'https://usa.example/mcp', 'origin': 'https://usa-origin.example'}}
    monkeypatch.setattr(hc._verify, 'request', lambda url, payload=None: {'status': 'ok', 'release_sha': 'abc1234'})
    monkeypatch.setattr(hc, 'served_by', lambda url: 'origin')
    assert hc.check_origins(list(services), services) == []
    monkeypatch.setattr(hc, 'served_by', lambda url: 'origin' if 'usa' in url else 'container')
    assert hc.check_origins(list(services), services) == ['ecfr: answered by container (Dell on abc1234)']

    def down(url, payload=None):
        raise RuntimeError('Endpoint unavailable')
    monkeypatch.setattr(hc._verify, 'request', down)
    assert hc.check_origins(['ecfr'], services) == ['ecfr: Dell unreachable (RuntimeError)']


# Actual initialization must catch up with the deployed health SHA.
hosted_spec = importlib.util.spec_from_file_location("hosted_release", ROOT / "scripts/verify_hosted_release.py")
verifier = importlib.util.module_from_spec(hosted_spec)
hosted_spec.loader.exec_module(verifier)


def setup_service(tmp_path, monkeypatch, versions, *, instructions=None):
    (tmp_path / "deploy/demo").mkdir(parents=True)
    (tmp_path / "servers/demo-mcp").mkdir(parents=True)
    (tmp_path / "deploy/services.json").write_text(json.dumps({"demo": {"package": "demo-mcp", "endpoint": "https://example.test/mcp"}}))
    (tmp_path / "servers/demo-mcp/pyproject.toml").write_text('[project]\nversion="2.0.0"\n')
    (tmp_path / "deploy/demo/tools-contract.json").write_text("[]")
    state = {"clock": 0.0, "initializations": 0, "tools_lists": 0, "timeouts": []}
    def request(url, payload=None, **kwargs):
        state["timeouts"].append(kwargs.get("timeout_seconds", 65))
        if url.endswith("/health"):
            return {"release_sha": "new-sha", "admission": {"processing": 16, "waiting": 32, "total": 48, "deadline_seconds": 55}}
        if payload["method"] == "initialize":
            i = state["initializations"]
            state["initializations"] += 1
            result = {"serverInfo": {"version": versions[min(i, len(versions)-1)]}}
            if instructions: result["instructions"] = instructions
            return {"result": result}
        assert payload["method"] == "tools/list"
        state["tools_lists"] += 1
        return {"result": {"tools": []}}
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "request", request)
    monkeypatch.setattr(verifier.time, "monotonic", lambda: state["clock"])
    monkeypatch.setattr(verifier.time, "sleep", lambda seconds: state.update(clock=state["clock"]+seconds))
    monkeypatch.setattr(sys, "argv", ["verify_hosted_release.py", "demo", "--sha", "new-sha", "--wait-seconds", "25", "--no-upstream"])
    return state


def test_new_health_sha_waits_for_new_initialization_version(tmp_path, monkeypatch):
    state = setup_service(tmp_path, monkeypatch, ["1.0.0", "2.0.0"])
    verifier.main()
    assert state["initializations"] == 2
    assert state["clock"] == 10
    assert state["tools_lists"] == 1


def test_persistent_old_initialization_version_times_out_within_deadline(tmp_path, monkeypatch):
    state = setup_service(tmp_path, monkeypatch, ["1.0.0"])
    with pytest.raises(SystemExit, match="deadline"):
        verifier.main()
    assert state["clock"] == 25
    assert state["tools_lists"] == 0
    assert all(0 < timeout <= 25 for timeout in state["timeouts"])


def test_ready_version_still_rejects_unexpected_instructions(tmp_path, monkeypatch):
    state = setup_service(tmp_path, monkeypatch, ["2.0.0"], instructions="unexpected")
    with pytest.raises(AssertionError, match="instructions"):
        verifier.main()
    assert state["tools_lists"] == 0
