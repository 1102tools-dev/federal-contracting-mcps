#!/usr/bin/env python3
"""Refresh a bundled-data MCP when its government source publishes new files.

    python3 scripts/refresh_data.py bls-oews
    python3 scripts/refresh_data.py gsa-perdiem

Runs the package's source check (and, for per diem, reads GSA's files page
for new fiscal years). When the upstream files changed, rebuilds the bundled
data with the package's own builder, which fails on schema drift and
internal inconsistencies, then bumps the patch version on every version
surface and adds a changelog entry. Writes nothing when the sources match.

Exit codes: 0 with nothing to do, 10 when a refresh is staged in the working
tree, 1 on any failure (with a Markdown report on stdout). Tests, live
parity, and publishing are the data-refresh workflow's job.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGED = 10


class RefreshError(RuntimeError):
    pass


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _uv(*args: str) -> list[str]:
    return ["uv", "run", "--frozen", "--group", "dev", *args]


class Service:
    slug: str
    package: str
    module: str

    def __init__(self) -> None:
        self.dir = ROOT / "servers" / self.package
        self.data = self.dir / "src" / self.module / "data"
        # Everything detect() and build() may write.
        self.generated = [self.data]

    def detect(self) -> list[str]:
        """Return the upstream differences (empty when nothing changed)."""
        raise NotImplementedError

    def build(self, cache: Path) -> None:
        raise NotImplementedError

    def fingerprint(self) -> object:
        """What identifies the upstream files a build used."""
        raise NotImplementedError

    def summary(self) -> str:
        raise NotImplementedError

    def update_docs(self) -> None:
        pass

    def _check_sources(self) -> list[str]:
        r = run(_uv("python", "scripts/check_sources.py"), self.dir)
        if r.returncode == 0:
            return []
        lines = [line for line in r.stdout.splitlines() if line.startswith("- ")]
        if not lines:
            raise RefreshError(f"check_sources.py failed without a report:\n{r.stdout}{r.stderr}")
        return lines

    def _build(self, script: str, cache: Path) -> None:
        r = run(_uv("python", f"scripts/{script}", "--cache", str(cache)), self.dir)
        if r.returncode:
            raise RefreshError(f"{script} refused the new files:\n\n```\n{(r.stderr or r.stdout)[-3000:]}\n```")


class BLS(Service):
    slug, package, module = "bls-oews", "bls-oews-mcp", "bls_oews_mcp"

    def manifest(self) -> dict:
        return json.loads((self.data / "manifest.json").read_text())

    def detect(self) -> list[str]:
        return self._check_sources()

    def build(self, cache: Path) -> None:
        self._build("build_oews_db.py", cache)

    def fingerprint(self) -> object:
        return {name: src["sha256"] for name, src in self.manifest()["sources"].items()}

    def summary(self) -> str:
        m = self.manifest()
        return (f"Bundles the BLS OEWS {m['release']['description']} release "
                f"(published {m['sources']['oe.release']['last_modified']}), "
                f"{m['counts']['cells']:,} estimate cells.")

    def update_docs(self) -> None:
        m = self.manifest()
        name, year = m["release"]["description"], m["data_year"]
        published = m["sources"]["oe.release"]["last_modified"]
        y, mo, d = (int(x) for x in published.split("-"))
        months = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"]
        long_date = f"{months[mo - 1]} {d}, {y}"
        readme = self.dir / "readme.md"
        text = readme.read_text()
        text = re.sub(r"May \d{4} estimates, published (by BLS on )?[A-Z][a-z]+ \d{1,2}, \d{4}",
                      lambda mt: f"{name} estimates, published {mt.group(1) or ''}{long_date}", text)
        text = re.sub(r"answers from the bundled release, \d{4} \(", f"answers from the bundled release, {year} (", text)
        readme.write_text(text)


class PerDiem(Service):
    slug, package, module = "gsa-perdiem", "gsa-perdiem-mcp", "gsa_perdiem_mcp"

    def __init__(self) -> None:
        super().__init__()
        self.generated.append(self.dir / "scripts" / "sources.json")

    def manifest(self) -> dict:
        return json.loads((self.data / "manifest.json").read_text())

    def detect(self) -> list[str]:
        r = run(["python3", "scripts/discover_sources.py", "--write"], self.dir)
        if r.returncode == 2:
            raise RefreshError(f"Could not read GSA's per diem files page:\n{r.stderr}")
        page = r.stdout.splitlines() if r.returncode == 1 else []
        # A new fiscal year on the page is handled by sources.json above; the
        # hash check below covers files GSA replaced under the same name.
        hashes = [line for line in self._check_sources() if "newer than bundled" not in line]
        return page + hashes

    def build(self, cache: Path) -> None:
        self._build("build_snapshot.py", cache)

    def fingerprint(self) -> object:
        m = self.manifest()
        return {
            "census": {k: v["sha256"] for k, v in m["census"].items()},
            "years": {fy: {k: meta[k]["sha256"] for k in ("rates", "zip", "mie")}
                      | {"zip_published": meta["zip"]["published"]}
                      for fy, meta in m["fiscal_years"].items()},
        }

    def summary(self) -> str:
        years = sorted(int(fy) for fy in self.manifest()["fiscal_years"])
        return f"Bundles GSA per diem rate, ZIP, and M&IE files for FY{years[0]}-FY{years[-1]}."


SERVICES = {s.slug: s for s in (BLS, PerDiem)}


def bump_version(svc: Service) -> str:
    pyproject = svc.dir / "pyproject.toml"
    text = pyproject.read_text()
    m = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.M)
    if not m:
        raise RefreshError(f"{pyproject}: no plain X.Y.Z version")
    old = ".".join(m.groups())
    new = f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}"
    pyproject.write_text(text[:m.start()] + f'version = "{new}"' + text[m.end():])

    manifest_path = svc.dir / "server.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = new
    for package in manifest.get("packages", []):
        package["version"] = new
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    distribution = svc.package
    for name in ("Dockerfile", "smithery.yaml"):
        path = svc.dir / name
        if path.is_file():
            path.write_text(path.read_text().replace(f"{distribution}=={old}", f"{distribution}=={new}"))

    r = run(["uv", "lock"], svc.dir)
    if r.returncode:
        raise RefreshError(f"uv lock failed:\n{r.stderr}")
    return new


def add_changelog(svc: Service, version: str, changes: list[str]) -> None:
    path = svc.dir / "changelog.md"
    text = path.read_text()
    head, sep, rest = text.partition("\n## ")
    if not sep:
        raise RefreshError(f"{path}: no '## <version>' heading to insert above")
    entry = (f"\n## {version}\n\nAutomated data refresh. {svc.summary()} No code changes.\n\n"
             + "\n".join(changes) + "\n")
    path.write_text(head.rstrip("\n") + "\n" + entry + "\n## " + rest)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug", choices=sorted(SERVICES))
    p.add_argument("--cache", type=Path, help="download cache (default: a temporary directory)")
    args = p.parse_args()
    svc = SERVICES[args.slug]()
    out = os.environ.get("GITHUB_OUTPUT")

    def emit(**values: str) -> None:
        if out:
            with open(out, "a") as f:
                f.writelines(f"{k}={v}\n" for k, v in values.items())

    try:
        changes = svc.detect()
        if not changes:
            print(f"{svc.slug}: upstream files match the bundled data; nothing to do.")
            return 0
        before = svc.fingerprint()
        with tempfile.TemporaryDirectory() as tmp:
            svc.build(args.cache or Path(tmp))
        if svc.fingerprint() == before:
            # The check flagged something (a failed download, say) but the
            # files the build used are the ones already bundled.
            paths = [str(p) for p in svc.generated]
            run(["git", "checkout", "--", *paths], svc.dir)
            run(["git", "clean", "-fdq", "--", *paths], svc.dir)
            print(f"{svc.slug}: rebuild used the already-bundled files; nothing to publish.\n")
            print("\n".join(changes))
            return 0
        svc.update_docs()
        version = bump_version(svc)
        add_changelog(svc, version, changes)
    except RefreshError as e:
        print(f"## {svc.slug} data refresh stopped before publishing\n\n{e}")
        return 1
    print(f"{svc.slug} {version}: {svc.summary()}\n")
    print("\n".join(changes))
    emit(version=version, tag=f"{svc.slug}/v{version}", package=svc.package, summary=svc.summary())
    return STAGED


if __name__ == "__main__":
    sys.exit(main())
