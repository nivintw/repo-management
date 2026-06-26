# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the collaborators manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_user

from repo_management.changes import Action
from repo_management.config import Collaborator, SharedConfig
from repo_management.managers.collaborators import CollaboratorsManager


def test_no_collaborators_is_noop(repo: MagicMock) -> None:
    """A repo config without collaborators yields no changes."""
    desired = SharedConfig()
    assert CollaboratorsManager().plan(repo, desired) == []


def test_new_collaborator_produces_create(repo: MagicMock) -> None:
    """A non-collaborator (permission 'none') yields a create that calls add_to_collaborators."""
    repo.get_collaborator_permission.return_value = "none"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="push")],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "collaborator:alice"
    assert (change.before, change.after) == (None, "push")
    repo.get_collaborator_role_name.assert_not_called()
    change.apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "push")


def test_existing_write_and_desired_push_produces_no_change(repo: MagicMock) -> None:
    """An existing 'write' role with desired 'push' yields no change."""
    repo.get_collaborator_permission.return_value = "write"
    repo.get_collaborator_role_name.return_value = "write"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="push")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_existing_read_and_desired_push_produces_update(repo: MagicMock) -> None:
    """An existing 'read' role with desired 'push' yields one update change."""
    repo.get_collaborator_permission.return_value = "read"
    repo.get_collaborator_role_name.return_value = "read"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="push")],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert (change.before, change.after) == ("pull", "push")
    change.apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "push")


def test_existing_admin_and_desired_admin_produces_no_change(repo: MagicMock) -> None:
    """An existing 'admin' role with desired 'admin' yields no change."""
    repo.get_collaborator_permission.return_value = "admin"
    repo.get_collaborator_role_name.return_value = "admin"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="admin")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_maintain_converges(repo: MagicMock) -> None:
    """Regression: 'maintain' (legacy permission reports 'write') must converge via role_name."""
    repo.get_collaborator_permission.return_value = "write"  # legacy collapse of maintain
    repo.get_collaborator_role_name.return_value = "maintain"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="maintain")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_existing_triage_and_desired_maintain_produces_update(repo: MagicMock) -> None:
    """An existing 'triage' role with desired 'maintain' yields one update change."""
    repo.get_collaborator_permission.return_value = "read"  # legacy collapse of triage
    repo.get_collaborator_role_name.return_value = "triage"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="maintain")],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert (change.before, change.after) == ("triage", "maintain")
    change.apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "maintain")


def test_unlisted_direct_collaborator_is_removed(repo: MagicMock) -> None:
    """A direct collaborator absent from the config is removed (authoritative)."""
    repo.get_collaborator_permission.return_value = "write"
    repo.get_collaborator_role_name.return_value = "write"
    repo.get_collaborators.return_value = [make_user("alice"), make_user("mallory")]
    desired = SharedConfig(collaborators=[Collaborator(username="alice", permission="push")])

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1  # alice is in sync; mallory is pruned
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "collaborator:mallory"
    assert (change.before, change.after) == ("mallory", None)
    repo.get_collaborators.assert_called_once_with(affiliation="direct")
    change.apply()
    repo.remove_from_collaborators.assert_called_once_with("mallory")


def test_multiple_collaborators(repo: MagicMock) -> None:
    """Several collaborators with different states produce the correct changes."""
    repo.get_collaborator_permission.side_effect = ["none", "write", "read", "admin"]
    repo.get_collaborator_role_name.side_effect = ["write", "read", "admin"]
    desired = SharedConfig(
        collaborators=[
            Collaborator(username="alice", permission="push"),
            Collaborator(username="bob", permission="push"),
            Collaborator(username="charlie", permission="push"),
            Collaborator(username="dave", permission="admin"),
        ],
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 2
    change_alice, change_charlie = sorted(changes, key=lambda c: c.target)
    assert change_alice.action is Action.CREATE
    assert change_alice.target == "collaborator:alice"
    assert change_charlie.action is Action.UPDATE
    assert change_charlie.target == "collaborator:charlie"
    assert (change_charlie.before, change_charlie.after) == ("pull", "push")
