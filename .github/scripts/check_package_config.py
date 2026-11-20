#!/usr/bin/env python3
"""Check package_config/*.yaml files against the schema in README.md.

    check_package_config.py [--online] [FILE ...]

With no FILE, every file in package_config/ is checked. --online also checks
that each checked file's repository exists and is public. Name and repo_url
uniqueness is always checked against every file in package_config/.

Problems that stop the metrics collector from using a file are errors (exit
status 1). Keys the schema doesn't list are only warnings, because the
collector reads some that the README doesn't document yet.

On GitHub Actions each problem is also printed as an annotation on its file.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

CONFIG_DIR = Path("package_config")
SCHEMA_VERSION = 1
REQUIRED = ("name", "repo_type", "repo_url")
REPO_TYPES = ("github", "gitlab")
URL_FIELDS = ("cdash", "documentation", "homepage")
STRING_FIELDS = ("description", "default_branch", "primary_language", "spack_package")
# Keys the collector reads (corsa-center/metrics); anything else is a warning.
KNOWN_KEYS = {
    "schema", "published", "password_sha256", "name", "description",
    "repo_type", "repo_url", "default_branch", "cdash", "documentation",
    "homepage", "primary_language", "spack_repo", "spack_package",
    "overrides", "collectors",
}
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


class Report:
    def __init__(self):
        self.errors = 0

    def _emit(self, level, path, message):
        print(f"{path}: {level}: {message}")
        if IN_ACTIONS:
            print(f"::{level} file={path}::{message}")

    def error(self, path, message):
        self.errors += 1
        self._emit("error", path, message)

    def warning(self, path, message):
        self._emit("warning", path, message)


def is_http_url(value):
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def repo_path(repo_url):
    """Host and owner/repo path of a repository URL, without .git or a trailing slash."""
    parsed = urllib.parse.urlparse(repo_url)
    path = re.sub(r"\.git$", "", parsed.path.strip("/"))
    return parsed.netloc.lower(), path


def normalized_repo_url(repo_url):
    host, path = repo_path(repo_url)
    return f"{host}/{path.lower()}"


def expected_file_name(repo_url):
    """<owner>_<repo>.yaml from the last two parts of the repository path."""
    _, path = repo_path(repo_url)
    parts = path.split("/")
    if len(parts) < 2:
        return None
    return f"{parts[-2]}_{parts[-1]}"


def load(path, report):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        report.error(path, f"could not read it as YAML: {e}")
        return None
    if not isinstance(data, dict):
        report.error(path, "must be a YAML mapping of keys to values")
        return None
    return data


def read_quietly(path):
    """A file's mapping, or {} if it can't be read: for comparing against."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def check_fields(path, data, report):
    if data.get("schema") != SCHEMA_VERSION:
        report.error(path, f"schema must be {SCHEMA_VERSION}, not {data.get('schema')!r}")

    for key in REQUIRED:
        if not isinstance(data.get(key), str) or not data[key].strip():
            report.error(path, f"{key} is required and must be a string")

    if isinstance(data.get("repo_type"), str) and data["repo_type"].strip().lower() not in REPO_TYPES:
        report.error(path, f"repo_type must be one of {', '.join(REPO_TYPES)}, not {data['repo_type']!r}")

    repo_url = data.get("repo_url")
    if isinstance(repo_url, str) and repo_url.strip():
        if not repo_url.startswith("https://"):
            report.error(path, "repo_url must start with https://")
        else:
            host, rpath = repo_path(repo_url)
            if host == "github.com" and len(rpath.split("/")) != 2:
                report.error(path, "a GitHub repo_url must be https://github.com/<owner>/<repo>")
            if data.get("repo_type") == "github" and host != "github.com":
                report.error(path, "repo_type is github but repo_url isn't on github.com")
            if data.get("repo_type") == "gitlab" and host == "github.com":
                report.error(path, "repo_type is gitlab but repo_url is on github.com")
            expected = expected_file_name(repo_url)
            if expected and path.stem != expected:
                report.warning(path, f"name the file {expected}{path.suffix}, after the repository's owner and name")

    published = data.get("published", True)
    if not isinstance(published, bool):
        report.error(path, f"published must be true or false, not {published!r}")
    elif not published:
        digest = data.get("password_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            report.error(path, "an unpublished package needs password_sha256: the 64-character lowercase hex SHA-256 of its password")

    for key in URL_FIELDS:
        if key in data and not is_http_url(data[key]):
            report.error(path, f"{key} must be a URL starting with https://")

    for key in STRING_FIELDS:
        if key in data and not isinstance(data[key], str):
            report.error(path, f"{key} must be a string")

    if "spack_repo" in data:
        repos = data["spack_repo"] if isinstance(data["spack_repo"], list) else [data["spack_repo"]]
        if not repos or not all(isinstance(r, str) and r.strip() for r in repos):
            report.error(path, "spack_repo must be a git URL or a list of them")

    if "overrides" in data:
        overrides = data["overrides"]
        if not isinstance(overrides, dict) or not all(
            isinstance(labels, dict) and all(isinstance(v, str) for v in labels.values())
            for labels in overrides.values()
        ):
            report.error(path, 'overrides must map metric paths to {sub-metric label: "N/A" or a string}')

    if "collectors" in data and not isinstance(data["collectors"], dict):
        report.error(path, "collectors must be a mapping")

    unknown = sorted(set(data) - KNOWN_KEYS)
    if unknown:
        report.warning(path, f"key(s) not in the schema, so a misspelling would be ignored: {', '.join(unknown)}")


def http_get_json(url, headers):
    request = urllib.request.Request(url, headers={"User-Agent": "metrics-packages-check", **headers})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def check_repository(path, data, report):
    """The repository must exist and be public, or there's nothing to collect."""
    repo_url, repo_type = data.get("repo_url"), data.get("repo_type")
    if not isinstance(repo_url, str) or repo_type not in REPO_TYPES:
        return
    host, rpath = repo_path(repo_url)
    if repo_type == "github":
        url = f"https://api.github.com/repos/{rpath}"
        headers = {"Accept": "application/vnd.github+json"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    else:
        url = f"https://{host}/api/v4/projects/{urllib.parse.quote(rpath, safe='')}"
        headers = {}
    try:
        info = http_get_json(url, headers)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            report.error(path, f"{repo_url} doesn't exist or isn't public")
        else:
            report.error(path, f"couldn't look up {repo_url}: HTTP {e.code}")
        return
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        report.error(path, f"couldn't look up {repo_url}: {e}")
        return
    if info.get("private") or info.get("visibility", "public") != "public":
        report.error(path, f"{repo_url} isn't public")
    if info.get("archived"):
        report.warning(path, f"{repo_url} is archived")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--online", action="store_true", help="also check that each repository exists and is public")
    args = parser.parse_args()

    report = Report()
    all_files = sorted(p for p in CONFIG_DIR.iterdir() if p.is_file())
    to_check = args.files or all_files
    checked = {}

    for path in to_check:
        if path.parent != CONFIG_DIR or path.suffix not in (".yaml", ".yml"):
            report.error(path, f"package files go in {CONFIG_DIR}/ and end in .yaml")
            continue
        data = load(path, report)
        if data is None:
            continue
        checked[path] = data
        check_fields(path, data, report)
        if args.online:
            check_repository(path, data, report)

    # Uniqueness against every file: the collector skips a second package with
    # the same name, and two files for one repository would collect it twice.
    everything = {p: read_quietly(p) for p in all_files}
    for path, data in checked.items():
        for other, other_data in everything.items():
            if other.resolve() == path.resolve():
                continue
            if isinstance(data.get("name"), str) and data["name"] == other_data.get("name"):
                report.error(path, f"name {data['name']!r} is already used by {other}")
            if (
                isinstance(data.get("repo_url"), str)
                and isinstance(other_data.get("repo_url"), str)
                and normalized_repo_url(data["repo_url"]) == normalized_repo_url(other_data["repo_url"])
            ):
                report.error(path, f"{other} already lists {data['repo_url']}")

    count = len(to_check)
    print(f"Checked {count} file{'s' if count != 1 else ''}: {report.errors} error{'s' if report.errors != 1 else ''}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
