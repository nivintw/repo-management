# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository settings, features, and merge options."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import RepoConfig

# Config fields that map one-to-one onto Repository attributes and Repository.edit kwargs.
_DIRECT_FIELDS = (
    "description",
    "homepage",
    "private",
    "has_issues",
    "has_wiki",
    "has_projects",
    "has_discussions",
    "default_branch",
    "allow_squash_merge",
    "allow_merge_commit",
    "allow_rebase_merge",
    "allow_auto_merge",
    "delete_branch_on_merge",
    "allow_update_branch",
)


class SettingsManager:
    """Reconcile scalar repository settings and the topics list."""

    domain = "settings"

    def plan(self, repo: Repository, desired: RepoConfig) -> list[Change]:
        """Return one change per setting that differs from the live repository."""
        settings = desired.settings
        if settings is None:
            return []

        changes: list[Change] = []
        for field in _DIRECT_FIELDS:
            want = getattr(settings, field)
            if want is None:
                continue
            current = getattr(repo, field, None)
            if current != want:
                changes.append(self._edit_change(repo, field, current, want))

        if settings.topics is not None:
            change = self._topics_change(repo, settings.topics)
            if change is not None:
                changes.append(change)

        return changes

    def _edit_change(
        self,
        repo: Repository,
        field: str,
        current: object,
        want: object,
    ) -> Change:
        def apply(field: str = field, want: object = want) -> None:
            # The field is chosen dynamically, so the value type can't be narrowed here.
            kwargs: dict[str, Any] = {field: want}
            repo.edit(**kwargs)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=field,
            before=current,
            after=want,
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
