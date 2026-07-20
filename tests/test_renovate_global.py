# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Lock the central Renovate runner's supply-chain-relevant global config.

The binary-checksum ``postUpgradeTask`` runs only on scheduled *fleet* Renovate runs, never in
this repo's own PR CI, so these invariants can't be exercised here — this test pins them so a
later edit can't silently disarm the gate. The gate itself lives in
``scripts/refresh-binary-checksums.sh`` (active only when ``BASE_REF`` is set); the central
runner arms it fleet-wide via ``.github/renovate-global.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CONFIG = _REPO_ROOT / ".github" / "renovate-global.json"
REFRESH_SCRIPT = _REPO_ROOT / "scripts" / "refresh-binary-checksums.sh"


def _config() -> dict:
    return json.loads(GLOBAL_CONFIG.read_text(encoding="utf-8"))


def test_base_ref_arms_the_tamper_gate() -> None:
    """BASE_REF=origin/HEAD reaches the postUpgradeTask so the checksum gate stays armed.

    origin/HEAD is base-branch-agnostic: it resolves to each managed repo's default branch in
    Renovate's working clone, so ``git show "$BASE_REF:<file>"`` reads the pre-upgrade version
    whether the repo's default branch is main, master, or anything else.
    """
    assert _config()["customEnvVariables"]["BASE_REF"] == "origin/HEAD"


def test_base_ref_is_not_overridable_by_a_managed_repo() -> None:
    """BASE_REF's value must come ONLY from customEnvVariables, never an overridable channel.

    Renovate applies a repo's own ``env`` (gated by allowedEnv) AFTER customEnvVariables, so an
    allowlisted BASE_REF would let a target repo override the admin-set gate value. The gate is
    non-overridable iff BASE_REF is set via customEnvVariables (admin-only) AND kept out of
    allowedEnv — assert both halves, not just the absence.
    """
    config = _config()
    assert "BASE_REF" in config["customEnvVariables"]
    assert "BASE_REF" not in config.get("allowedEnv", [])


def test_refresh_script_is_allowlisted_and_exists() -> None:
    """The postUpgradeTask command must be allowlisted AND present, or Renovate silently no-ops.

    A dangling allowlist entry (script renamed/deleted) would leave the gate "configured" but
    never executed, so confirm the referenced script actually exists too.
    """
    patterns = _config()["allowedCommands"]
    assert any("refresh-binary-checksums" in pattern for pattern in patterns)
    assert REFRESH_SCRIPT.is_file(), f"allowlisted postUpgradeTask script missing: {REFRESH_SCRIPT}"


def test_renovate_vulnerability_alerts_disabled_dedups_the_security_seam() -> None:
    """Renovate must NOT open vulnerability PRs — that path is Dependabot's alone (#144).

    Named "renovate_" explicitly: this asserts *Renovate's* ``vulnerabilityAlerts`` is OFF, the
    opposite of the Dependabot ``vulnerability_alerts`` the same change turns ON fleet-wide — the
    two are easy to conflate in a failure message otherwise.

    The fleet runs a Dependabot security *floor* (enabled via repo-management's security config)
    and a Renovate freshness *ceiling*. If Renovate's ``vulnerabilityAlerts`` stayed on, a single
    advisory would yield two competing security PRs. Pin it off so the seam can't silently
    re-open on a later edit and reintroduce duplicate remediation PRs fleet-wide.
    """
    assert _config()["vulnerabilityAlerts"]["enabled"] is False


def test_major_updates_automerge() -> None:
    """Major updates automerge fleet-wide — a deliberate, risk-accepted policy, locked here.

    Auto-merging majors is intentionally aggressive: it trades the human pre-merge gate for the
    CI gate every other update type already rides. Because it looks risky, a later well-meaning
    edit could quietly delete or flip it back to human-reviewed. Pin it so that reversal can't
    happen silently — the merge stays genuinely CI-gated via platformAutomerge=false (asserted
    below), which is what makes automerging majors safe rather than reckless.
    """
    config = _config()
    assert config["platformAutomerge"] is False, (
        "automerging majors is only safe while platformAutomerge is off, so Renovate merges "
        "solely on observed-green checks rather than the CI App's ruleset bypass rights"
    )
    major_rules = [
        rule for rule in config["packageRules"] if "major" in (rule.get("matchUpdateTypes") or [])
    ]
    assert major_rules, "no packageRule matches 'major' updates"
    assert all(rule.get("automerge") is True for rule in major_rules), (
        "a rule matching 'major' updates must set automerge:true (risk-accepted policy)"
    )


def test_refresh_script_consumes_base_ref() -> None:
    """Cross-check the other half of the contract: the script actually reads BASE_REF.

    The config only arms the gate if the script consumes BASE_REF. If a later edit removes the
    BASE_REF handling from refresh-binary-checksums.sh, the env var the config injects arms
    nothing — this fails CI so the two halves can't silently drift apart.
    """
    assert "BASE_REF" in REFRESH_SCRIPT.read_text(encoding="utf-8")
