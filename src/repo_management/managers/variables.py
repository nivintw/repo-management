# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions variables.

Unlike secrets, variable values are readable, so an existing variable's value can be
diffed: it is updated only when the desired value actually differs. A declared
``variables`` section is authoritative — variables absent from the config are deleted.
Values are not sensitive and are shown in plain text in plans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository
    from github.Variable import Variable as GhVariable

    from repo_management.config import SharedConfig


class VariablesManager:
    """Reconcile Actions variables: a declared section is the authoritative, complete set."""

    domain = "variables"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, update, and delete variables to match the config."""
        if desired.variables is None:
            return []

        existing = {variable.name: variable for variable in repo.get_variables()}
        wanted = desired.variables
        changes: list[Change] = []

        for item in wanted:
            current = existing.get(item.name)
            value = item.resolve()
            if current is None:
                changes.append(self._create(repo, item.name, value))
            elif current.value != value:
                changes.append(self._update(current, value))

        wanted_names = {item.name for item in wanted}
        changes.extend(
            self._delete(variable)
            for name, variable in existing.items()
            if name not in wanted_names
        )
        return changes

    def _create(self, repo: Repository, name: str, value: str) -> Change:
        def apply() -> None:
            repo.create_variable(name, value)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"variable:{name}",
            before=None,
            after=value,
            apply=apply,
        )

    def _update(self, current: GhVariable, value: str) -> Change:
        def apply() -> None:
            current.edit(value)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=f"variable:{current.name}",
            before=current.value,
            after=value,
            apply=apply,
        )

    def _delete(self, variable: GhVariable) -> Change:
        def apply() -> None:
            variable.delete()

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"variable:{variable.name}",
            before=variable.value,
            after=None,
            apply=apply,
        )
