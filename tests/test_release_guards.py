"""Release regression cases: silent PyPI skips and unsafe deployment ordering."""
import hashlib
import importlib.util
import io
import json
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


def test_release_dependency_gates_and_postpublication_verification():
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-pypi.yml").read_text())
    jobs = workflow["jobs"]
    # Default success() dependency handling must not be bypassed by always().
    for name in ("publish", "deploy-hosted", "publish-registry"):
        assert "if" not in jobs[name]
    assert "deploy-hosted" in jobs["publish"]["needs"]
    assert "test-and-build" in jobs["deploy-hosted"]["needs"]
    assert "publish" not in jobs["deploy-hosted"]["needs"]
    assert jobs["publish-registry"]["needs"] == "publish"
    steps = jobs["test-and-build"]["steps"]
    guard_step = next(i for i, step in enumerate(steps) if "check_published_version.py" in step.get("run", ""))
    upload_step = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert guard_step < upload_step
    assert not steps[guard_step].get("continue-on-error", False)
    assert "if" not in steps[guard_step]
    steps = jobs["publish"]["steps"]
    upload_step = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert any("--require-published" in step.get("run", "") for step in steps[upload_step + 1:])


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
    def request(url, payload=None):
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
            data = {'text_extraction_status': 'error' if failure == 'pdf_metadata_only' else 'complete', 'content': 'actual PDF text'}
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
