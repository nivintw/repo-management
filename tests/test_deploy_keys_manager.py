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


def test_create_strips_ambient_whitespace(repo: MagicMock) -> None:
    """A YAML block scalar's trailing newline is stripped before the API call.

    Matching tolerates it (see test_matching_ignores_trailing_comment), but GitHub's
    create-key endpoint must not receive it.
    """
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA... deploy@ci\n", read_only=True)],
    )
    repo.get_keys.return_value = []

    changes = DeployKeysManager().plan(repo, desired)

    changes[0].apply()
    repo.create_key.assert_called_once_with("ci", "ssh-ed25519 AAAA... deploy@ci", read_only=True)


def test_existing_deploy_key_matches_exactly(repo: MagicMock) -> None:
    """An existing deploy key that matches exactly yields no change."""
    existing = make_deploy_key(title="ci", key="ssh-ed25519 AAAA...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA...", read_only=True)],
    )
    repo.get_keys.return_value = [existing]

    assert DeployKeysManager().plan(repo, desired) == []


def test_matching_ignores_trailing_comment(repo: MagicMock) -> None:
    """A key differing only by an ssh-keygen-style comment is not spuriously recreated.

    GitHub's stored key may or may not echo back a submitted comment; matching on the
    algorithm+body only keeps identity stable either way, since ssh-keygen's default
    output always appends one.
    """
    existing = make_deploy_key(title="ci", key="ssh-ed25519 AAAA...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA... deploy@ci", read_only=True)],
    )
    repo.get_keys.return_value = [existing]

    assert DeployKeysManager().plan(repo, desired) == []


def test_unlisted_deploy_key_is_left_alone_by_default(repo: MagicMock) -> None:
    """deploy_keys_mode defaults to add-only: a key added out-of-band is not deleted."""
    existing = make_deploy_key(title="stale", key="ssh-ed25519 STALE...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA...", read_only=True)],
    )
    repo.get_keys.return_value = [existing]

    changes = DeployKeysManager().plan(repo, desired)

    # Only the CREATE for the listed key; "stale" is untouched.
    assert {change.target: change.action for change in changes} == {"deploy_key:ci": Action.CREATE}
    existing.delete.assert_not_called()


def test_unlisted_deploy_key_is_deleted_when_authoritative(repo: MagicMock) -> None:
    """deploy_keys_mode=authoritative restores the complete-set behaviour."""
    existing = make_deploy_key(title="stale", key="ssh-ed25519 STALE...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="ci", key="ssh-ed25519 AAAA...", read_only=True)],
        deploy_keys_mode="authoritative",
    )
    repo.get_keys.return_value = [existing]

    changes = DeployKeysManager().plan(repo, desired)

    # One CREATE for "ci" and one DELETE for the unlisted "stale".
    actions = {change.target: change.action for change in changes}
    assert actions == {"deploy_key:ci": Action.CREATE, "deploy_key:stale": Action.DELETE}
    delete = next(change for change in changes if change.action is Action.DELETE)
    delete.apply()
    existing.delete.assert_called_once_with()


def test_listed_key_still_delete_recreates_under_add_only(repo: MagicMock) -> None:
    """THE trap this whole change had to avoid.

    This manager emits DELETE for two unrelated reasons: pruning an unlisted key, and expressing
    an update to a LISTED key (GitHub has no deploy-key update endpoint, so a title/read_only
    change is a delete plus a create). Add-only gates only the first. Gating deletes wholesale
    would leave listed keys silently unable to converge on title/read_only — the config would
    claim a state the repo never reaches, forever, with no error.
    """
    existing = make_deploy_key(title="old-name", key="ssh-ed25519 AAAA...", read_only=True)
    desired = SharedConfig(
        deploy_keys=[DeployKey(title="new-name", key="ssh-ed25519 AAAA...", read_only=True)],
    )
    repo.get_keys.return_value = [existing]

    changes = DeployKeysManager().plan(repo, desired)

    # Same key content, changed title: the pair must survive add-only.
    assert [change.action for change in changes] == [Action.DELETE, Action.CREATE]
    assert [change.target for change in changes] == [
        "deploy_key:old-name",
        "deploy_key:new-name",
    ]


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
