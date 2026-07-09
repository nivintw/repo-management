# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the secrets manager."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from conftest import make_secret

from repo_management.changes import Action
from repo_management.config import Secret, SharedConfig
from repo_management.managers.secrets import SecretsManager

_OLD = datetime(2026, 1, 1, tzinfo=UTC)
_NEW = datetime(2026, 6, 1, tzinfo=UTC)


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


def test_source_newer_than_target_repushes(
    repo: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source secret updated more recently than the target is re-pushed (rotation propagates)."""
    monkeypatch.setenv("TOKEN_SRC", "rotated-value")
    repo.get_secrets.return_value = [make_secret("TOKEN", updated_at=_OLD)]
    desired = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="TOKEN_SRC")])

    changes = SecretsManager(source_secrets={"TOKEN_SRC": _NEW}).plan(repo, desired)

    assert [c.action for c in changes] == [Action.UPDATE]
    changes[0].apply()
    repo.create_secret.assert_called_once_with("TOKEN", "rotated-value")


def test_force_overrides_a_source_older_than_target(
    repo: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force wins over the timestamp verdict: an older source is still re-pushed under force.

    plan_config always threads source_secrets (possibly {}), so force and the timestamp policy
    coexist on the real --force-secrets path — pin that force takes precedence.
    """
    monkeypatch.setenv("TOKEN_SRC", "v")
    repo.get_secrets.return_value = [make_secret("TOKEN", updated_at=_NEW)]  # target NEWER
    desired = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="TOKEN_SRC")])

    changes = SecretsManager(force=True, source_secrets={"TOKEN_SRC": _OLD}).plan(repo, desired)

    assert [c.action for c in changes] == [Action.UPDATE]


def test_mixed_batch_resolves_each_secret_independently(
    repo: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One plan call with re-push + skip + create secrets resolves each on its own merits."""
    monkeypatch.setenv("FRESH_SRC", "v")  # only the re-pushed and created secrets resolve
    monkeypatch.setenv("NEW_SRC", "v")
    repo.get_secrets.return_value = [
        make_secret("FRESH", updated_at=_OLD),  # source newer -> UPDATE
        make_secret("STALE", updated_at=_NEW),  # source older -> skip
    ]
    desired = SharedConfig(
        secrets=[
            Secret(name="FRESH", value_from_env="FRESH_SRC"),
            Secret(name="STALE", value_from_env="STALE_SRC"),
            Secret(name="NEW", value_from_env="NEW_SRC"),  # absent target -> CREATE
        ]
    )

    changes = SecretsManager(
        source_secrets={"FRESH_SRC": _NEW, "STALE_SRC": _OLD, "NEW_SRC": _NEW}
    ).plan(repo, desired)

    assert {c.target: c.action for c in changes} == {
        "secret:FRESH": Action.UPDATE,
        "secret:NEW": Action.CREATE,
    }


def test_source_not_newer_than_target_is_skipped(repo: MagicMock) -> None:
    """A target at least as new as its source is left untouched — our workflow already set it."""
    repo.get_secrets.return_value = [make_secret("TOKEN", updated_at=_NEW)]
    desired = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="TOKEN_SRC")])

    # Older source, and the equal-timestamp boundary, both skip (comparison is strictly newer).
    assert SecretsManager(source_secrets={"TOKEN_SRC": _OLD}).plan(repo, desired) == []
    assert SecretsManager(source_secrets={"TOKEN_SRC": _NEW}).plan(repo, desired) == []


def test_source_without_timestamp_is_skipped(repo: MagicMock) -> None:
    """A secret whose source carries no timestamp keeps the write-only skip-if-exists default."""
    repo.get_secrets.return_value = [make_secret("TOKEN", updated_at=_OLD)]
    # value_from_env not present in the source map, and an inline-value secret with no source.
    from_env = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="MISSING_SRC")])
    inline = SharedConfig(secrets=[Secret(name="TOKEN", value="literal")])

    assert SecretsManager(source_secrets={"OTHER": _NEW}).plan(repo, from_env) == []
    assert SecretsManager(source_secrets={"TOKEN": _NEW}).plan(repo, inline) == []


def test_target_without_timestamp_is_skipped(repo: MagicMock) -> None:
    """A target secret with no updated_at can't be dated, so it's left untouched, not re-pushed."""
    repo.get_secrets.return_value = [make_secret("TOKEN", updated_at=None)]
    desired = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="TOKEN_SRC")])

    assert SecretsManager(source_secrets={"TOKEN_SRC": _NEW}).plan(repo, desired) == []


def test_container_secret_without_updated_at_attr_degrades(repo: MagicMock) -> None:
    """A container whose secrets lack updated_at entirely reads as undatable, not AttributeError.

    The SecretsContainer protocol only promises a name; plan_secrets reads updated_at via getattr
    so a container that doesn't expose it (or a future/mock one) degrades to skip-if-exists.
    """
    repo.get_secrets.return_value = [SimpleNamespace(name="TOKEN")]  # no updated_at attribute
    desired = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="TOKEN_SRC")])

    assert SecretsManager(source_secrets={"TOKEN_SRC": _NEW}).plan(repo, desired) == []


def test_absent_secret_creates_regardless_of_source(
    repo: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent target is still created even when a (newer) source timestamp exists."""
    monkeypatch.setenv("TOKEN_SRC", "value")
    repo.get_secrets.return_value = []
    desired = SharedConfig(secrets=[Secret(name="TOKEN", value_from_env="TOKEN_SRC")])

    changes = SecretsManager(source_secrets={"TOKEN_SRC": _NEW}).plan(repo, desired)

    assert [c.action for c in changes] == [Action.CREATE]


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
