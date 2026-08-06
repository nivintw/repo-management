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


def test_unlisted_direct_collaborator_is_left_alone_by_default(repo: MagicMock) -> None:
    """collaborators_mode defaults to add-only: someone added via the UI keeps their access.

    Also asserts the listing is never requested — nothing unlisted is acted on, so add-only
    works with a token that can't enumerate collaborators at all.
    """
    repo.get_collaborator_permission.return_value = "write"
    repo.get_collaborator_role_name.return_value = "write"
    repo.get_collaborators.return_value = [make_user("alice"), make_user("mallory")]
    desired = SharedConfig(collaborators=[Collaborator(username="alice", permission="push")])

    assert CollaboratorsManager().plan(repo, desired) == []
    repo.get_collaborators.assert_not_called()


def test_unlisted_direct_collaborator_is_removed_when_authoritative(repo: MagicMock) -> None:
    """collaborators_mode=authoritative restores the complete-set behaviour."""
    repo.get_collaborator_permission.return_value = "write"
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


def test_listed_collaborator_is_downgraded_under_add_only(repo: MagicMock) -> None:
    """Add-only governs *who*, not *what*: an out-of-band escalation is still walked back.

    The most security-relevant case for this default — someone listed as `pull` who was bumped
    to `admin` in the UI is returned to `pull`, even though unlisted people are untouched.
    """
    repo.get_collaborator_permission.return_value = "admin"
    repo.get_collaborator_role_name.return_value = "admin"
    desired = SharedConfig(collaborators=[Collaborator(username="alice", permission="pull")])

    changes = CollaboratorsManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE
    assert (changes[0].before, changes[0].after) == ("admin", "pull")
    changes[0].apply()
    repo.add_to_collaborators.assert_called_once_with("alice", "pull")


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


def test_collaborators_mode_without_section_is_still_unmanaged(repo: MagicMock) -> None:
    """An omitted section outranks its mode: no section means the domain is untouched.

    The dangerous misreading is the reverse — `collaborators_mode: authoritative` with no
    `collaborators:` key revoking every direct collaborator on every repo in the fleet. That is
    reachable because the mode is a separate top-level scalar that merges through `extends:`
    independently of its section.
    """
    repo.get_collaborators.return_value = [make_user("alice")]

    assert CollaboratorsManager().plan(repo, SharedConfig(collaborators_mode="authoritative")) == []
    repo.get_collaborators.assert_not_called()


def test_empty_collaborators_is_a_noop_under_add_only(repo: MagicMock) -> None:
    """`collaborators: []` no longer asserts "nobody has direct access" under the new default.

    Under 1.x this was the strongest statement in the config. It is now a no-op, and that
    inversion is silent — hence both this test and the docs note.
    """
    repo.get_collaborators.return_value = [make_user("mallory")]

    assert CollaboratorsManager().plan(repo, SharedConfig(collaborators=[])) == []


def test_empty_collaborators_revokes_everyone_when_authoritative(repo: MagicMock) -> None:
    """`collaborators: [] + authoritative` is the emergency lockdown, and must still work."""
    repo.get_collaborators.return_value = [make_user("alice"), make_user("mallory")]
    desired = SharedConfig(collaborators=[], collaborators_mode="authoritative")

    changes = CollaboratorsManager().plan(repo, desired)

    assert {change.target for change in changes} == {
        "collaborator:alice",
        "collaborator:mallory",
    }
    assert all(change.action is Action.DELETE for change in changes)
