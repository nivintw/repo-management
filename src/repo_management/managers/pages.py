# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for GitHub Pages configuration.

PyGithub doesn't model the Pages-configuration endpoint, so this manager drives it directly
through the authenticated requester, the same way ``RulesetsManager``/``ActionsManager`` do.

A ``pages`` section left unset is unmanaged, consistent with every other manager. A declared
section with ``enabled: true`` (the default) is created if absent and updated if it differs;
``enabled: false`` disables Pages if it's currently on. GitHub's create endpoint only accepts
``build_type``/``source`` — ``cname``/``https_enforced`` are update-only, so creating a site
with those already set takes a POST followed immediately by a PUT, both inside one Change's
``apply``.
"""

from __future__ import annotations

import warnings
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from github import GithubException

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import Pages, SharedConfig


class PagesManager:
    """Reconcile GitHub Pages configuration: create, update, or disable to match the config."""

    domain = "pages"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return at most one change to create, update, or disable Pages."""
        pages = desired.pages
        if pages is None:
            return []

        url = f"{repo.url}/pages"
        try:
            current = self._get(repo, url)
        except GithubException as exc:
            if exc.status == HTTPStatus.FORBIDDEN:
                # The Pages permission is granted separately from repo administration, so a
                # token without it 403s on this read. Degrade to skip-with-warning rather
                # than let the 403 abort every other domain's reconciliation for this repo
                # (the reconciler runs each manager's plan() in a bare loop). Any other
                # status still surfaces.
                warnings.warn(
                    f"skipping Pages for {repo.full_name}: read returned 403 (token lacks "
                    "the Pages permission); every other domain still reconciles",
                    stacklevel=2,
                )
                return []
            raise

        if not pages.enabled:
            return [] if current is None else [self._disable(repo, url, current)]
        if current is None:
            return [self._create(repo, url, pages)]

        fields = _wanted_fields(pages)
        if all(current.get(field) == value for field, value in fields.items()):
            return []
        return [self._update(repo, url, fields, current)]

    def _get(self, repo: Repository, url: str) -> dict[str, Any] | None:
        try:
            _, data = repo.requester.requestJsonAndCheck("GET", url)
        except GithubException as exc:
            if exc.status == HTTPStatus.NOT_FOUND:
                return None
            raise
        return data

    def _create(self, repo: Repository, url: str, pages: Pages) -> Change:
        fields = _wanted_fields(pages)
        create_body = {key: fields[key] for key in ("build_type", "source") if key in fields}
        follow_up = {key: value for key, value in fields.items() if key not in create_body}

        def apply() -> None:
            repo.requester.requestJsonAndCheck("POST", url, input=create_body)
            if follow_up:
                repo.requester.requestJsonAndCheck("PUT", url, input=follow_up)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target="pages",
            before=None,
            after=fields,
            apply=apply,
        )

    def _update(
        self, repo: Repository, url: str, fields: dict[str, Any], current: dict[str, Any]
    ) -> Change:
        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT", url, input=fields)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="pages",
            before={field: current.get(field) for field in fields},
            after=fields,
            apply=apply,
        )

    def _disable(self, repo: Repository, url: str, current: dict[str, Any]) -> Change:
        def apply() -> None:
            repo.requester.requestJsonAndCheck("DELETE", url)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target="pages",
            before=_summary(current),
            after=None,
            apply=apply,
        )


def _wanted_fields(pages: Pages) -> dict[str, Any]:
    fields: dict[str, Any] = {"build_type": pages.build_type}
    if pages.source is not None:
        fields["source"] = {"branch": pages.source.branch, "path": pages.source.path}
    if pages.cname is not None:
        fields["cname"] = pages.cname
    if pages.https_enforced is not None:
        fields["https_enforced"] = pages.https_enforced
    return fields


def _summary(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "build_type": current.get("build_type"),
        "source": current.get("source"),
        "cname": current.get("cname"),
        "https_enforced": current.get("https_enforced"),
    }
