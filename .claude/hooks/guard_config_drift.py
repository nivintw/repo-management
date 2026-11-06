"""PreToolUse guard: warn on twin drift, and block language-agnostic config in pyproject.toml.

Two edit-time guards:

1. Twin-drift WARNING (own dogfood repo only). copier-everything keeps certain files as both a
   templated source under `template/` and a rendered copy at the repo root — "twins" that must
   stay in sync (tests/test_synced_files.py detects drift in CI; scripts/resync_twins.py fixes
   it). This warns, at edit time, when you touch one side, naming its partner — the preventive
   counterpart. It only fires when a `template/` dir exists, so a generated project (no template)
   never sees it.

2. Ban language-agnostic config in pyproject.toml (BLOCK, everywhere). Python is optional here,
   so `pyproject.toml` only exists for Python projects; config that isn't Python-specific must
   live in its language-neutral home under `.config/` instead. Writing one of those tables into
   pyproject.toml is blocked, pointing at the right file.

The WATCHED twin set and the banned-table list are derived from copier-everything's OWN layout
(tests/test_guard_config_drift.py verifies WATCHED against test_synced_files' buckets), not
copied from any downstream.
"""

from __future__ import annotations

import re
from pathlib import Path

# _hooklib is the sibling module on sys.path (script dir when run, harness-inserted when imported).
from _hooklib import (
    dispatch,
    edited_path,
    project_root,
    read_event,
    resulting_content,
)

# Files kept in sync between the repo root and their `template/` source — copier-everything's own
# twin set (tests/test_synced_files.py::TRIVIALLY_EQUAL ∪ STRUCTURALLY_TESTED). A guard test
# asserts this stays equal to those buckets so the two can't silently drift apart.
WATCHED: frozenset[str] = frozenset(
    {
        ".config/rumdl.toml",
        ".config/yamllint.yaml",
        ".config/lychee.toml",
        ".github/workflows/approve-bot-prs.yml",
        ".github/workflows/dependabot-auto-merge.yml",
        ".github/workflows/label-hygiene.yml",
        ".github/workflows/pr.yml",
        ".github/workflows/link-check.yml",
        ".github/workflows/docs.yml",
        "LICENSE",
        "LICENSES/MIT.txt",
        "docs/assets/favicon.svg",
        "docs/stylesheets/extra.css",
        "overrides/404.html",
        "pyproject.toml",
        ".cz.toml",
        ".vscode/settings.json",
        ".vscode/extensions.json",
        ".editorconfig",
        "scripts/refresh-binary-checksums.sh",
        "mkdocs.yml",
        ".claude/settings.json",
        ".claude/hooks/_hooklib.py",
        ".claude/hooks/guard_version_bumps.py",
        ".claude/hooks/guard_managed_files.py",
        ".claude/hooks/guard_config_drift.py",
    }
)

# Language-agnostic tools the template deliberately configures OUTSIDE pyproject.toml (under
# .config/, because Python is optional). Each maps its pyproject table name → its real home.
BANNED_PYPROJECT_TABLES: dict[str, str] = {
    "typos": ".config/typos.toml",
    "rumdl": ".config/rumdl.toml",
    "lychee": ".config/lychee.toml",
    "yamllint": ".config/yamllint.yaml",
}


def _twin_partner(relative: Path, root: Path) -> str | None:
    """The other side of a twin for `relative` (from root), or None if it isn't a twin here.

    Fires only when a `template/` dir exists (the dogfood repo). Editing a root twin points at
    its `template/` source; editing under `template/` points back at the root copy.
    """
    if not (root / "template").is_dir():
        return None
    parts = relative.parts
    if parts and parts[0] == "template":
        # template/<...>/name.jinja → strip the leading `template/`, the `.jinja` suffix, and any
        # `{% if ... %}segment{% endif %}` conditional-dir wrappers, giving the root twin path.
        inner = Path(*parts[1:])
        stem = inner.with_suffix("") if inner.suffix == ".jinja" else inner
        root_rel = "/".join(re.sub(r"\{%.*?%\}", "", segment) or segment for segment in stem.parts)
        return root_rel if root_rel in WATCHED and (root / root_rel).exists() else None
    posix = relative.as_posix()
    return f"template/{posix}(.jinja) source" if posix in WATCHED else None


def _banned_table(content: str) -> tuple[str, str] | None:
    """(table, home) for the first banned `[tool.<x>]` table in `content`, else None."""
    for table, home in BANNED_PYPROJECT_TABLES.items():
        if re.search(rf"(?m)^\[tool\.{re.escape(table)}(?:\.[^\]]+)?\]", content):
            return table, home
    return None


def decide(event: dict) -> tuple[str, str]:
    """Pure decision: (action, message) where action is allow|deny|warn_allow."""
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

    # Behavior 2 (BLOCK): a banned language-agnostic table in pyproject.toml.
    if relative.name == "pyproject.toml" and relative.parent == Path():
        content = resulting_content(event, file)
        if content is not None and (hit := _banned_table(content)) is not None:
            table, home = hit
            return "deny", (
                f"Blocked: [tool.{table}] is language-agnostic config and must not live in "
                f"pyproject.toml (which only exists for Python projects here). Put it in {home} "
                f"instead, its language-neutral home."
            )

    # Behavior 1 (WARN): twin drift.
    partner = _twin_partner(relative, root)
    if partner is not None:
        return "warn_allow", (
            f"guard_config_drift: {relative} is a dogfood twin — keep its partner ({partner}) in "
            f"sync, or run `python scripts/resync_twins.py` after this edit. (Allowing the edit.)"
        )
    return "allow", ""


def main() -> None:
    dispatch(*decide(read_event()))


if __name__ == "__main__":
    main()
