# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Guard: the apply/plan workflows export exactly the configs' ``value_from_env`` secrets.

``apply``/``plan`` propagate each ``value_from_env`` secret from this repo's own Actions
secrets into the managed repos (the GitHub API can't read a secret back, so the value must be
supplied via the environment). GitHub Actions requires a *literal* ``${{ secrets.X }}`` per
secret, so that env block can't be derived from the configs at runtime — which is exactly how
it used to drift (a new managed secret needed editing the config layer AND both workflows, with
nothing catching a missed spot).

This test closes that gap: it makes ``config/`` the single source of truth and fails CI if
either workflow's exported secret set drifts from the configs' env-source names — every
``value_from_env`` (secrets/variables) plus webhook ``secret_from_env``, i.e.
:func:`~repo_management.config.fleet_env_sources`. So the literal block stays (a GHA
invariant) but can no longer silently fall out of sync (#39).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest
import yaml

from repo_management.config import fleet_env_sources

_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = _ROOT / "config"
WORKFLOWS = {
    "apply": _ROOT / ".github" / "workflows" / "apply-config.yml",
    "plan": _ROOT / ".github" / "workflows" / "plan-config.yml",
}

# An ``env:`` value that pulls from the secrets context, e.g. ``${{ secrets.GIST_PAT }}``.
_SECRET_REF = re.compile(r"\$\{\{\s*secrets\.")


@functools.lru_cache(maxsize=1)
def _expected_env_sources() -> frozenset[str]:
    """The fleet's ``value_from_env`` set, from config.fleet_env_sources (the single source).

    Cached — the configs don't change within a test run, and this is read once per case.
    """
    return frozenset(fleet_env_sources(CONFIG_DIR))


def _propagated_secret_env_keys(workflow: Path) -> set[str]:
    """Secret-sourced env-var names on the step that runs the CLI (the propagation step).

    apply/plan propagate each ``value_from_env`` secret by exporting it in the ``env:`` of the
    single step that runs ``repo-management apply``/``plan``; the CLI reads it via
    ``os.environ``. We scan ONLY that step — matched by its ``run:`` invoking
    ``repo-management`` — not the whole workflow: a secret in the preflight GATE step (a
    *separate job*, e.g. the ``CI_APP_PRIVATE_KEY`` presence check) must not mask its absence
    from the propagation step, and per-job env doesn't cross jobs at runtime anyway. Reads the
    env-var KEY (what the CLI looks up), not the secret it references. NOTE: counts ``env:``
    only — the mint credential reaches the mint-app-token action via ``with:`` (an action
    input), so it's correctly excluded; keep mint inputs in ``with:``, never ``env:``.
    """
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for job in data.get("jobs", {}).values():
        for step in job.get("steps", []):
            run = step.get("run")
            if not (isinstance(run, str) and "repo-management" in run):
                continue
            keys.update(
                key
                for key, value in (step.get("env") or {}).items()
                if isinstance(value, str) and _SECRET_REF.search(value)
            )
    return keys


def test_configs_declare_the_expected_value_from_env_secrets() -> None:
    """Lock the known set so an accidental config change is visible here, not only via drift."""
    assert _expected_env_sources() == {"CI_APP_PRIVATE_KEY", "GIST_PAT"}


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_exports_exactly_the_config_secrets(name: str) -> None:
    """Apply and plan must each export exactly the configs' value_from_env set — no drift.

    A missing name means an apply would fail to propagate (or blank) that secret on the fleet;
    an extra one is a stale export left behind after a config secret was removed.
    """
    expected = _expected_env_sources()
    actual = _propagated_secret_env_keys(WORKFLOWS[name])

    assert actual == expected, (
        f"{WORKFLOWS[name].name} secret env exports drifted from config/ value_from_env: "
        f"missing={expected - actual}, extra={actual - expected}"
    )
