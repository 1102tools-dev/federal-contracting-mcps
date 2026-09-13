#!/usr/bin/env python3
"""Fail closed when an existing PyPI version differs from the built wheel.

Compare installed payload and install metadata, not ZIP timestamps, RECORD,
builder versions, or README prose. No downloaded code is imported or executed.
"""

import argparse
import configparser
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import time
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import zipfile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version


class GuardError(RuntimeError):
    pass


def fetch(url, *, missing_ok=False):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "1102tools-release-guard/1"}), timeout=40) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            if error.code != 429 and error.code < 500:
                raise GuardError(f"PyPI check failed: HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError):
            pass
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise GuardError("Cannot verify PyPI after three attempts; refusing to release")


def normalized_requirement(value):
    requirement = Requirement(value)
    extras = sorted(canonicalize_name(extra) for extra in requirement.extras)
    return (
        canonicalize_name(requirement.name), tuple(extras), str(requirement.specifier),
        requirement.url or "", str(requirement.marker) if requirement.marker else "",
    )


def wheel_contract(data):
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        names = [name for name in wheel.namelist() if not name.endswith("/")]
        if len(names) != len(set(names)):
            raise GuardError("Wheel contains duplicate paths")
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise GuardError("Expected exactly one wheel METADATA file")
        metadata_path = metadata_paths[0]
        dist_info = metadata_path.rsplit("/", 1)[0] + "/"
        metadata = BytesParser().parsebytes(wheel.read(metadata_path))
        if not metadata["Name"] or not metadata["Version"]:
            raise GuardError("Wheel is missing its package identity")
        payload = {
            name: hashlib.sha256(wheel.read(name)).hexdigest()
            for name in names if not name.startswith(dist_info)
        }
        entries = configparser.ConfigParser(interpolation=None)
        entries.optionxform = str
        if dist_info + "entry_points.txt" in names:
            entries.read_string(wheel.read(dist_info + "entry_points.txt").decode())
        wheel_metadata = BytesParser().parsebytes(wheel.read(dist_info + "WHEEL"))
        return {
            "name": canonicalize_name(metadata["Name"]),
            "version": str(Version(metadata["Version"])),
            "payload": payload,
            "dependencies": sorted(normalized_requirement(value) for value in metadata.get_all("Requires-Dist", [])),
            "python": str(SpecifierSet(metadata.get("Requires-Python", ""))),
            "extras": sorted(canonicalize_name(value) for value in metadata.get_all("Provides-Extra", [])),
            "external": sorted(metadata.get_all("Requires-External", [])),
            "entry_points": {section: dict(entries.items(section)) for section in entries.sections()},
            "tags": sorted(wheel_metadata.get_all("Tag", [])),
            "purelib": wheel_metadata.get("Root-Is-Purelib"),
        }


def check_wheel(path, name, version, *, require_published=False, fetcher=fetch, publication_wait_seconds=0):
    local = wheel_contract(path.read_bytes())
    if (local["name"], Version(local["version"])) != (canonicalize_name(name), Version(version)):
        raise GuardError("Built wheel identity differs from pyproject.toml")
    base = "https://pypi.org/pypi/" + quote(canonicalize_name(name), safe="")
    response = fetcher(base + "/" + quote(version, safe="") + "/json", missing_ok=True)
    # Upload success can precede visibility on the public JSON endpoint. Wait
    # only for a missing release; never retry away a payload/digest mismatch.
    deadline = time.monotonic() + publication_wait_seconds
    while response is None and require_published and time.monotonic() < deadline:
        time.sleep(min(5, max(0, deadline - time.monotonic())))
        response = fetcher(base + "/" + quote(version, safe="") + "/json", missing_ok=True)
    if response is None:
        if require_published:
            raise GuardError(f"{name} {version} is not published")
        project = fetcher(base + "/json", missing_ok=True)
        if project is not None and Version(version) <= Version(json.loads(project)["info"]["version"]):
            raise GuardError(f"{name}: choose a new version above the latest PyPI release")
        return "new version"
    release = json.loads(response)
    artifacts = [file for file in release["urls"] if file["filename"] == path.name and file["packagetype"] == "bdist_wheel"]
    if len(artifacts) != 1 or artifacts[0].get("yanked"):
        raise GuardError(f"{name} {version}: no matching non-yanked published wheel; increase its version")
    artifact = artifacts[0]
    url = urlparse(artifact["url"])
    if url.scheme != "https" or url.hostname != "files.pythonhosted.org":
        raise GuardError("Unexpected PyPI artifact host")
    published = fetcher(artifact["url"])
    if hashlib.sha256(published).hexdigest() != artifact["digests"]["sha256"]:
        raise GuardError("Published wheel SHA-256 does not match PyPI")
    remote = wheel_contract(published)
    differences = [key for key in local if local[key] != remote[key]]
    if differences:
        raise GuardError(
            f"{name} {version}: package changed ({', '.join(differences)}); increase its version"
        )
    return "published version matches"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--require-published", action="store_true")
    parser.add_argument("--publication-wait-seconds", type=int, default=90)
    args = parser.parse_args()
    project = tomllib.loads((args.project / "pyproject.toml").read_text())["project"]
    wheels = list((args.dist or args.project / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise GuardError("Expected exactly one built wheel")
    if not 0 <= args.publication_wait_seconds <= 300:
        raise GuardError("Publication visibility wait must be between 0 and 300 seconds")
    result = check_wheel(wheels[0], project["name"], project["version"], require_published=args.require_published,
                         publication_wait_seconds=args.publication_wait_seconds if args.require_published else 0)
    print(f"{project['name']} {project['version']}: {result}")


if __name__ == "__main__":
    try:
        main()
    except (GuardError, ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error
