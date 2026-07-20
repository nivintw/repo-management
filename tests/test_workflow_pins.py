# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Guard: every external GitHub Actions ``uses:`` is pinned to a full commit SHA.

A mutable tag (``@v7``) lets the action's author re-point it at new code, so the hash behind an
unchanged-looking pin changes underfoot — the surprise/false-failure supply-chain hole. zizmor's
``unpinned-uses`` audit enforces the same rule (see ``.github/zizmor.yml``), but that runs as a
separate CI step (the online audit is token-gated and skippable) and depends on zizmor's own
default policy. This test locks the invariant in the fast unit gate, independent of any external
tool — the same "pin the invariant so a later edit can't silently disarm it" pattern as
``tests/test_renovate_global.py`` and ``tests/test_workflow_secrets.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_ACTIONS = _REPO_ROOT / ".github" / "actions"

# A full Git commit SHA: exactly 40 lowercase hex characters.
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _uses_refs(node: object) -> list[str]:
    """Every ``uses:`` string anywhere in a parsed workflow/action document."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_uses_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_uses_refs(item))
    return found


def _yaml_files() -> list[Path]:
    files = sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))
    files += sorted(_ACTIONS.glob("**/action.yml")) + sorted(_ACTIONS.glob("**/action.yaml"))
    return files


def _pinnable_uses() -> list[tuple[Path, str]]:
    """(file, uses-ref) for every ``uses:`` that must be SHA-pinned.

    Local composite-action references (``./…``) carry no remote ref to pin and are excluded.
    """
    pairs: list[tuple[Path, str]] = []
    for path in _yaml_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for ref in _uses_refs(doc):
            if ref.startswith("./"):
                continue
            pairs.append((path, ref))
    return pairs


def test_there_are_uses_to_check() -> None:
    """Guard against a silent no-op: the discovery must actually find external ``uses:``."""
    assert _pinnable_uses(), "no external 'uses:' discovered — has workflow discovery drifted?"


@pytest.mark.parametrize(
    ("path", "ref"),
    _pinnable_uses(),
    ids=lambda value: value.name if isinstance(value, Path) else value,
)
def test_uses_is_pinned_to_a_full_sha(path: Path, ref: str) -> None:
    """A ``uses:`` reference must be ``owner/repo@<40-hex-sha>`` (a tag/branch is mutable)."""
    _, _, git_ref = ref.partition("@")
    assert git_ref, f"{path.name}: '{ref}' has no '@<ref>' pin at all"
    assert _FULL_SHA.match(git_ref), (
        f"{path.name}: '{ref}' is not pinned to a full commit SHA "
        f"(got '{git_ref}'). Pin to a 40-char SHA; Renovate keeps the digest fresh."
    )
