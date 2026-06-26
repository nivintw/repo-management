# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository collaborators.

This manager is additive: it adds collaborators and updates their permission level, but
does not remove collaborators absent from the config (removing access is destructive and
left as an explicit, manual action).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import Collaborator, RepoConfig

# GitHub's permission API reports read/write; the config (and add API) use pull/push.
_API_TO_CONFIG = {"read": "pull", "write": "push"}
_NONE = "none"


class CollaboratorsManager:
    """Add collaborators and reconcile their permission levels."""

    domain = "collaborators"

    def plan(self, repo: Repository, desired: RepoConfig) -> list[Change]:
        """Return a change per collaborator that must be added or have permission changed."""
        if desired.collaborators is None:
            return []

        changes: list[Change] = []
        for collaborator in desired.collaborators:
            change = self._collaborator_change(repo, collaborator)
            if change is not None:
                changes.append(change)
        return changes

    def _collaborator_change(
        self,
        repo: Repository,
        collaborator: Collaborator,
    ) -> Change | None:
        raw = repo.get_collaborator_permission(collaborator.username)
        current = _API_TO_CONFIG.get(raw, raw)
        want = collaborator.permission
        if current == want:
            return None

        def apply() -> None:
            repo.add_to_collaborators(collaborator.username, want)

        is_new = current == _NONE
        return Change(
            domain=self.domain,
            action=Action.CREATE if is_new else Action.UPDATE,
            target=f"collaborator:{collaborator.username}",
            before=None if is_new else current,
            after=want,
            apply=apply,
        )
