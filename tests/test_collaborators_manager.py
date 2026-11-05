# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the collaborators manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from conftest import make_user

from repo_management.changes import Action
from repo_management.config import Collaborator, Permission, SectionMode, SharedConfig
from repo_management.managers.collaborators import CollaboratorsManager


def test_no_collaborators_is_noop(repo: MagicMock) -> None:
    """A repo config without collaborators yields no changes."""
    desired = SharedConfig()
    assert CollaboratorsManager().plan(repo, desired) == []


def test_new_collaborator_produces_create(repo: MagicMock) -> None:
    """A non-collaborator yields a create that calls add_to_collaborators."""
    repo.has_in_collaborators.return_value = False
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


@pytest.mark.parametrize("permission", ["pull", "push"])
def test_non_collaborator_on_a_public_repo_is_created(
    repo: MagicMock, permission: Permission
) -> None:
    """A public repo reports anyone as "read", which mustn't pass for an existing grant."""
    repo.has_in_collaborators.return_value = False
    repo.get_collaborator_permission.return_value = "read"
    repo.get_collaborator_role_name.return_value = "read"
    desired = SharedConfig(collaborators=[Collaborator(username="alice", permission=permission)])

    changes = CollaboratorsManager().plan(repo, desired)

    assert [(change.action, change.before, change.after) for change in changes] == [
        (Action.CREATE, None, permission)
    ]


def test_existing_write_and_desired_push_produces_no_change(repo: MagicMock) -> None:
    """An existing 'write' role with desired 'push' yields no change."""
    repo.get_collaborator_role_name.return_value = "write"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="push")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_existing_read_and_desired_push_produces_update(repo: MagicMock) -> None:
    """An existing 'read' role with desired 'push' yields one update change."""
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
    repo.get_collaborator_role_name.return_value = "admin"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="admin")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_maintain_converges(repo: MagicMock) -> None:
    """Regression: 'maintain' (legacy permission reports 'write') must converge via role_name."""
    repo.get_collaborator_role_name.return_value = "maintain"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="maintain")],
    )
    assert CollaboratorsManager().plan(repo, desired) == []


def test_existing_triage_and_desired_maintain_produces_update(repo: MagicMock) -> None:
    """An existing 'triage' role with desired 'maintain' yields one update change."""
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


def test_unlisted_direct_collaborator_is_left_alone_by_default(repo: MagicMock) -> None:
    """collaborators_mode defaults to add-only: someone added via the UI keeps their access.

    Also asserts the listing is never requested — nothing unlisted is acted on, so add-only
    works with a token that can't enumerate collaborators at all.
    """
    repo.get_collaborator_role_name.return_value = "write"
    repo.get_collaborators.return_value = [make_user("alice"), make_user("mallory")]
    desired = SharedConfig(collaborators=[Collaborator(username="alice", permission="push")])

    assert CollaboratorsManager().plan(repo, desired) == []
    repo.get_collaborators.assert_not_called()


def test_unlisted_direct_collaborator_is_removed_when_authoritative(repo: MagicMock) -> None:
    """collaborators_mode=authoritative restores the complete-set behaviour."""
    repo.get_collaborator_role_name.return_value = "write"
    repo.get_collaborators.return_value = [make_user("alice"), make_user("mallory")]
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="push")],
        collaborators_mode="authoritative",
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1  # alice is in sync; mallory is pruned
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "collaborator:mallory"
    assert (change.before, change.after) == ("mallory", None)
    repo.get_collaborators.assert_called_once_with(affiliation="direct")
    change.apply()
    repo.remove_from_collaborators.assert_called_once_with("mallory")


@pytest.mark.parametrize("mode", ["add-only", "authoritative"])
def test_listed_collaborator_is_downgraded(repo: MagicMock, mode: SectionMode) -> None:
    """Add-only governs *who*, not *what*: an out-of-band escalation is still walked back.

    The most security-relevant case for this default — someone listed as `pull` who was bumped
    to `admin` in the UI is returned to `pull`, even though unlisted people are untouched.
    """
    repo.get_collaborator_role_name.return_value = "admin"
    desired = SharedConfig(
        collaborators=[Collaborator(username="alice", permission="pull")],
        collaborators_mode=mode,
    )

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE
    assert (changes[0].before, changes[0].after) == ("admin", "pull")
    changes[0].apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "pull")


def test_multiple_collaborators(repo: MagicMock) -> None:
    """Several collaborators with different states produce the correct changes."""
    repo.has_in_collaborators.side_effect = [False, True, True, True]
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


@pytest.mark.parametrize(("listed", "live"), [("Alice", "alice"), ("alice", "Alice")])
def test_listed_collaborator_with_different_case_is_not_removed(
    repo: MagicMock, listed: str, live: str
) -> None:
    """GitHub logins are case-insensitive, so a listed person is never pruned over casing."""
    repo.get_collaborator_role_name.return_value = "write"
    repo.get_collaborators.return_value = [make_user(live)]
    desired = SharedConfig(
        collaborators=[Collaborator(username=listed, permission="push")],
        collaborators_mode="authoritative",
    )

    assert CollaboratorsManager().plan(repo, desired) == []
