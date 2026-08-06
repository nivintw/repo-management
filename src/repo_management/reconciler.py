# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Reconciliation engine: turn desired config into planned and applied changes.

Every repository in a fleet run is independent. A failure attributable to one repo — a plan
tier without rulesets, a visibility-conditional endpoint, a token missing admin, a repo that
was renamed out from under the config — degrades to a diagnostic for that repo (and, where the
failure belongs to one domain, that domain) instead of aborting the run. The operator still
gets every other repo's diff, and every healthy repo still applies.

Failures reuse the unresolved-value diagnostic rather than a parallel error channel: "this
domain couldn't be planned" and "this value couldn't be resolved" mean the same thing
downstream — the repository isn't fully planned, so it must not be written to, and the run must
exit non-zero.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from github import GithubException

from repo_management.changes import Change
from repo_management.client import get_repo, source_secret_timestamps
from repo_management.config import ConfigError
from repo_management.managers import build_managers

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from github import Github
    from github.Repository import Repository

    from repo_management.config import Config, SharedConfig

# The pseudo-domain for a failure that struck before any manager ran: the repository itself
# couldn't be fetched, so no single domain is implicated.
_REPO_DOMAIN = "repo"
# The target of a diagnostic standing in for a manager whose plan() raised. The failure belongs
# to the whole domain, not to one entity inside it.
_PLAN_TARGET = "plan"
# Failures this tool anticipates, and whose message already says everything useful: a GitHub API
# rejection or a config problem. Anything else reaching a handler below is a bug in this tool
# rather than a fact about the repository — see :func:`describe_failure`.
_EXPECTED_FAILURES = (GithubException, ConfigError)


def describe_failure(exc: Exception) -> str:
    """Render an exception for a diagnostic, keeping the traceback for unanticipated types.

    Isolating faults means an exception becomes a printed line instead of a crash, which on its
    own would trade a stack trace for one sentence. Anticipated failures lose nothing by that:
    a 403 or a missing environment variable is fully described by its message. An unexpected
    type is a bug here rather than a repo-state problem, so it keeps its traceback instead of
    being flattened into a one-liner nobody can act on.
    """
    summary = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, _EXPECTED_FAILURES):
        return summary
    stack = "".join(traceback.format_exception(exc)).rstrip()
    return f"{summary}\n{stack}"


@dataclass
class RepoPlan:
    """The set of changes planned for a single repository."""

    repo_name: str
    changes: list[Change] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        """Whether the repository already matches the desired config.

        False if there's anything to apply *or* any problem — a plan that couldn't resolve a
        value or couldn't read a domain isn't "in sync", we just couldn't compute its diff.
        """
        return not self.actionable and not self.problems

    @property
    def actionable(self) -> list[Change]:
        """The changes to apply — everything but diagnostics."""
        return [change for change in self.changes if not change.unresolved]

    @property
    def problems(self) -> list[Change]:
        """The diagnostics: values that wouldn't resolve, and domains that wouldn't plan."""
        return [change for change in self.changes if change.unresolved]

    @property
    def healthy(self) -> bool:
        """Whether this plan is safe to apply.

        A plan carrying any problem is only a partial picture of the repository, so applying it
        would write a diff computed from incomplete state. Such a repo is skipped — which costs
        only that repo, not the fleet.
        """
        return not self.problems


@dataclass
class ApplyReport:
    """The outcome of applying one repository's plan."""

    repo_name: str
    applied: list[Change] = field(default_factory=list)
    failed: list[tuple[Change, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether every change in the plan applied cleanly."""
        return not self.failed


def plan_repo(
    repo: Repository,
    desired: SharedConfig,
    *,
    force_secrets: bool = False,
    source_secrets: Mapping[str, datetime] | None = None,
) -> list[Change]:
    """Aggregate the changes from every manager for one repository.

    Each manager is isolated. Every manager reads from the API while planning, and those reads
    fail for reasons specific to one repository — a plan tier that doesn't carry rulesets, an
    Actions endpoint that only exists for one visibility, a token without admin. One domain's
    failure therefore costs its own diff and nothing else: the remaining managers still plan,
    and the failure is reported against the domain that owns it.
    """
    changes: list[Change] = []
    for manager in build_managers(force_secrets=force_secrets, source_secrets=source_secrets):
        try:
            changes.extend(manager.plan(repo, desired))
        except Exception as exc:  # noqa: BLE001 - isolating the domain is the whole point; the
            # type is preserved in the diagnostic and an unexpected one keeps its traceback.
            changes.append(Change.diagnostic(manager.domain, _PLAN_TARGET, describe_failure(exc)))
    return changes


def plan_config(client: Github, config: Config, *, force_secrets: bool = False) -> list[RepoPlan]:
    """Build a :class:`RepoPlan` for each repository, applying the shared config to each.

    A repository that can't be fetched or planned yields a plan carrying a single repo-level
    diagnostic rather than aborting the fleet, so one renamed repo or one revoked grant can't
    cost the operator all fifteen other diffs.

    The source repo's secret timestamps are read once up front and shared across every repo's
    plan, so an unchanged source secret is skipped fleet-wide without a per-repo re-push. The
    read is skipped entirely — no wasted round-trip, no misleading "unavailable" warning — when
    nothing would consult it: under ``--force-secrets`` (which re-pushes everything anyway), or
    when no configured secret is ``value_from_env``-sourced (only those are timestamp-compared).
    """
    read_timestamps = not force_secrets and _has_env_sourced_secret(config)
    source_secrets = source_secret_timestamps(client) if read_timestamps else {}
    plans: list[RepoPlan] = []
    for name in config.repos:
        try:
            repo = get_repo(client, name)
            changes = plan_repo(
                repo, config, force_secrets=force_secrets, source_secrets=source_secrets
            )
        except Exception as exc:  # noqa: BLE001 - a repo-level failure must cost only this repo;
            # the type is preserved in the diagnostic and an unexpected one keeps its traceback.
            changes = [Change.diagnostic(_REPO_DOMAIN, name, describe_failure(exc))]
        plans.append(RepoPlan(name, changes))
    return plans


def _has_env_sourced_secret(config: Config) -> bool:
    """Whether any configured secret is ``value_from_env``-sourced (the only kind timestamped).

    Inline ``value`` secrets are never timestamp-compared, so a config without a single
    ``value_from_env`` secret has no use for the source-timestamp read at all.
    """
    return bool(config.secrets) and any(
        secret.value_from_env is not None for secret in config.secrets
    )


def apply_plan(plan: RepoPlan) -> ApplyReport:
    """Apply every actionable change in a plan, in order, isolating each failure.

    A change that raises is recorded and the rest still apply. Domains are as independent as
    repositories: a 403 writing webhooks says nothing about whether labels can be written, and
    abandoning the remainder would leave the repository further from its desired state than the
    one failure requires.

    Diagnostics carry no write and are skipped; the CLI holds back any plan carrying one, so in
    practice this only ever sees actionable changes.
    """
    report = ApplyReport(plan.repo_name)
    for change in plan.actionable:
        try:
            change.apply()
        except Exception as exc:  # noqa: BLE001 - one failed write must not abandon the repo's
            # remaining changes; the type is preserved and an unexpected one keeps its traceback.
            report.failed.append((change, describe_failure(exc)))
        else:
            report.applied.append(change)
    return report
