# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository settings, features, and merge options."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import RepoConfig, Settings


class SettingsManager:
    """Reconcile scalar repository settings and the topics list."""

    domain = "settings"

    def plan(self, repo: Repository, desired: RepoConfig) -> list[Change]:
        """Return at most one batched settings change plus a topics change."""
        settings = desired.settings
        if settings is None:
            return []

        changes: list[Change] = []
        edit = self._edit_change(repo, settings)
        if edit is not None:
            changes.append(edit)
        if settings.topics is not None:
            topics = self._topics_change(repo, settings.topics)
            if topics is not None:
                changes.append(topics)
        return changes

    def _edit_change(self, repo: Repository, settings: Settings) -> Change | None:
        # The Settings field names match both Repository attributes and Repository.edit
        # kwargs, so the set fields can be diffed and applied without a manual mapping.
        wanted: dict[str, Any] = settings.model_dump(exclude_none=True, exclude={"topics"})
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for field, want in wanted.items():
            current = getattr(repo, field, None)
            if current != want:
                before[field] = current
                after[field] = want
        if not after:
            return None

        def apply() -> None:
            repo.edit(**after)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="settings",
            before=before,
            after=after,
            apply=apply,
        )

    def _topics_change(self, repo: Repository, want: list[str]) -> Change | None:
        current = list(repo.get_topics())
        if sorted(current) == sorted(want):
            return None

        def apply() -> None:
            repo.replace_topics(want)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="topics",
            before=sorted(current),
            after=sorted(want),
            apply=apply,
        )
