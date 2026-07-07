"""PreToolUse guard: block hand-edits to tool-owned files.

`uv.lock` (uv), `CHANGELOG.md` (release-please), `.copier-answers.yml` (copier), and everything
under `LICENSES/` (REUSE/the license tooling) are owned by a tool that regenerates them. A
hand-edit silently drifts the file from its owner. This blocks Edit/Write to those paths.
Matching is root-anchored on the edited file's nearest `.git` (copier-path aware, not cwd),
case-insensitive, and only fires for the file at the PROJECT ROOT — a `docs/CHANGELOG.md` a user
authored is not the release-please one.
"""

from __future__ import annotations

from pathlib import Path

# _hooklib is the sibling module on sys.path (script dir when run, harness-inserted when imported).
from _hooklib import dispatch, edited_path, project_root, read_event

# Tool-owned files at the project root (compared case-insensitively).
MANAGED_ROOT_FILES = frozenset({"uv.lock", "changelog.md", ".copier-answers.yml"})
# Tool-owned directories at the project root (the whole subtree is owned).
MANAGED_ROOT_DIRS = frozenset({"licenses"})

_OWNER = {
    "uv.lock": "uv (run `uv lock` / `uv sync`)",
    "changelog.md": "release-please (it rewrites this on each release)",
    ".copier-answers.yml": "copier (it rewrites this on `copier copy`/`update`)",
    "licenses": "the license tooling (REUSE / your license list)",
}


def _managed_key(relative: Path) -> str | None:
    """The owner key if `relative` (from the project root) is tool-owned, else None."""
    parts = [part.lower() for part in relative.parts]
    if len(parts) == 1 and parts[0] in MANAGED_ROOT_FILES:
        return parts[0]
    if parts and parts[0] in MANAGED_ROOT_DIRS:
        return parts[0]
    return None


def decide(event: dict) -> tuple[str, str]:
    """Pure decision: (action, message) where action is allow|deny."""
    path = edited_path(event)
    if not path:
        return "allow", ""
    file = Path(path).resolve()
    root = project_root(file.parent)
    if root is None:
        return "allow", ""
    try:
        relative = file.relative_to(root)
    except ValueError:
        return "allow", ""
    key = _managed_key(relative)
    if key is None:
        return "allow", ""
    return "deny", (
        f"Blocked: {relative} is owned by {_OWNER[key]}, not hand-edited. "
        f"Change it through its tool so it doesn't drift, or delete this guard if you really must."
    )


def main() -> None:
    dispatch(*decide(read_event()))


if __name__ == "__main__":
    main()
