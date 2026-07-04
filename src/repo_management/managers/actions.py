# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions permissions and workflow permissions.

PyGithub doesn't model the Actions-permissions endpoints, so this manager drives them
directly through the authenticated requester, the same way ``RulesetsManager`` and
``SettingsManager``'s topics/workflow-permission handling do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import SelectedActions, SharedConfig


class ActionsManager:
    """Reconcile Actions enablement/policy and workflow permissions."""

    domain = "actions"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes for the permissions, selected-actions, and workflow-permission APIs."""
        actions = desired.actions
        if actions is None:
            return []

        changes: list[Change] = []
        permissions = self._partial_change(
            repo,
            target="permissions",
            url=f"{repo.url}/actions/permissions",
            wanted={"enabled": actions.enabled, "allowed_actions": actions.allowed_actions},
        )
        if permissions is not None:
            changes.append(permissions)
        if actions.selected_actions is not None:
            selected = self._selected_actions_change(repo, actions.selected_actions)
            if selected is not None:
                changes.append(selected)
        workflow = self._partial_change(
            repo,
            target="workflow permissions",
            url=f"{repo.url}/actions/permissions/workflow",
            wanted={
                "default_workflow_permissions": actions.default_workflow_permissions,
                "can_approve_pull_request_reviews": actions.can_approve_pull_request_reviews,
            },
        )
        if workflow is not None:
            changes.append(workflow)
        return changes

    def _partial_change(
        self, repo: Repository, *, target: str, url: str, wanted: dict[str, Any]
    ) -> Change | None:
        """Diff a subset of fields on a GET/PUT endpoint, preserving whichever are unmanaged.

        Shared by the permissions and workflow-permissions endpoints, which both expose a
        pair of fields the config may only partly manage; an omitted field is written back
        with its live value so the PUT doesn't clear it.
        """
        if all(want is None for want in wanted.values()):
            return None
        _, data = repo.requester.requestJsonAndCheck("GET", url)
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        payload: dict[str, Any] = {}
        for field, want in wanted.items():
            current = data.get(field)
            payload[field] = current if want is None else want
            if want is not None and current != want:
                before[field] = current
                after[field] = want
        if not after:
            return None

        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT", url, input=payload)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=target,
            before=before,
            after=after,
            apply=apply,
        )

    def _selected_actions_change(self, repo: Repository, want: SelectedActions) -> Change | None:
        url = f"{repo.url}/actions/permissions/selected-actions"
        _, data = repo.requester.requestJsonAndCheck("GET", url)
        wanted = want.model_dump()
        before = {field: data.get(field) for field in wanted}
        if before == wanted:
            return None

        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT", url, input=wanted)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="selected actions",
            before=before,
            after=wanted,
            apply=apply,
        )
