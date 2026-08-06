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
from repo_management.client import api_message, get_repo, source_secret_timestamps
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
# Failures a repository reconcile anticipates, and whose message already says everything useful:
# a GitHub API rejection or a config problem. Anything else reaching a handler below is a bug in
# this tool rather than a fact about the repository — see :func:`_describe_failure`. The CLI
# boundary's ``_api_errors`` recognizes a wider set (it also fronts the projects sub-app, which
# no manager here can raise from); this tuple is deliberately the narrower, per-repo subset.
_EXPECTED_FAILURES = (GithubException, ConfigError)


def _describe_failure(exc: Exception) -> str:
    """Render an exception for a diagnostic, keeping the traceback for unanticipated types.

    Isolating faults means an exception becomes a printed line instead of a crash, which on its
    own would trade a stack trace for one sentence. Anticipated failures lose nothing by that:
    a 403 or a missing environment variable is fully described by its message. An unexpected
    type is a bug here rather than a repo-state problem, so it keeps its traceback instead of
    being flattened into a one-liner nobody can act on.
    """
    detail = api_message(exc) if isinstance(exc, GithubException) else str(exc)
    summary = f"{type(exc).__name__}: {detail}"
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


@dataclass
class ApplyReport:
    """The outcome of applying one repository's plan."""

    repo_name: str
    applied: list[Change] = field(default_factory=list)
    failed: list[tuple[Change, str]] = field(default_factory=list)


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
        except Exception as exc:  # noqa: BLE001 - fault isolation; see the module docstring
            changes.append(Change.diagnostic(manager.domain, _PLAN_TARGET, _describe_failure(exc)))
    return changes


def plan_config(client: Github, config: Config, *, force_secrets: bool = False) -> list[RepoPlan]:
    """Build a :class:`RepoPlan` for each repository, applying the shared config to each.

    A repository that can't be fetched yields a plan carrying a single repo-level diagnostic
    rather than aborting the fleet, so one renamed repo or one revoked grant can't cost the
    operator all fifteen other diffs. (A failure *inside* planning is already contained
    per-domain by :func:`plan_repo`; this handler covers the fetch and the manager construction
    that happen before any manager runs.)

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
        except Exception as exc:  # noqa: BLE001 - fault isolation; see the module docstring
            changes = [Change.diagnostic(_REPO_DOMAIN, name, _describe_failure(exc))]
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


def preflight_plan(plan: RepoPlan) -> str | None:
    """Decide whether a repository is safe to write to, returning why it isn't — or ``None``.

    Two things hold a repository back, and they're the same decision made from two directions:

    - Its plan carries a problem, so the diff was computed from a partial picture of the repo.
    - A write payload won't resolve. Secret values resolve lazily at the write, so a missing one
      wouldn't otherwise surface until mid-apply; resolving them up front keeps a repository's
      own writes all-or-nothing.

    Either way the cost is one repository, never the fleet. ``plan`` never calls this — secrets
    are write-only, resolved only when applying.
    """
    if plan.problems:
        return f"{len(plan.problems)} problem(s) in its plan — see the ! line(s) above"
    try:
        for change in plan.actionable:
            if change.preflight is not None:
                change.preflight()
    except Exception as exc:  # noqa: BLE001 - fault isolation; see the module docstring
        return _describe_failure(exc)
    return None


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
        except Exception as exc:  # noqa: BLE001 - fault isolation; see the module docstring
            report.failed.append((change, _describe_failure(exc)))
        else:
            report.applied.append(change)
    return report
