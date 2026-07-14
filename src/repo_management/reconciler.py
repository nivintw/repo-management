# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Reconciliation engine: turn desired config into planned and applied changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from repo_management.client import get_repo, source_secret_timestamps
from repo_management.managers import build_managers

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from github import Github
    from github.Repository import Repository

    from repo_management.changes import Change
    from repo_management.config import Config, SharedConfig


@dataclass
class RepoPlan:
    """The set of changes planned for a single repository."""

    repo_name: str
    changes: list[Change] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        """Whether the repository already matches the desired config.

        False if there's anything to apply *or* any unresolved value — a plan that couldn't
        resolve a value isn't "in sync", we just couldn't compute its diff.
        """
        return not self.actionable and not self.problems

    @property
    def actionable(self) -> list[Change]:
        """The changes to apply — everything but unresolved-value diagnostics."""
        return [change for change in self.changes if not change.unresolved]

    @property
    def problems(self) -> list[Change]:
        """The unresolved-value diagnostics — values that couldn't be resolved for the diff."""
        return [change for change in self.changes if change.unresolved]


def plan_repo(
    repo: Repository,
    desired: SharedConfig,
    *,
    force_secrets: bool = False,
    source_secrets: Mapping[str, datetime] | None = None,
) -> list[Change]:
    """Aggregate the changes from every manager for one repository."""
    changes: list[Change] = []
    for manager in build_managers(force_secrets=force_secrets, source_secrets=source_secrets):
        changes.extend(manager.plan(repo, desired))
    return changes


def plan_config(client: Github, config: Config, *, force_secrets: bool = False) -> list[RepoPlan]:
    """Build a :class:`RepoPlan` for each repository, applying the shared config to each.

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
        repo = get_repo(client, name)
        plans.append(
            RepoPlan(
                name,
                plan_repo(repo, config, force_secrets=force_secrets, source_secrets=source_secrets),
            )
        )
    return plans


def _has_env_sourced_secret(config: Config) -> bool:
    """Whether any configured secret is ``value_from_env``-sourced (the only kind timestamped).

    Inline ``value`` secrets are never timestamp-compared, so a config without a single
    ``value_from_env`` secret has no use for the source-timestamp read at all.
    """
    return bool(config.secrets) and any(
        secret.value_from_env is not None for secret in config.secrets
    )


def apply_plan(plan: RepoPlan) -> None:
    """Apply every actionable change in a plan, in order.

    Skips unresolved-value diagnostics (they carry no write); the CLI refuses to apply a plan
    that has any before reaching here, so this only ever sees actionable changes in practice.
    """
    for change in plan.actionable:
        change.apply()
