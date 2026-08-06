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

from github import BadCredentialsException, GithubException, RateLimitExceededException

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
# a GitHub API rejection, a config problem, or a transport error. `OSError` covers the last of
# those because `requests`' exceptions subclass it — a connection reset is a fact about the
# network, not a bug here, and formatting a urllib3 stack for it (per repo, per domain) would
# bury the run in thousands of lines. Kept in step with the CLI boundary's `_api_errors`, which
# recognizes the same three plus `ProjectError` for the projects sub-app this never reaches.
_EXPECTED_FAILURES = (GithubException, ConfigError, OSError)
# Conditions that doom the whole run, so isolating them per repository would report one problem
# N times and stall on retry backoff. These stay fatal and surface once, at the CLI boundary.
_FLEET_FATAL = (BadCredentialsException, RateLimitExceededException)


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
    # Changes never attempted because an earlier write in the same domain failed. Distinct from
    # ``failed``: these were abandoned deliberately, not rejected by the API.
    abandoned: list[tuple[Change, str]] = field(default_factory=list)


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
        except _FLEET_FATAL:
            raise  # dooms the run, not this domain — see the constant's comment
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
        except _FLEET_FATAL:
            # A dead token or an exhausted rate limit is a fact about the *run*, not this repo.
            # Isolating it would repeat the same failure for every repository — and, because
            # PyGithub retries rate-limit responses with backoff, would turn one fast failure
            # into a long stall that deepens the secondary-rate-limit penalty.
            raise
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
      own writes all-or-nothing *with respect to unresolvable payloads* — a write the API
      rejects is isolated per domain (see :func:`apply_plan`), not per repository.

    Either way the cost is one repository, never the fleet. ``plan`` never calls this — secrets
    are write-only, resolved only when applying.
    """
    if plan.problems:
        return f"{len(plan.problems)} problem(s) in its plan — see the ! line(s) above"
    try:
        for change in plan.actionable:
            if change.preflight is not None:
                change.preflight()
    except _FLEET_FATAL:
        raise  # dooms the run, not this repo — see the constant's comment
    except Exception as exc:  # noqa: BLE001 - fault isolation; see the module docstring
        return _describe_failure(exc)
    return None


def apply_plan(plan: RepoPlan) -> ApplyReport:
    """Apply a plan's actionable changes in order, isolating failures **per domain**.

    Domains are as independent as repositories — a 403 writing webhooks says nothing about
    whether labels can be written — so one domain's failure never stops the others.

    Within a domain it is the opposite, and the distinction is load-bearing rather than
    fastidious. An authoritative section expresses a *replacement* as two changes: every manager
    emits its creates and updates first and its deletes last, so a renamed ruleset is a CREATE of
    the new name followed by a DELETE of the old. Those two are halves of one operation. If the
    CREATE is rejected — a plan tier without rulesets, an invite cap, an org policy — running the
    DELETE anyway leaves the repository *worse* than before the run: the branch protection is
    gone and nothing replaced it. So the first failure in a domain abandons that domain's
    remaining changes, which are reported as abandoned rather than silently dropped.

    Diagnostics carry no write and are skipped; the CLI holds back any plan carrying one, so in
    practice this only ever sees actionable changes.
    """
    report = ApplyReport(plan.repo_name)
    broken: set[str] = set()
    for change in plan.actionable:
        if change.domain in broken:
            reason = f"not attempted: an earlier {change.domain} write failed"
            report.abandoned.append((change, reason))
            continue
        try:
            change.apply()
        except _FLEET_FATAL:
            raise  # dooms the run, not this domain — see the constant's comment
        except Exception as exc:  # noqa: BLE001 - fault isolation; see the module docstring
            broken.add(change.domain)
            report.failed.append((change, _describe_failure(exc)))
        else:
            report.applied.append(change)
    return report
