# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Reconciliation engine: turn desired config into planned and applied changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from repo_management.client import get_repo
from repo_management.managers import MANAGERS

if TYPE_CHECKING:
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


def plan_repo(repo: Repository, desired: SharedConfig) -> list[Change]:
    """Aggregate the changes from every manager for one repository."""
    changes: list[Change] = []
    for manager in MANAGERS:
        changes.extend(manager.plan(repo, desired))
    return changes


def plan_config(client: Github, config: Config) -> list[RepoPlan]:
    """Build a :class:`RepoPlan` for each repository, applying the shared config to each."""
    plans: list[RepoPlan] = []
    for name in config.repos:
        repo = get_repo(client, name)
        plans.append(RepoPlan(name, plan_repo(repo, config)))
    return plans


def apply_plan(plan: RepoPlan) -> None:
    """Apply every change in a plan, in order."""
    for change in plan.changes:
        change.apply()
