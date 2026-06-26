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

    from repo_management.config import Collaborator, SharedConfig

# GitHub's role name reports read/write; the config (and add API) use pull/push.
# triage/maintain/admin are reported verbatim.
_API_TO_CONFIG = {"read": "pull", "write": "push"}
_NONE = "none"


class CollaboratorsManager:
    """Add collaborators and reconcile their permission levels."""

    domain = "collaborators"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
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
        # The legacy permission field collapses maintain->write and triage->read, which
        # would never converge for those roles; role_name reports the granular role. A
        # non-collaborator reports permission "none".
        if repo.get_collaborator_permission(collaborator.username) == _NONE:
            current = _NONE
        else:
            role = repo.get_collaborator_role_name(collaborator.username)
            current = _API_TO_CONFIG.get(role, role)
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
