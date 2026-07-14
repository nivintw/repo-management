# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Guard: the apply/plan workflows export the right ``value_from_env`` sources — and diverge.

``apply`` propagates each ``value_from_env`` secret from this repo's own Actions secrets into
the managed repos (the GitHub API can't read a secret back, so the value must be supplied via
the environment). GitHub Actions requires a *literal* ``${{ secrets.X }}`` per secret, so that
env block can't be derived from the configs at runtime — which is exactly how it used to drift
(a new managed secret needed editing the config layer AND the workflows, with nothing catching
a missed spot).

``plan`` and ``apply`` **legitimately diverge**: ``plan`` is read-only and resolves only
VARIABLE values (diff-input — shown and compared to decide update-vs-no-op), while secret values
(Actions and webhook) are write-only payload resolved only at ``apply``. So ``apply`` exports
the full :func:`~repo_management.config.fleet_env_sources` (secrets + variables + webhook
secrets) and ``plan`` exports only the variable subset
(:func:`~repo_management.config.fleet_variable_env_sources`) — never secret values into the
PR-triggered plan job.

These tests make ``config/`` the single source of truth and fail CI if either workflow drifts
from its expected set. So the literal blocks stay (a GHA invariant) but can no longer silently
fall out of sync (#39).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest
import yaml

from repo_management.config import fleet_env_sources, fleet_variable_env_sources

_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = _ROOT / "config"
WORKFLOWS = {
    "apply": _ROOT / ".github" / "workflows" / "apply-config.yml",
    "plan": _ROOT / ".github" / "workflows" / "plan-config.yml",
}

# An ``env:`` value that pulls from the secrets context, e.g. ``${{ secrets.GIST_PAT }}``.
_SECRET_REF = re.compile(r"\$\{\{\s*secrets\.")
# The same, but capturing the referenced secret name (``GIST_PAT`` from the example above).
_SECRET_REF_NAME = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
# An ``env:`` value that pulls from the variables context, e.g. ``${{ vars.DEPLOY_REGION }}``.
_VAR_REF = re.compile(r"\$\{\{\s*vars\.")


@functools.lru_cache(maxsize=1)
def _expected_env_sources() -> frozenset[str]:
    """The fleet's full env-source set, from config.fleet_env_sources (the single source).

    The union of secret ``value_from_env`` + variable ``value_from_env`` + webhook
    ``secret_from_env``. Cached — the configs don't change within a test run.
    """
    return frozenset(fleet_env_sources(CONFIG_DIR))


@functools.lru_cache(maxsize=1)
def _expected_secret_env_sources() -> frozenset[str]:
    """The ``secrets``-context subset: the full set minus the variable ``value_from_env`` sources.

    Secret and webhook-secret sources are exported as ``${{ secrets.X }}``; variable sources as
    ``${{ vars.X }}``. So the ``secrets.``-context exports must equal the full set *without* the
    variable subset — comparing against the full :func:`fleet_env_sources` would spuriously fail
    the moment a config adds an env-sourced variable (exported via ``vars.``, not ``secrets.``).
    """
    return _expected_env_sources() - frozenset(fleet_variable_env_sources(CONFIG_DIR))


def _propagated_env_keys(workflow: Path, ref: re.Pattern[str]) -> set[str]:
    """Env-var names on the step that runs the CLI whose value matches ``ref`` (secrets/vars).

    apply/plan propagate each ``value_from_env`` source by exporting it in the ``env:`` of the
    single step that runs ``repo-management apply``/``plan``; the CLI reads it via
    ``os.environ``. We scan ONLY that step — matched by its ``run:`` invoking
    ``repo-management`` — not the whole workflow: a secret in the preflight GATE step (a
    *separate job*, e.g. the ``CI_APP_PRIVATE_KEY`` presence check) must not mask its absence
    from the propagation step, and per-job env doesn't cross jobs at runtime anyway. Reads the
    env-var KEY (what the CLI looks up), not the context name it references. NOTE: counts ``env:``
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
                if isinstance(value, str) and ref.search(value)
            )
    return keys


def _propagated_secret_env_keys(workflow: Path) -> set[str]:
    """The CLI step's ``${{ secrets.X }}``-sourced env-var names."""
    return _propagated_env_keys(workflow, _SECRET_REF)


def _propagated_var_env_keys(workflow: Path) -> set[str]:
    """The CLI step's ``${{ vars.X }}``-sourced env-var names (variable value sources)."""
    return _propagated_env_keys(workflow, _VAR_REF)


def _propagated_secret_env_pairs(workflow: Path) -> dict[str, str]:
    """Map each propagation-step env-var KEY to the ``secrets.<X>`` name it references.

    Same step selection as :func:`_propagated_secret_env_keys`, but keeps the referenced secret
    name so a test can assert the env-var name equals the secret name it reads.
    """
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    pairs: dict[str, str] = {}
    for job in data.get("jobs", {}).values():
        for step in job.get("steps", []):
            run = step.get("run")
            if not (isinstance(run, str) and "repo-management" in run):
                continue
            for key, value in (step.get("env") or {}).items():
                match = isinstance(value, str) and _SECRET_REF_NAME.search(value)
                if match:
                    pairs[key] = match.group(1)
    return pairs


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_secret_env_var_name_matches_its_source_secret_name(name: str) -> None:
    """Each ``KEY: ${{ secrets.REF }}`` must have ``KEY == REF``.

    The source-timestamp secret propagation (SecretsPolicy) keys its comparison by the source
    repo's *secret name* but looks it up by the config's ``value_from_env`` (the env-var KEY).
    Those coincide only under this identity convention; a ``FOO: ${{ secrets.BAR }}`` mapping
    would silently strand FOO's rotation. Lock the convention so that can't drift in unnoticed.
    """
    mismatched = {
        key: ref for key, ref in _propagated_secret_env_pairs(WORKFLOWS[name]).items() if key != ref
    }
    assert not mismatched, (
        f"{WORKFLOWS[name].name}: env var name must equal the secret it reads "
        f"(source-timestamp propagation keys on the secret name); mismatched={mismatched}"
    )


def test_configs_declare_the_expected_env_sources() -> None:
    """Lock the known sets so an accidental config change is visible here, not only via drift.

    The full set (apply) is the three secrets; the variable subset (plan) is empty — this repo's
    configs declare no ``value_from_env`` variables, so ``plan`` needs no value env vars at all.
    """
    assert _expected_env_sources() == {"CI_APP_PRIVATE_KEY", "GIST_PAT", "ROADMAP_PROJECT_TOKEN"}
    assert frozenset(fleet_variable_env_sources(CONFIG_DIR)) == frozenset()


def test_apply_exports_exactly_the_secret_sources() -> None:
    """Apply's ``secrets``-context exports must equal the secret + webhook-secret sources.

    apply propagates every value, but secret and webhook-secret sources ride as ``${{ secrets.X }}``
    while variable sources ride as ``${{ vars.X }}`` (asserted separately). So the ``secrets.``
    exports must equal the full set minus the variable subset — a missing name means apply would
    fail to propagate (or blank) that value on the fleet; an extra one is a stale export.
    """
    expected = _expected_secret_env_sources()
    actual = _propagated_secret_env_keys(WORKFLOWS["apply"])

    assert actual == expected, (
        f"apply-config.yml secret env exports drifted from config secret/webhook sources: "
        f"missing={expected - actual}, extra={actual - expected}"
    )


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_exports_exactly_the_variable_sources(name: str) -> None:
    """Both workflows must export exactly the fleet's variable value_from_env set as ${{ vars.X }}.

    Variable values are diff-input — `plan` resolves them to build the diff and `apply` to write
    them — so BOTH workflows must export their sources (as `vars.`, since variables are
    non-secret). Empty today (no env-sourced variables), so this locks that adding one without
    the matching `${{ vars.X }}` line in *both* workflows fails here, not only at runtime.
    """
    expected = frozenset(fleet_variable_env_sources(CONFIG_DIR))
    actual = _propagated_var_env_keys(WORKFLOWS[name])

    assert actual == expected, (
        f"{WORKFLOWS[name].name} variable env exports drifted from config variable sources: "
        f"missing={expected - actual}, extra={actual - expected}"
    )


def test_plan_exports_no_secret_values() -> None:
    """Plan must export NO secret values — they're write-only, resolved only at apply.

    plan is read-only and resolves only VARIABLE values (diff-input); secret values (Actions and
    webhook) are write-only payload resolved at apply, so exporting them into the PR-triggered
    plan job is needless secret exposure. This is the deliberate divergence from apply. (Variable
    ``value_from_env`` sources, if any, ride as ``${{ vars.X }}`` — non-secret and outside this
    secrets-only guard; the fleet has none today, per the lock above.)
    """
    actual = _propagated_secret_env_keys(WORKFLOWS["plan"])

    assert actual == set(), (
        f"plan-config.yml must export no secret values (secrets resolve at apply, not plan); "
        f"found stale secret exports: {actual}"
    )
