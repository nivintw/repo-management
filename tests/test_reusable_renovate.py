# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Lock the supply-chain-relevant settings of the per-repo Renovate workflow.

Every managed repo runs Renovate by calling ``reusable-renovate.yml`` at a tag, so these settings
apply fleet-wide and can't be exercised by this repo's own CI. The tests pin them so a later edit
can't silently widen what a repo's postUpgradeTasks may run, disarm the checksum tamper gate, or
widen the token beyond the calling repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "reusable-renovate.yml"


def _steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["renovate"]["steps"]


def _step(name_fragment: str) -> dict:
    return next(s for s in _steps() if name_fragment in s.get("name", ""))


def test_allowed_commands_are_exactly_the_two_fleet_scripts() -> None:
    """PostUpgradeTasks may run only the checksum refresh and the uv relock script, anchored."""
    allowed = json.loads(_step("Run Renovate")["env"]["RENOVATE_ALLOWED_COMMANDS"])
    assert allowed == [
        "^scripts/refresh-binary-checksums\\.sh$",
        "^scripts/renovate-uv-relock\\.sh$",
    ]


def test_base_ref_arms_the_tamper_gate_and_is_admin_only() -> None:
    """BASE_REF comes from customEnvVariables (admin-only), never from an overridable channel."""
    env = _step("Run Renovate")["env"]
    assert json.loads(env["RENOVATE_CUSTOM_ENV_VARIABLES"]) == {"BASE_REF": "origin/HEAD"}
    assert "RENOVATE_ALLOWED_ENV" not in env


def test_token_is_scoped_to_the_calling_repo_only() -> None:
    """The minted token covers exactly the repo Renovate runs in, never the fleet."""
    mint = _step("Mint a Renovate App token")["with"]
    assert mint["repositories"] == "${{ steps.repo.outputs.name }}"
    assert _step("Run Renovate")["env"]["RENOVATE_REPOSITORIES"] == "${{ github.repository }}"


def test_renovate_version_is_pinned_exactly() -> None:
    """A floating Renovate version would change fleet-wide behavior without a release."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    version = workflow["jobs"]["renovate"]["env"]["RENOVATE_VERSION"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
