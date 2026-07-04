# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the AutolinksManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_autolink

from repo_management.changes import Action
from repo_management.config import Autolink, SharedConfig
from repo_management.managers.autolinks import AutolinksManager


def test_no_autolinks_is_noop(repo: MagicMock) -> None:
    """A repo config without an autolinks section yields no changes."""
    desired = SharedConfig()
    assert AutolinksManager().plan(repo, desired) == []


def test_new_autolink_creates_change(repo: MagicMock) -> None:
    """An autolink in config not present on repo yields one CREATE change."""
    desired = SharedConfig(
        autolinks=[Autolink(key_prefix="TICKET-", url_template="https://example.com/TICKET-<num>")],
    )
    repo.get_autolinks.return_value = []

    changes = AutolinksManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "autolink:TICKET-"
    assert change.before is None
    assert change.after == {
        "url_template": "https://example.com/TICKET-<num>",
        "is_alphanumeric": True,
    }
    change.apply()
    repo.create_autolink.assert_called_once_with(
        "TICKET-", "https://example.com/TICKET-<num>", is_alphanumeric=True
    )


def test_existing_autolink_matches_exactly(repo: MagicMock) -> None:
    """An existing autolink that matches exactly yields no change."""
    existing = make_autolink("TICKET-", "https://example.com/TICKET-<num>")
    desired = SharedConfig(
        autolinks=[Autolink(key_prefix="TICKET-", url_template="https://example.com/TICKET-<num>")],
    )
    repo.get_autolinks.return_value = [existing]

    assert AutolinksManager().plan(repo, desired) == []


def test_extra_autolink_is_deleted(repo: MagicMock) -> None:
    """A declared autolinks section is authoritative: an autolink absent from it is deleted."""
    existing = make_autolink("STALE-", "https://example.com/STALE-<num>", autolink_id=42)
    desired = SharedConfig(
        autolinks=[Autolink(key_prefix="TICKET-", url_template="https://example.com/TICKET-<num>")],
    )
    repo.get_autolinks.return_value = [existing]

    changes = AutolinksManager().plan(repo, desired)

    actions = {change.target: change.action for change in changes}
    assert actions == {"autolink:TICKET-": Action.CREATE, "autolink:STALE-": Action.DELETE}
    delete = next(change for change in changes if change.action is Action.DELETE)
    delete.apply()
    repo.remove_autolink.assert_called_once_with(42)


def test_changed_autolink_is_delete_and_create_not_update(repo: MagicMock) -> None:
    """GitHub's autolinks API has no update endpoint.

    So a ``key_prefix`` that already exists but whose ``url_template`` or
    ``is_alphanumeric`` differs from the desired config must be planned as a DELETE of
    the stale autolink plus a CREATE of the new one -- never a single UPDATE, unlike
    every other manager in this codebase.
    """
    existing = make_autolink(
        "TICKET-", "https://old.example.com/TICKET-<num>", is_alphanumeric=False, autolink_id=7
    )
    desired = SharedConfig(
        autolinks=[
            Autolink(
                key_prefix="TICKET-",
                url_template="https://new.example.com/TICKET-<num>",
                is_alphanumeric=True,
            )
        ],
    )
    repo.get_autolinks.return_value = [existing]

    changes = AutolinksManager().plan(repo, desired)

    assert len(changes) == 2
    assert [change.action for change in changes] == [Action.DELETE, Action.CREATE]
    delete, create = changes
    assert delete.target == "autolink:TICKET-"
    assert delete.before == {
        "url_template": "https://old.example.com/TICKET-<num>",
        "is_alphanumeric": False,
    }
    assert delete.after is None
    assert create.target == "autolink:TICKET-"
    assert create.before is None
    assert create.after == {
        "url_template": "https://new.example.com/TICKET-<num>",
        "is_alphanumeric": True,
    }

    delete.apply()
    repo.remove_autolink.assert_called_once_with(7)
    create.apply()
    repo.create_autolink.assert_called_once_with(
        "TICKET-", "https://new.example.com/TICKET-<num>", is_alphanumeric=True
    )
