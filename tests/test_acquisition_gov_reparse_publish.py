"""Offline orchestration regressions; never contact Dell or Cloudflare."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reparse_and_publish_acquisition_gov as fast

ID = "a" * 32
STATS = {"mode": "reparse", "requests": 0, "downloads": 0, "seconds": 12.3}


@pytest.fixture
def fixed_id(monkeypatch):
    monkeypatch.setattr(fast.uuid, "uuid4", lambda: SimpleNamespace(hex=ID))


def receipt(**stats):
    directory = f"{fast.REMOTE_ROOT}/output/fast-{ID}"
    return {"snapshot": directory + "/snapshot.sqlite", "stats": directory + "/stats.json", "reparse": {**STATS, **stats}}


def test_only_parsed_files_transfer_before_mac_publication(tmp_path, fixed_id):
    calls = []
    environment = {"PATH": "/bin", "CLOUDFLARE_API_TOKEN": "mac-only-secret", "CLOUDFLARE_ACCOUNT_ID": "account"}

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "ssh":
            return SimpleNamespace(stdout=json.dumps(receipt()))
        if command[0] == "scp":
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout=json.dumps({"snapshot": 10, "publish_seconds": 4}))

    result = fast.run(output=tmp_path, runner=runner, environment=environment)
    assert [command[0] for command, _ in calls] == ["ssh", "scp", "scp", sys.executable]
    assert [command[-2].split("/")[-1] for command, _ in calls[1:3]] == ["snapshot.sqlite", "stats.json"]
    for command, kwargs in calls[:3]:
        assert kwargs["env"] == {"PATH": "/bin"}
        assert "mac-only-secret" not in str(command) + kwargs.get("input", "")
        assert "SendEnv=-*" in command
    assert calls[-1][1]["env"] == environment
    assert calls[-1][0][-2:] == ["--local", str(tmp_path / "snapshot.sqlite")]
    assert result["reparse"]["seconds"] == 12.3
    assert json.loads((tmp_path / "publish-stats.json").read_text())["snapshot"] == 10


@pytest.mark.parametrize("failure_at", [0, 1, 2, 3])
def test_failure_stops_sequence(tmp_path, fixed_id, failure_at):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if len(calls) - 1 == failure_at:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout=json.dumps(receipt()))

    with pytest.raises(subprocess.CalledProcessError):
        fast.run(output=tmp_path, runner=runner, environment={"CLOUDFLARE_D1_TOKEN": "secret"})
    assert len(calls) == failure_at + 1
    assert not (tmp_path / "publish-stats.json").exists()


@pytest.mark.parametrize("bad_receipt", [receipt(downloads=1), receipt(requests=1), receipt(mode="reload"), {**receipt(), "snapshot": "/var/lib/acquisition-gov-raw/bodies/raw.pdf"}])
def test_unexpected_receipt_prevents_transfer_and_publish(tmp_path, fixed_id, bad_receipt):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=json.dumps(bad_receipt))

    with pytest.raises(RuntimeError):
        fast.run(output=tmp_path, runner=runner, environment={"CLOUDFLARE_API_TOKEN": "secret"})
    assert len(calls) == 1


def test_missing_mac_token_does_not_start_reparse(tmp_path):
    def runner(*args, **kwargs):
        pytest.fail("A remote process must not start without a Mac publication token")

    with pytest.raises(RuntimeError, match="on the Mac"):
        fast.run(output=tmp_path, runner=runner, environment={})


def test_remote_program_backs_up_only_after_offline_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fast, "REMOTE_ROOT", str(tmp_path))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "must-not-reach-parser")
    seen = []

    def parse(command, **kwargs):
        seen.append(command)
        assert command[-1] == "--reparse"
        assert "--remote" not in command and "--full" not in command
        assert kwargs["cwd"] == tmp_path / "work"
        assert not any(key.startswith("CLOUDFLARE") for key in kwargs["env"])
        path = Path(command[command.index("--local") + 1])
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE parsed (value TEXT)")
            db.execute("INSERT INTO parsed VALUES ('parsed text')")
        return SimpleNamespace(stdout=json.dumps(STATS))

    monkeypatch.setattr(subprocess, "run", parse)
    exec(compile(fast.remote_program(ID), "remote-program", "exec"), {})
    result = json.loads(capsys.readouterr().out)
    with sqlite3.connect(result["snapshot"]) as db:
        assert db.execute("SELECT value FROM parsed").fetchone() == ("parsed text",)
    assert json.loads(Path(result["stats"]).read_text()) == STATS
    assert len(seen) == 1


@pytest.mark.parametrize("failed_stats", [None, {**STATS, "downloads": 1}])
def test_remote_parse_failure_never_creates_publishable_backup(tmp_path, monkeypatch, failed_stats):
    monkeypatch.setattr(fast, "REMOTE_ROOT", str(tmp_path))

    def parse(command, **kwargs):
        if failed_stats is None:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout=json.dumps(failed_stats))

    monkeypatch.setattr(subprocess, "run", parse)
    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        exec(compile(fast.remote_program(ID), "remote-program", "exec"), {})
    directory = tmp_path / "output" / ("fast-" + ID)
    assert not (directory / "snapshot.sqlite").exists()
    assert not (directory / "stats.json").exists()


def test_rejects_shell_options_in_host(tmp_path):
    with pytest.raises(ValueError):
        fast.run(host="-oProxyCommand=bad", output=tmp_path, environment={"CLOUDFLARE_API_TOKEN": "secret"})
