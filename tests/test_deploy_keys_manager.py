# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the DeployKeysManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_deploy_key

from repo_management.changes import Action
from repo_management.config import DeployKey, SharedConfig
from repo_management.managers.deploy_keys import DeployKeysManager


def test_no_deploy_keys_is_noop(repo: MagicMock) -> None:
    """A repo config without a deploy_keys section yields no changes."""
    desired = SharedConfig()
    repo.get_keys.return_value = []
    assert DeployKeysManager().plan(repo, desired) == []


def test_new_deploy_key_creates_change(repo: MagicMock) -> None:
    """A deploy key in config not present on repo yields one CREATE change."""
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA...", read_only=True)],
    )
    repo.get_keys.return_value = []

    changes = DeployKeysManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "deploy_key:ci"
    assert change.before is None
    assert change.after == {"title": "ci", "read_only": True}
    change.apply()
    repo.create_key.assert_called_once_with("ci", "ssh-ed25519 AAAA...", read_only=True)


def test_existing_deploy_key_matches_exactly(repo: MagicMock) -> None:
    """An existing deploy key that matches exactly yields no change."""
    existing = make_deploy_key(title="ci", key="ssh-ed25519 AAAA...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA...", read_only=True)],
    )
    repo.get_keys.return_value = [existing]

    assert DeployKeysManager().plan(repo, desired) == []


def test_unlisted_deploy_key_is_deleted(repo: MagicMock) -> None:
    """A declared deploy_keys section is authoritative: an unlisted key is deleted."""
    existing = make_deploy_key(title="stale", key="ssh-ed25519 STALE...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA...", read_only=True)],
    )
    repo.get_keys.return_value = [existing]

    changes = DeployKeysManager().plan(repo, desired)

    # One CREATE for "ci" and one DELETE for the unlisted "stale".
    actions = {change.target: change.action for change in changes}
    assert actions == {"deploy_key:ci": Action.CREATE, "deploy_key:stale": Action.DELETE}
    delete = next(change for change in changes if change.action is Action.DELETE)
    delete.apply()
    existing.delete.assert_called_once_with()


def test_changed_title_for_same_key_is_delete_and_create_not_update(repo: MagicMock) -> None:
    """GitHub's deploy-key API has no update endpoint.

    When the same key content is kept but its title (or read_only flag) changes, the only
    way to represent that in the API is to delete the existing key and create a new one --
    never a single UPDATE, unlike every other manager in this codebase.
    """
    existing = make_deploy_key(title="old-name", key="ssh-ed25519 AAAA...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="new-name", key="ssh-ed25519 AAAA...", read_only=False)],
    )
    repo.get_keys.return_value = [existing]

    changes = DeployKeysManager().plan(repo, desired)

    assert len(changes) == 2
    assert {change.action for change in changes} == {Action.DELETE, Action.CREATE}
    assert all(change.action is not Action.UPDATE for change in changes)

    delete = next(change for change in changes if change.action is Action.DELETE)
    create = next(change for change in changes if change.action is Action.CREATE)
    assert delete.target == "deploy_key:old-name"
    assert create.target == "deploy_key:new-name"

    delete.apply()
    existing.delete.assert_called_once_with()
    create.apply()
    repo.create_key.assert_called_once_with("new-name", "ssh-ed25519 AAAA...", read_only=False)
