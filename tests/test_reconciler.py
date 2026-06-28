# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the reconciliation engine."""

from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_secret

from repo_management.changes import Action, Change
from repo_management.config import Config, Secret, Settings, SharedConfig
from repo_management.reconciler import RepoPlan, apply_plan, plan_config, plan_repo


def test_plan_repo_aggregates_managers(repo: MagicMock) -> None:
    """plan_repo collects changes from every manager that has work."""
    repo.description = "old"
    repo.get_topics.return_value = []
    desired = SharedConfig(settings=Settings(description="new", topics=["x"]))

    changes = plan_repo(repo, desired)

    targets = {c.target for c in changes}
    assert "settings" in targets
    assert "topics" in targets


def test_plan_repo_force_secrets_repushes(repo: MagicMock) -> None:
    """force_secrets threads through build_managers so existing secrets are re-pushed."""
    repo.get_secrets.return_value = [make_secret("EXISTING")]
    desired = SharedConfig(secrets=[Secret(name="EXISTING", value="v")])

    assert plan_repo(repo, desired) == []
    assert [c.action for c in plan_repo(repo, desired, force_secrets=True)] == [Action.UPDATE]


def test_plan_config_builds_a_plan_per_repo() -> None:
    """plan_config fetches each named repo and returns one RepoPlan apiece."""
    repo = MagicMock()
    repo.description = "match"
    client = MagicMock()
    client.get_repo.return_value = repo
    config = Config(repos=["o/r1", "o/r2"], settings=Settings(description="match"))

    plans = plan_config(client, config)

    assert [p.repo_name for p in plans] == ["o/r1", "o/r2"]
    assert all(p.in_sync for p in plans)
    assert client.get_repo.call_count == 2


def test_repo_plan_in_sync() -> None:
    """RepoPlan.in_sync reflects whether there are changes."""
    assert RepoPlan("o/r").in_sync
    change = Change("x", Action.CREATE, "t", None, None, lambda: None)
    assert not RepoPlan("o/r", [change]).in_sync


def test_apply_plan_invokes_each_change() -> None:
    """apply_plan calls apply() on every change in order."""
    calls: list[str] = []
    plan = RepoPlan(
        "o/r",
        [
            Change("x", Action.CREATE, "a", None, None, lambda: calls.append("a")),
            Change("x", Action.UPDATE, "b", None, None, lambda: calls.append("b")),
        ],
    )
    apply_plan(plan)
    assert calls == ["a", "b"]
