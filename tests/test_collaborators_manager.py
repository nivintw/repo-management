# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the collaborators manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_management.changes import Action
from repo_management.config import Collaborator, RepoConfig
from repo_management.managers.collaborators import CollaboratorsManager


def test_no_collaborators_is_noop(repo: MagicMock) -> None:
    """A repo config without collaborators yields no changes."""
    desired = RepoConfig(name="o/r")
    assert CollaboratorsManager().plan(repo, desired) == []


def test_new_collaborator_produces_create(repo: MagicMock) -> None:
    """A new collaborator yields one create change that calls repo.add_to_collaborators."""
    repo.get_collaborator_permission.return_value = "none"
    desired = RepoConfig(
        name="o/r",
        collaborators=[Collaborator(username="alice", permission="push")],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "collaborator:alice"
    assert (change.before, change.after) == (None, "push")
    change.apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "push")


def test_existing_write_and_desired_push_produces_no_change(repo: MagicMock) -> None:
    """An existing 'write' permission with desired 'push' yields no change."""
    repo.get_collaborator_permission.return_value = "write"
    desired = RepoConfig(
        name="o/r",
        collaborators=[Collaborator(username="alice", permission="push")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_existing_read_and_desired_push_produces_update(repo: MagicMock) -> None:
    """An existing 'read' permission with desired 'push' yields one update change."""
    repo.get_collaborator_permission.return_value = "read"
    desired = RepoConfig(
        name="o/r",
        collaborators=[Collaborator(username="alice", permission="push")],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "collaborator:alice"
    assert (change.before, change.after) == ("pull", "push")
    change.apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "push")


def test_existing_admin_and_desired_admin_produces_no_change(repo: MagicMock) -> None:
    """An existing 'admin' permission with desired 'admin' yields no change."""
    repo.get_collaborator_permission.return_value = "admin"
    desired = RepoConfig(
        name="o/r",
        collaborators=[Collaborator(username="alice", permission="admin")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_existing_triage_and_desired_maintain_produces_update(repo: MagicMock) -> None:
    """An existing 'triage' permission with desired 'maintain' yields one update change."""
    repo.get_collaborator_permission.return_value = "triage"
    desired = RepoConfig(
        name="o/r",
        collaborators=[Collaborator(username="alice", permission="maintain")],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "collaborator:alice"
    assert (change.before, change.after) == ("triage", "maintain")
    change.apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "maintain")


def test_multiple_collaborators(repo: MagicMock) -> None:
    """Several collaborators with different states produce the correct changes."""
    repo.get_collaborator_permission.side_effect = ["none", "write", "read", "admin"]
    desired = RepoConfig(
        name="o/r",
        collaborators=[
            Collaborator(username="alice", permission="push"),
            Collaborator(username="bob", permission="push"),
            Collaborator(username="charlie", permission="push"),
            Collaborator(username="dave", permission="admin"),
        ],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 2
    change_alice, change_charlie = sorted(
        changes,
        key=lambda c: c.target,
    )
    assert change_alice.action is Action.CREATE
    assert change_alice.target == "collaborator:alice"
    assert (change_alice.before, change_alice.after) == (None, "push")
    change_alice.apply()
    repo.add_to_collaborators.assert_any_call("alice", "push")

    assert change_charlie.action is Action.UPDATE
    assert change_charlie.target == "collaborator:charlie"
    assert (change_charlie.before, change_charlie.after) == ("pull", "push")
    change_charlie.apply()
    repo.add_to_collaborators.assert_any_call("charlie", "push")
