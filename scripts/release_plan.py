"""Compute the release matrices for publish-pypi.yml.

Scope comes from, in order: an explicit `services` dispatch input other than
"all" (comma-separated hosted slugs from deploy/services.json); a scoped tag
`refs/tags/<slug>/v<version>` (e.g. gsa-perdiem/v1.1.0); otherwise every
package and hosted service (an all-service tag `refs/tags/vX.Y.Z`). A scoped
release builds, deploys, and publishes only those services and their packages.

An all-service tag's version is the repository release number (v1.0.33 follows
v1.0.32); it does not name any one package version. Every other ref, including
a branch dispatch or a malformed tag such as v9nonsense, is rejected here so no
build or deploy starts.
"""
import argparse, json, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# PyPI distribution names that differ from their servers/ directory.
PYPI_NAMES = {"regulations-gov-mcp": "regulationsgov-mcp"}


_SCOPED_TAG = re.compile(r"^refs/tags/([a-z0-9-]+)/v(\d[^/]*)$")
_ALL_SERVICE_TAG = re.compile(r"^refs/tags/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _package_version(package_dir: str) -> str:
    import tomllib

    return tomllib.loads((ROOT / "servers" / package_dir / "pyproject.toml").read_text())["project"]["version"]


def plan(services: str, ref: str = "") -> dict:
    hosted_all = json.loads((ROOT / "deploy/services.json").read_text())
    dirs_all = sorted(p.name for p in (ROOT / "servers").iterdir() if (p / "pyproject.toml").exists())
    requested = [s.strip() for s in (services or "all").split(",") if s.strip()]
    tag = _SCOPED_TAG.match(ref or "")
    if ref and not tag and not _ALL_SERVICE_TAG.match(ref):
        raise SystemExit(
            f"{ref} is not a release tag. Use vX.Y.Z to release everything or <slug>/v<version> "
            "for one service, and dispatch this workflow only on such a tag."
        )
    if requested in ([], ["all"]) and tag:
        requested = [tag.group(1)]
    elif tag and requested != [tag.group(1)]:
        raise SystemExit(f"Tag {ref} is scoped to {tag.group(1)}; services input {services!r} conflicts")
    if tag and tag.group(1) in hosted_all:
        want = _package_version(hosted_all[tag.group(1)]["package"])
        if tag.group(2) != want:
            raise SystemExit(
                f"Tag {ref} names version {tag.group(2)}, but {hosted_all[tag.group(1)]['package']} "
                f"is {want} in pyproject.toml. Tag the commit that carries the release version."
            )
    if requested in ([], ["all"]):
        hosted, dirs, scope = list(hosted_all), dirs_all, "all"
    else:
        unknown = [s for s in requested if s not in hosted_all]
        if unknown:
            raise SystemExit(f"Unknown hosted service(s): {', '.join(unknown)}. Known: {', '.join(hosted_all)}")
        hosted = requested
        dirs = sorted({hosted_all[s]["package"] for s in requested})
        scope = ", ".join(requested)
    packages = [{"dir": d, "pkg": PYPI_NAMES.get(d, d)} for d in dirs]
    summary = ("PyPI packages, the MCP registry, and all hosted services" if scope == "all"
               else f"The {scope} package, MCP registry entry, and hosted service")
    return {
        "hosted": json.dumps(hosted),
        "packages": json.dumps(packages),
        "manifests": " ".join(f"servers/{d}/server.json" for d in dirs),
        "scope": scope,
        "release_body": f"{summary} completed this release from the same commit. "
                        "See the workflow summary for deployment verification.",
    }


def main():
    p = argparse.ArgumentParser(); p.add_argument("--services", default="all")
    p.add_argument("--ref", default=os.environ.get("GITHUB_REF", "")); args = p.parse_args()
    if os.environ.get("GITHUB_ACTIONS") and not args.ref:
        raise SystemExit("GITHUB_REF is empty; run this workflow on a release tag")
    out = plan(args.services, args.ref)
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in out.items())
    if target:
        with open(target, "a") as f:
            f.write(lines)
    print(lines, end="")


if __name__ == "__main__":
    main()
