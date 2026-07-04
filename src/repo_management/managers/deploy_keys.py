# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository deploy keys.

A declared ``deploy_keys`` section is the authoritative, complete set: a key present on
the repo but absent from the section is deleted. The natural key for the diff is the
key's content (the ``key`` field), not its ``title`` -- GitHub allows duplicate titles,
but key content is the real identity of a deploy key.

GitHub's deploy-key API has no update endpoint, and PyGithub's ``RepositoryKey.update()``
is only a conditional-GET refresh, not a REST PATCH. So unlike every other manager in this
codebase, an in-place edit cannot be expressed as a single UPDATE change: when a key's
``title`` or ``read_only`` flag differs for the same ``key`` content, this manager instead
emits a DELETE of the existing key paired with a CREATE of the desired one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository
    from github.RepositoryKey import RepositoryKey

    from repo_management.config import DeployKey, SharedConfig


class DeployKeysManager:
    """Reconcile deploy keys: a declared ``deploy_keys`` section is authoritative and complete."""

    domain = "deploy_keys"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, delete, and delete+recreate deploy keys to match the config."""
        if desired.deploy_keys is None:
            return []

        existing = {key.key: key for key in repo.get_keys()}
        wanted = desired.deploy_keys
        changes: list[Change] = []

        for item in wanted:
            current = existing.get(item.key)
            if current is None:
                changes.append(self._create(repo, item))
            elif _deploy_key_differs(current, item):
                changes.append(self._delete(current))
                changes.append(self._create(repo, item))

        wanted_keys = {item.key for item in wanted}
        changes.extend(
            self._delete(key) for content, key in existing.items() if content not in wanted_keys
        )

        return changes

    def _create(self, repo: Repository, item: DeployKey) -> Change:
        def apply() -> None:
            repo.create_key(item.title, item.key, read_only=item.read_only)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"deploy_key:{item.title}",
            before=None,
            after=_summary(item.title, read_only=item.read_only),
            apply=apply,
        )

    def _delete(self, key: RepositoryKey) -> Change:
        def apply() -> None:
            key.delete()

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"deploy_key:{key.title}",
            before=_summary(key.title, read_only=key.read_only),
            after=None,
            apply=apply,
        )


def _deploy_key_differs(current: RepositoryKey, item: DeployKey) -> bool:
    """Whether the same-content key needs a delete+recreate to match title/read_only."""
    return current.title != item.title or current.read_only != item.read_only


def _summary(title: str, *, read_only: bool) -> dict[str, Any]:
    return {"title": title, "read_only": read_only}
