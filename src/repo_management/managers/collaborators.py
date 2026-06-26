# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository collaborators.

A declared ``collaborators`` section is authoritative: collaborators are added and have
their permission reconciled, and *direct* collaborators absent from the config are removed.
Only directly-granted access is managed — access inherited from org/team membership is not
listed and so is never touched.
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
    """Add, update, and remove direct collaborators to match the config."""

    domain = "collaborators"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to add, re-permission, and remove collaborators to match config."""
        if desired.collaborators is None:
            return []

        changes: list[Change] = []
        for collaborator in desired.collaborators:
            change = self._collaborator_change(repo, collaborator)
            if change is not None:
                changes.append(change)

        wanted = {collaborator.username for collaborator in desired.collaborators}
        # affiliation="direct" excludes access inherited via org/team membership, which the
        # repo collaborator API can't revoke anyway.
        changes.extend(
            self._remove(repo, user.login)
            for user in repo.get_collaborators(affiliation="direct")
            if user.login not in wanted
        )
        return changes

    def _remove(self, repo: Repository, username: str) -> Change:
        def apply() -> None:
            repo.remove_from_collaborators(username)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"collaborator:{username}",
            before=username,
            after=None,
            apply=apply,
        )

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
