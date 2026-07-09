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
        """Whether the repository already matches the desired config."""
        return not self.changes


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
    plan, so an unchanged source secret is skipped fleet-wide without a per-repo re-push.
    """
    source_secrets = source_secret_timestamps(client)
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


def apply_plan(plan: RepoPlan) -> None:
    """Apply every change in a plan, in order."""
    for change in plan.changes:
        change.apply()
