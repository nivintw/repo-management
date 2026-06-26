# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository issue/PR labels."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from github import GithubObject

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Label import Label as GhLabel
    from github.Repository import Repository

    from repo_management.config import Label, SharedConfig


class LabelsManager:
    """Reconcile labels: a declared ``labels`` section is the authoritative, complete set."""

    domain = "labels"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, update, and delete labels to match the config."""
        if desired.labels is None:
            return []

        existing = {label.name: label for label in repo.get_labels()}
        wanted = desired.labels
        changes: list[Change] = []

        for item in wanted:
            current = existing.get(item.name)
            if current is None:
                changes.append(self._create(repo, item))
            elif _label_differs(current, item):
                changes.append(self._update(current, item))

        wanted_names = {item.name for item in wanted}
        changes.extend(
            self._delete(label) for name, label in existing.items() if name not in wanted_names
        )

        return changes

    def _create(self, repo: Repository, item: Label) -> Change:
        description = item.description if item.description is not None else GithubObject.NotSet

        def apply() -> None:
            repo.create_label(item.name, item.color, description=description)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"label:{item.name}",
            before=None,
            after=_summary(item.color, item.description),
            apply=apply,
        )

    def _update(self, current: GhLabel, item: Label) -> Change:
        description = item.description if item.description is not None else GithubObject.NotSet

        def apply() -> None:
            current.edit(item.name, item.color, description=description)

        # An unset description is unmanaged, so the after-state keeps the current value.
        after_description = (
            item.description if item.description is not None else current.description
        )
        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=f"label:{item.name}",
            before=_summary(current.color, current.description),
            after=_summary(item.color, after_description),
            apply=apply,
        )

    def _delete(self, label: GhLabel) -> Change:
        def apply() -> None:
            label.delete()

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"label:{label.name}",
            before=_summary(label.color, label.description),
            after=None,
            apply=apply,
        )


def _label_differs(current: GhLabel, item: Label) -> bool:
    """Whether a label needs updating. An unset description is left unmanaged."""
    if current.color != item.color:
        return True
    return item.description is not None and current.description != item.description


def _summary(color: str, description: str | None) -> dict[str, Any]:
    return {"color": color, "description": description}
