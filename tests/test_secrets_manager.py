# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the secrets manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_secret

from repo_management.changes import Action
from repo_management.config import Secret, SharedConfig
from repo_management.managers.secrets import SecretsManager


def test_no_secrets_is_noop(repo: MagicMock) -> None:
    """A repo config without a secrets section yields no changes."""
    desired = SharedConfig()
    assert SecretsManager().plan(repo, desired) == []


def test_new_secret_produces_create(repo: MagicMock) -> None:
    """A secret not in get_secrets() yields one create change with redacted values."""
    repo.get_secrets.return_value = []
    desired = SharedConfig(secrets=[Secret(name="NEW_SECRET", value="literalvalue")])

    changes = SecretsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "secret:NEW_SECRET"
    assert (change.before, change.after) == (None, "(set)")
    assert change.secret is True
    change.apply()
    repo.create_secret.assert_called_once_with("NEW_SECRET", "literalvalue")
    assert "literalvalue" not in change.describe()


def test_existing_secret_is_skipped(repo: MagicMock) -> None:
    """A secret already present is left untouched by default — no churn, no resolve."""
    repo.get_secrets.return_value = [make_secret("EXISTING_SECRET")]
    # A value_from_env source whose env var is unset would raise if resolved — proving the
    # skipped secret is never resolved.
    desired = SharedConfig(secrets=[Secret(name="EXISTING_SECRET", value_from_env="UNSET_VAR")])

    assert SecretsManager().plan(repo, desired) == []


def test_force_repushes_existing_secret(repo: MagicMock) -> None:
    """force=True re-pushes an existing secret as an update (for rotation)."""
    repo.get_secrets.return_value = [make_secret("EXISTING_SECRET")]
    desired = SharedConfig(secrets=[Secret(name="EXISTING_SECRET", value="literalvalue")])

    changes = SecretsManager(force=True).plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert (change.before, change.after) == ("(exists)", "(set)")
    assert change.secret is True
    change.apply()
    repo.create_secret.assert_called_once_with("EXISTING_SECRET", "literalvalue")
    assert "literalvalue" not in change.describe()


def test_unlisted_secret_is_deleted(repo: MagicMock) -> None:
    """A declared secrets section is authoritative: a secret absent from it is deleted."""
    repo.get_secrets.return_value = [make_secret("STALE_SECRET")]
    desired = SharedConfig(secrets=[Secret(name="WANTED", value="v")])

    changes = SecretsManager().plan(repo, desired)

    actions = {change.target: change.action for change in changes}
    assert actions == {"secret:WANTED": Action.CREATE, "secret:STALE_SECRET": Action.DELETE}
    delete = next(change for change in changes if change.action is Action.DELETE)
    assert (delete.before, delete.after) == ("(exists)", None)
    delete.apply()
    repo.delete_secret.assert_called_once_with("STALE_SECRET")
