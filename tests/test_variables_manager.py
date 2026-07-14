# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the variables manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from conftest import make_variable

from repo_management.changes import Action
from repo_management.config import SharedConfig, Variable
from repo_management.managers.variables import VariablesManager


def test_no_variables_is_noop(repo: MagicMock) -> None:
    """A repo config without a variables section yields no changes."""
    desired = SharedConfig()
    assert VariablesManager().plan(repo, desired) == []


def test_new_variable_produces_create(repo: MagicMock) -> None:
    """A variable not in get_variables() yields one create change showing its value."""
    repo.get_variables.return_value = []
    desired = SharedConfig(variables=[Variable(name="REGION", value="us-east-1")])

    changes = VariablesManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "variable:REGION"
    assert (change.before, change.after) == (None, "us-east-1")
    assert change.secret is False
    change.apply()
    repo.create_variable.assert_called_once_with("REGION", "us-east-1")
    assert "us-east-1" in change.describe()


def test_unchanged_variable_is_noop(repo: MagicMock) -> None:
    """A variable whose value already matches yields no change."""
    repo.get_variables.return_value = [make_variable("REGION", "us-east-1")]
    desired = SharedConfig(variables=[Variable(name="REGION", value="us-east-1")])

    assert VariablesManager().plan(repo, desired) == []


def test_changed_variable_produces_update(repo: MagicMock) -> None:
    """A variable whose value differs yields one update change with both values shown."""
    current = make_variable("REGION", "us-east-1")
    repo.get_variables.return_value = [current]
    desired = SharedConfig(variables=[Variable(name="REGION", value="eu-west-2")])

    changes = VariablesManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert (change.before, change.after) == ("us-east-1", "eu-west-2")
    change.apply()
    current.edit.assert_called_once_with("eu-west-2")


def test_variable_value_from_env_is_resolved(repo: MagicMock, monkeypatch) -> None:  # noqa: ANN001
    """A variable sourced from the environment resolves its value at plan time."""
    monkeypatch.setenv("DEPLOY_REGION", "ap-south-1")
    repo.get_variables.return_value = []
    desired = SharedConfig(variables=[Variable(name="REGION", value_from_env="DEPLOY_REGION")])

    changes = VariablesManager().plan(repo, desired)

    assert changes[0].after == "ap-south-1"
    changes[0].apply()
    repo.create_variable.assert_called_once_with("REGION", "ap-south-1")


def test_unresolvable_variable_is_a_diagnostic_not_a_crash(
    repo: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A variable whose value can't be resolved becomes a diagnostic without aborting the plan.

    Unlike a secret, a variable's value is diff-input, so it's resolved at plan time. But one
    truly-absent value must not hide the rest of the plan: the stale delete still shows, and the
    unresolvable variable is a `!` diagnostic that makes the plan a hard failure.
    """
    monkeypatch.delenv("VAR_SRC", raising=False)
    stale = make_variable("STALE", "old")
    repo.get_variables.return_value = [stale]
    desired = SharedConfig(variables=[Variable(name="REGION", value_from_env="VAR_SRC")])

    changes = VariablesManager().plan(repo, desired)  # must not raise

    by_target = {change.target: change for change in changes}
    assert by_target["variable:STALE"].action is Action.DELETE  # the rest of the plan survives
    problem = by_target["variable:REGION"]
    assert problem.unresolved
    assert problem.describe().startswith("! [variables] variable:REGION:")
    # The diagnostic is never applied (the CLI refuses first), but fails loud if it ever were.
    with pytest.raises(RuntimeError):
        problem.apply()


def test_unlisted_variable_is_deleted(repo: MagicMock) -> None:
    """A declared variables section is authoritative: a variable absent from it is deleted."""
    stale = make_variable("STALE", "old")
    repo.get_variables.return_value = [stale]
    desired = SharedConfig(variables=[Variable(name="WANTED", value="v")])

    changes = VariablesManager().plan(repo, desired)

    actions = {change.target: change.action for change in changes}
    assert actions == {"variable:WANTED": Action.CREATE, "variable:STALE": Action.DELETE}
    delete = next(change for change in changes if change.action is Action.DELETE)
    assert (delete.before, delete.after) == ("old", None)
    delete.apply()
    stale.delete.assert_called_once_with()
