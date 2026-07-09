# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Shared secret/variable diff helpers.

Reused by ``SecretsManager``, ``VariablesManager``, and ``EnvironmentsManager``. A
repository and a GitHub ``Environment`` both expose the identical
``get_secrets``/``create_secret``/``delete_secret``/``get_variables``/``create_variable``
method names, so the diff logic is written once against that shared shape (``container``
below) and reused for both repo-scoped and environment-scoped sections instead of being
duplicated per call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from github.Variable import Variable as GhVariable

    from repo_management.config import Secret, Variable


@dataclass(frozen=True)
class SecretsPolicy:
    """When to re-push an *existing* secret whose value can't be read back to diff.

    - ``force`` re-pushes every declared secret unconditionally (rotation).
    - ``source_secrets`` — a ``{source-secret-name: updated_at}`` map from the source repo (see
      :func:`repo_management.client.source_secret_timestamps`) — re-pushes only the secrets
      whose source changed more recently than the target's own ``updated_at``. A secret that
      can't be dated on both sides (an inline ``value``, a source with no known timestamp, or a
      target with no ``updated_at``) is left alone even here.

    The default (neither set) is the write-only skip-if-exists policy: leave existing secrets
    alone.
    """

    force: bool = False
    source_secrets: Mapping[str, datetime] | None = None


class SecretsContainer(Protocol):
    """Anything exposing the secret operations used here — a ``Repository`` or ``Environment``."""

    def get_secrets(self) -> Iterable[Any]: ...
    def create_secret(self, secret_name: str, unencrypted_value: str) -> object: ...
    def delete_secret(self, secret_name: str) -> object: ...


class VariablesContainer(Protocol):
    """Anything exposing the variable operations used here — a ``Repository`` or ``Environment``."""

    def get_variables(self) -> Iterable[Any]: ...
    def create_variable(self, variable_name: str, value: str) -> object: ...


def plan_secrets(
    container: SecretsContainer,
    desired: list[Secret],
    *,
    domain: str,
    target_prefix: str = "",
    policy: SecretsPolicy | None = None,
) -> list[Change]:
    """Diff ``desired`` secrets against ``container.get_secrets()``.

    Values are write-only, so an existing secret is normally left untouched — re-pushing it
    every apply is pure churn. The list is authoritative: anything absent from ``desired`` is
    deleted. ``policy`` (see :class:`SecretsPolicy`, default skip-if-exists) decides when an
    *existing* secret is re-pushed anyway.
    """
    policy = policy or SecretsPolicy()
    existing = {secret.name: secret.updated_at for secret in container.get_secrets()}
    changes: list[Change] = []
    for secret in desired:
        if secret.name not in existing:
            changes.append(_upsert_secret(container, secret, domain, target_prefix, exists=False))
        elif policy.force or _source_is_newer(secret, existing[secret.name], policy.source_secrets):
            changes.append(_upsert_secret(container, secret, domain, target_prefix, exists=True))

    wanted = {secret.name for secret in desired}
    changes.extend(
        _delete_secret(container, name, domain, target_prefix)
        for name in existing
        if name not in wanted
    )
    return changes


def _source_is_newer(
    secret: Secret,
    target_updated: datetime | None,
    source_secrets: Mapping[str, datetime] | None,
) -> bool:
    """Whether ``secret``'s source changed more recently than the target's last write.

    True only when both sides are datable: a ``source_secrets`` map is provided, the secret is
    sourced from an env var whose source-repo secret we hold a timestamp for, and the target
    carries an ``updated_at`` the source is strictly newer than. Any missing piece is False —
    the write-only skip-if-exists default: never re-push a secret we can't prove is stale.
    """
    if not source_secrets or secret.value_from_env is None or target_updated is None:
        return False
    # Keyed by the env-var name because that's the source secret's own name (the workflow
    # authors `FOO: ${{ secrets.FOO }}`); a divergent mapping simply misses and skips.
    source_updated = source_secrets.get(secret.value_from_env)
    # Strictly newer, deliberately: a push restamps the target to now, so a later run sees
    # source <= target and converges (no re-push loop). It also makes a repo that is its own
    # source idempotent (equal timestamps skip). The cost is a ~1s window — GitHub dates
    # secrets to the second — where a rotation in the same second as the last write is missed
    # until the source is touched again; that's the safe direction (leave-in-place, not clobber).
    return source_updated is not None and source_updated > target_updated


def _delete_secret(
    container: SecretsContainer, name: str, domain: str, target_prefix: str
) -> Change:
    def apply() -> None:
        container.delete_secret(name)

    return Change(
        domain=domain,
        action=Action.DELETE,
        target=f"{target_prefix}secret:{name}",
        before="(exists)",
        after=None,
        apply=apply,
    )


def _upsert_secret(
    container: SecretsContainer, secret: Secret, domain: str, target_prefix: str, *, exists: bool
) -> Change:
    value = secret.resolve()

    def apply() -> None:
        container.create_secret(secret.name, value)

    return Change(
        domain=domain,
        action=Action.UPDATE if exists else Action.CREATE,
        target=f"{target_prefix}secret:{secret.name}",
        before="(exists)" if exists else None,
        after="(set)",
        apply=apply,
        secret=True,
    )


def plan_variables(
    container: VariablesContainer,
    desired: list[Variable],
    *,
    domain: str,
    target_prefix: str = "",
) -> list[Change]:
    """Diff ``desired`` variables against ``container.get_variables()``.

    Mirrors :class:`~repo_management.managers.variables.VariablesManager`'s policy: values are
    readable, so an existing variable is updated only when its value actually differs, and the
    list is authoritative — anything absent is deleted.
    """
    existing = {variable.name: variable for variable in container.get_variables()}
    changes: list[Change] = []

    for item in desired:
        current = existing.get(item.name)
        value = item.resolve()
        if current is None:
            changes.append(_create_variable(container, item.name, value, domain, target_prefix))
        elif current.value != value:
            changes.append(_update_variable(current, value, domain, target_prefix))

    wanted_names = {item.name for item in desired}
    changes.extend(
        _delete_variable(variable, domain, target_prefix)
        for name, variable in existing.items()
        if name not in wanted_names
    )
    return changes


def _create_variable(
    container: VariablesContainer, name: str, value: str, domain: str, target_prefix: str
) -> Change:
    def apply() -> None:
        container.create_variable(name, value)

    return Change(
        domain=domain,
        action=Action.CREATE,
        target=f"{target_prefix}variable:{name}",
        before=None,
        after=value,
        apply=apply,
    )


def _update_variable(current: GhVariable, value: str, domain: str, target_prefix: str) -> Change:
    def apply() -> None:
        current.edit(value)

    return Change(
        domain=domain,
        action=Action.UPDATE,
        target=f"{target_prefix}variable:{current.name}",
        before=current.value,
        after=value,
        apply=apply,
    )


def _delete_variable(variable: GhVariable, domain: str, target_prefix: str) -> Change:
    def apply() -> None:
        variable.delete()

    return Change(
        domain=domain,
        action=Action.DELETE,
        target=f"{target_prefix}variable:{variable.name}",
        before=variable.value,
        after=None,
        apply=apply,
    )
