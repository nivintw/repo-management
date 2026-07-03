# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository settings, features, merge options, and workflow permissions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import Settings, SharedConfig

# Settings fields that are not Repository.edit kwargs and get their own API calls.
_SPECIAL_FIELDS = {"topics", "can_approve_pull_request_reviews"}


class SettingsManager:
    """Reconcile scalar repository settings, the topics list, and workflow permissions."""

    domain = "settings"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return at most one batched settings change plus topics/workflow-permission changes."""
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
        if settings.can_approve_pull_request_reviews is not None:
            permissions = self._workflow_permissions_change(
                repo, want=settings.can_approve_pull_request_reviews
            )
            if permissions is not None:
                changes.append(permissions)
        return changes

    def _edit_change(self, repo: Repository, settings: Settings) -> Change | None:
        # The remaining Settings field names match both Repository attributes and
        # Repository.edit kwargs, so the set fields can be diffed and applied without a
        # manual mapping.
        wanted: dict[str, Any] = settings.model_dump(exclude_none=True, exclude=_SPECIAL_FIELDS)
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

    def _workflow_permissions_change(self, repo: Repository, *, want: bool) -> Change | None:
        # "Allow GitHub Actions to create and approve pull requests" lives on the Actions
        # workflow-permissions endpoint, which PyGithub doesn't model — drive it through
        # the authenticated requester like the rulesets manager does. The PUT writes back
        # the live default_workflow_permissions alongside the managed field: GitHub's docs
        # don't promise an omitted param is preserved, and this pins it either way without
        # managing it.
        url = f"{repo.url}/actions/permissions/workflow"
        _, data = repo.requester.requestJsonAndCheck("GET", url)
        current = data.get("can_approve_pull_request_reviews")
        if current == want:
            return None
        default_permissions = data.get("default_workflow_permissions")

        def apply() -> None:
            repo.requester.requestJsonAndCheck(
                "PUT",
                url,
                input={
                    "default_workflow_permissions": default_permissions,
                    "can_approve_pull_request_reviews": want,
                },
            )

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="workflow permissions",
            before={"can_approve_pull_request_reviews": current},
            after={"can_approve_pull_request_reviews": want},
            apply=apply,
        )
