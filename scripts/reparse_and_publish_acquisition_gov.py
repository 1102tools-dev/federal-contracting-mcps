"""Re-parse the isolated Dell raw cache, then publish parsed data from the Mac.

Run from the repository with:
uv run --frozen --project servers/acquisition-gov-mcp python scripts/reparse_and_publish_acquisition_gov.py
See docs/acquisition-gov-raw-cache.md. No download mode is provided.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/var/lib/acquisition-gov-raw"


def without_cloudflare(environment):
    return {key: value for key, value in environment.items() if not key.upper().startswith("CLOUDFLARE")}


def remote_program(run_id):
    """Only fixed paths and a locally generated ID enter the remote program."""
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("Invalid run ID")
    return f'''import fcntl, json, os, pathlib, sqlite3, subprocess
root = pathlib.Path({REMOTE_ROOT!r})
output = root / "output" / {('fast-' + run_id)!r}
output.mkdir(parents=True, exist_ok=False)
environment = {{k: v for k, v in os.environ.items() if not k.upper().startswith("CLOUDFLARE")}}
with (root / "_cache.lock").open("a+") as cache_lock:
    # Sync takes this lock exclusively only while mutating cached resources.
    # Hold a shared view through extraction and the consistent SQLite backup.
    fcntl.flock(cache_lock.fileno(), fcntl.LOCK_SH)
    result = subprocess.run([
        "nice", "-n", "10", "/usr/local/bin/uv", "run", "--frozen", "--python", "3.12",
        "--project", "servers/acquisition-gov-mcp", "python", "scripts/load_acquisition_gov.py",
        "--raw-cache", str(root), "--local", str(output / "working.sqlite"), "--reparse"
    ], cwd=root / "work", env=environment, check=True, stdout=subprocess.PIPE, text=True)
    stats = json.loads(result.stdout)
    if stats.get("mode") != "reparse" or stats.get("requests") != 0 or stats.get("downloads") != 0:
        raise RuntimeError("Expected an offline re-parse with zero requests and downloads")
    with sqlite3.connect((output / "working.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(output / "snapshot.sqlite") as target:
            source.backup(target)
    (output / "stats.json").write_text(json.dumps(stats, indent=2) + "\\n")
print(json.dumps({{"snapshot": str(output / "snapshot.sqlite"), "stats": str(output / "stats.json"), "reparse": stats}}))
'''


def run(host="govnode", output=None, runner=subprocess.run, environment=None):
    environment = dict(os.environ if environment is None else environment)
    if not (environment.get("CLOUDFLARE_D1_TOKEN") or environment.get("CLOUDFLARE_API_TOKEN")):
        raise RuntimeError("Set CLOUDFLARE_D1_TOKEN or CLOUDFLARE_API_TOKEN on the Mac before running.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", host):
        raise ValueError("Use an SSH host alias or hostname, without options or shell syntax.")
    run_id = uuid.uuid4().hex
    remote_dir = f"{REMOTE_ROOT}/output/fast-{run_id}"
    local_dir = Path(output) if output is not None else Path(tempfile.mkdtemp(prefix="acquisition-gov-fast-"))
    local_dir.mkdir(parents=True, exist_ok=True)
    transfer_env = without_cloudflare(environment)
    completed = runner(["ssh", "-o", "SendEnv=-*", host, "python3 -"], input=remote_program(run_id),
                       text=True, stdout=subprocess.PIPE, check=True, env=transfer_env)
    receipt = json.loads(completed.stdout)
    # Never let remote output select a raw file or an arbitrary transfer path.
    if receipt.get("snapshot") != f"{remote_dir}/snapshot.sqlite" or receipt.get("stats") != f"{remote_dir}/stats.json":
        raise RuntimeError("Unexpected remote snapshot paths; not transferring or publishing.")
    stats = receipt.get("reparse", {})
    if stats.get("mode") != "reparse" or stats.get("requests") != 0 or stats.get("downloads") != 0:
        raise RuntimeError("Remote run was not offline; not publishing.")
    runner(["scp", "-o", "SendEnv=-*", f"{host}:{remote_dir}/snapshot.sqlite", str(local_dir / "snapshot.sqlite")],
           check=True, env=transfer_env)
    runner(["scp", "-o", "SendEnv=-*", f"{host}:{remote_dir}/stats.json", str(local_dir / "stats.json")],
           check=True, env=transfer_env)
    published = runner([sys.executable, str(ROOT / "scripts/push_acquisition_gov_snapshot.py"),
                        "--local", str(local_dir / "snapshot.sqlite")], cwd=ROOT, env=environment,
                       check=True, text=True, stdout=subprocess.PIPE)
    publish_stats = json.loads(published.stdout)
    (local_dir / "publish-stats.json").write_text(json.dumps(publish_stats, indent=2) + "\n")
    return {"reparse": stats, "publish": publish_stats, "local_output": str(local_dir), "remote_output": remote_dir}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="govnode", help="SSH alias for the Dell (default: govnode)")
    parser.add_argument("--output", type=Path, help="retain parsed snapshot and timing evidence here (default: new temporary directory)")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.host, args.output), indent=2))


if __name__ == "__main__":
    main()
