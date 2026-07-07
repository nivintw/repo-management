"""PreToolUse guard: block a hand-edit that moves the release-please version off canonical.

release-please owns the version bump. A stray hand-edit that changes it is only caught
indirectly today — via a later release-please conflict. This guard blocks an Edit/Write that
sets the version-of-record (the `.config/.release-please-manifest.json` value, or any file
release-please mirrors it into via `extra-files`) to a value OTHER than the canonical one.
Rewriting the identical value is allowed. If canonical can't be resolved, it fails open loudly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# _hooklib is the sibling module in this same dir; it resolves both when Claude Code runs this
# as a script (the script's dir is on sys.path) and when the test harness imports it after
# putting this dir on sys.path.
from _hooklib import (
    dispatch,
    edited_path,
    project_root,
    read_event,
    resulting_content,
)

MANIFEST_REL = Path(".config") / ".release-please-manifest.json"
CONFIG_REL = Path(".config") / "release-please-config.json"


def _manifest_version(data: dict) -> str | None:
    """The single-package version from a release-please manifest ('.' key, or the sole entry)."""
    if "." in data:
        return data["."]
    return next(iter(data.values())) if len(data) == 1 else None


def canonical_version(root: Path) -> tuple[str | None, str | None]:
    """(version, error): the manifest's canonical version, or (None, reason) if unresolvable."""
    manifest = root / MANIFEST_REL
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not read {MANIFEST_REL}: {exc}"
    version = _manifest_version(data)
    if not version:
        return None, f"no single-package version in {MANIFEST_REL}"
    return version, None


def version_carriers(root: Path) -> set[Path]:
    """Every file that carries the version: the manifest + release-please's `extra-files`.

    Derived from THIS repo's own release-please-config.json (not a hardcoded list), so it tracks
    whatever a given project actually syncs — pyproject.toml / uv.lock for Python, galaxy.yml for
    an Ansible collection, nothing extra for a config-only repo.
    """
    carriers = {(root / MANIFEST_REL).resolve()}
    try:
        config = json.loads((root / CONFIG_REL).read_text())
    except (OSError, json.JSONDecodeError):
        return carriers
    for package in (config.get("packages") or {}).values():
        for extra in package.get("extra-files") or []:
            path = extra.get("path") if isinstance(extra, dict) else extra
            if path:
                carriers.add((root / path).resolve())
    return carriers


def version_in(content: str, file: Path) -> str | None:
    """The version this file's post-edit `content` declares, by the file's own convention."""
    name = file.name.lower()
    if name == MANIFEST_REL.name:
        try:
            return _manifest_version(json.loads(content))
        except (json.JSONDecodeError, AttributeError):
            return None
    if name == "pyproject.toml":
        # `$.project.version` — the first line-anchored `version = "..."` (the [project] one;
        # dependency pins are inline tables, never a bare top-of-line assignment).
        match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', content)
        return match.group(1) if match else None
    if name == "galaxy.yml":
        match = re.search(r'(?m)^version:\s*["\']?([^"\'\s]+)', content)
        return match.group(1) if match else None
    return None


def _decide_manifest_edit(root: Path, content: str) -> tuple[str, str]:
    """Guard an edit to the manifest by comparing the WHOLE dict — single AND multi-package.

    The manifest is the version-of-record; a per-package canonical can't be expressed as one
    value, so compare every package's version rather than a single one. Deny when any managed
    version changes (a hand bump); allow an identical rewrite.
    """
    try:
        current = json.loads((root / MANIFEST_REL).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return (
            "warn_allow",
            f"guard_version_bumps: can't read the current manifest ({exc}); allowing the edit (fail-open).",
        )
    try:
        new = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return "allow", ""  # the edit doesn't leave valid JSON — not a version change to adjudicate
    if not isinstance(new, dict):
        return "allow", ""
    changed = sorted(pkg for pkg in set(current) | set(new) if current.get(pkg) != new.get(pkg))
    if not changed:
        return "allow", ""
    return "deny", (
        f"Blocked: this edit changes the release-please-managed version of {', '.join(changed)} "
        f"in {MANIFEST_REL.name}. release-please owns version bumps — don't hand-edit the manifest "
        f"(rewriting the same values is fine). To release, let release-please's Release PR bump it."
    )


def decide(event: dict) -> tuple[str, str]:
    """Pure decision: returns (action, message) where action is allow|deny|warn_allow."""
    path = edited_path(event)
    if not path:
        return "allow", ""
    file = Path(path).resolve()
    root = project_root(file.parent)
    if root is None or file not in version_carriers(root):
        return "allow", ""
    content = resulting_content(event, file)
    if content is None:
        return "allow", ""
    # The manifest carries every package's version-of-record, so compare it whole — this is what
    # makes the guard cover a multi-package (monorepo) manifest, not just a single `.` package.
    if file == (root / MANIFEST_REL).resolve():
        return _decide_manifest_edit(root, content)
    # A non-manifest carrier (pyproject/galaxy) mirrors the single-package canonical version.
    canonical, error = canonical_version(root)
    if canonical is None:
        return (
            "warn_allow",
            f"guard_version_bumps: can't resolve the canonical version ({error}); allowing the edit (fail-open).",
        )
    new_version = version_in(content, file)
    if new_version is None or new_version == canonical:
        return "allow", ""
    return "deny", (
        f"Blocked: this edit sets the version in {file.name} to {new_version}, but release-please's "
        f"canonical version is {canonical}. release-please owns version bumps — don't hand-edit "
        f"the version (rewriting the same value is fine). To release, let release-please's PR bump it."
    )


def main() -> None:
    dispatch(*decide(read_event()))


if __name__ == "__main__":
    main()
