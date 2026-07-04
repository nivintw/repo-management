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

from typing import TYPE_CHECKING, Any, Protocol

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from collections.abc import Iterable

    from github.Variable import Variable as GhVariable

    from repo_management.config import Secret, Variable


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
    force: bool = False,
) -> list[Change]:
    """Diff ``desired`` secrets against ``container.get_secrets()``.

    Mirrors :class:`~repo_management.managers.secrets.SecretsManager`'s policy: an existing
    secret is left untouched unless ``force`` is set (values are write-only, so we can't tell
    whether it's current), and the list is authoritative — anything absent is deleted.
    """
    existing = {secret.name for secret in container.get_secrets()}
    changes = [
        _upsert_secret(container, secret, domain, target_prefix, exists=secret.name in existing)
        for secret in desired
        if force or secret.name not in existing
    ]

    wanted = {secret.name for secret in desired}
    changes.extend(
        _delete_secret(container, name, domain, target_prefix)
        for name in existing
        if name not in wanted
    )
    return changes


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
