"""Compute the release matrices for publish-pypi.yml.

Scope comes from, in order: an explicit `services` dispatch input other than
"all" (comma-separated hosted slugs from deploy/services.json); a scoped tag
`refs/tags/<slug>/v<version>` (e.g. gsa-perdiem/v1.1.0); otherwise every
package and hosted service (plain `v*` tags). A scoped release builds, deploys,
and publishes only those services and their packages.
"""
import argparse, json, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# PyPI distribution names that differ from their servers/ directory.
PYPI_NAMES = {"regulations-gov-mcp": "regulationsgov-mcp"}


_SCOPED_TAG = re.compile(r"^refs/tags/([a-z0-9-]+)/v\d")


def plan(services: str, ref: str = "") -> dict:
    hosted_all = json.loads((ROOT / "deploy/services.json").read_text())
    dirs_all = sorted(p.name for p in (ROOT / "servers").iterdir() if (p / "pyproject.toml").exists())
    requested = [s.strip() for s in (services or "all").split(",") if s.strip()]
    tag = _SCOPED_TAG.match(ref or "")
    if requested in ([], ["all"]) and tag:
        requested = [tag.group(1)]
    elif tag and requested != [tag.group(1)]:
        raise SystemExit(f"Tag {ref} is scoped to {tag.group(1)}; services input {services!r} conflicts")
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
    out = plan(args.services, args.ref)
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in out.items())
    if target:
        with open(target, "a") as f:
            f.write(lines)
    print(lines, end="")


if __name__ == "__main__":
    main()
