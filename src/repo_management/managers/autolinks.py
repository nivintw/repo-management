# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository autolink references.

GitHub's autolinks API has no update endpoint: it only supports create, list, and
delete. So unlike every other manager in this codebase, a changed ``url_template`` or
``is_alphanumeric`` for an existing ``key_prefix`` cannot be represented as a single
UPDATE change. Instead it is planned as a DELETE of the stale autolink followed by a
CREATE of the new one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Autolink import Autolink as GhAutolink
    from github.Repository import Repository

    from repo_management.config import Autolink, SharedConfig


class AutolinksManager:
    """Reconcile autolinks: a declared ``autolinks`` section is the authoritative, complete set."""

    domain = "autolinks"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create and delete autolinks to match the config."""
        if desired.autolinks is None:
            return []

        existing = {autolink.key_prefix: autolink for autolink in repo.get_autolinks()}
        wanted = desired.autolinks
        changes: list[Change] = []

        for item in wanted:
            current = existing.get(item.key_prefix)
            if current is None:
                changes.append(self._create(repo, item))
            elif _autolink_differs(current, item):
                changes.append(self._delete(repo, current))
                changes.append(self._create(repo, item))

        wanted_prefixes = {item.key_prefix for item in wanted}
        changes.extend(
            self._delete(repo, autolink)
            for prefix, autolink in existing.items()
            if prefix not in wanted_prefixes
        )

        return changes

    def _create(self, repo: Repository, item: Autolink) -> Change:
        def apply() -> None:
            repo.create_autolink(
                item.key_prefix, item.url_template, is_alphanumeric=item.is_alphanumeric
            )

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"autolink:{item.key_prefix}",
            before=None,
            after=_summary(item.url_template, is_alphanumeric=item.is_alphanumeric),
            apply=apply,
        )

    def _delete(self, repo: Repository, autolink: GhAutolink) -> Change:
        def apply() -> None:
            repo.remove_autolink(autolink.id)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"autolink:{autolink.key_prefix}",
            before=_summary(autolink.url_template, is_alphanumeric=autolink.is_alphanumeric),
            after=None,
            apply=apply,
        )


def _autolink_differs(current: GhAutolink, item: Autolink) -> bool:
    """Whether an autolink needs replacing, since there is no in-place update."""
    if current.url_template != item.url_template:
        return True
    return current.is_alphanumeric != item.is_alphanumeric


def _summary(url_template: str, *, is_alphanumeric: bool) -> dict[str, object]:
    return {"url_template": url_template, "is_alphanumeric": is_alphanumeric}
