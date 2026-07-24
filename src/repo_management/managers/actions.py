# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions permissions and workflow permissions.

PyGithub doesn't model the Actions-permissions endpoints, so this manager drives them
directly through the authenticated requester, the same way ``RulesetsManager`` does.
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
        """Return changes across the seven Actions settings endpoints this manager reconciles.

        Each endpoint is diffed independently, and an endpoint whose config fields are all
        unset is skipped without a GET (see :meth:`_partial_change`).
        """
        actions = desired.actions
        if actions is None:
            return []

        fork_private = actions.fork_pr_workflows_private_repos
        candidates = [
            self._partial_change(
                repo,
                target="permissions",
                url=f"{repo.url}/actions/permissions",
                wanted={
                    "enabled": actions.enabled,
                    "allowed_actions": actions.allowed_actions,
                    "sha_pinning_required": actions.sha_pinning_required,
                },
            ),
            self._selected_actions_change(repo, actions.selected_actions)
            if actions.selected_actions is not None
            else None,
            self._partial_change(
                repo,
                target="workflow permissions",
                url=f"{repo.url}/actions/permissions/workflow",
                wanted={
                    "default_workflow_permissions": actions.default_workflow_permissions,
                    "can_approve_pull_request_reviews": actions.can_approve_pull_request_reviews,
                },
            ),
            self._partial_change(
                repo,
                target="external access",
                url=f"{repo.url}/actions/permissions/access",
                wanted={"access_level": actions.access_level},
            ),
            self._partial_change(
                repo,
                target="artifact and log retention",
                url=f"{repo.url}/actions/permissions/artifact-and-log-retention",
                wanted={"days": actions.artifact_and_log_retention_days},
            ),
            self._partial_change(
                repo,
                target="fork PR contributor approval",
                url=f"{repo.url}/actions/permissions/fork-pr-contributor-approval",
                wanted={"approval_policy": actions.fork_pr_contributor_approval},
            ),
            # The sub-model's field names match the API payload keys exactly, so a plain dump
            # is the wanted dict; a `None` field is unmanaged and written back by _partial_change.
            self._partial_change(
                repo,
                target="fork PR workflows (private repos)",
                url=f"{repo.url}/actions/permissions/fork-pr-workflows-private-repos",
                wanted=fork_private.model_dump(),
            )
            if fork_private is not None
            else None,
        ]
        return [change for change in candidates if change is not None]

    def _partial_change(
        self, repo: Repository, *, target: str, url: str, wanted: dict[str, Any]
    ) -> Change | None:
        """Diff a subset of fields on a GET/PUT endpoint, preserving whichever are unmanaged.

        Shared by the permissions and workflow-permissions endpoints, which both expose a
        pair of fields the config may only partly manage; an omitted field is written back
        with its live value so the PUT doesn't clear it — unless the GET itself omitted
        that value, in which case it's dropped from the payload rather than sent as null.
        """
        if all(want is None for want in wanted.values()):
            return None
        _, data = repo.requester.requestJsonAndCheck("GET", url)
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        payload: dict[str, Any] = {}
        for field, want in wanted.items():
            current = data.get(field)
            if want is None:
                if current is not None:
                    payload[field] = current
                continue
            payload[field] = want
            if current != want:
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
