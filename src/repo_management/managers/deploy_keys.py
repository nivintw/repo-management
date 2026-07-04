# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository deploy keys.

A declared ``deploy_keys`` section is the authoritative, complete set: a key present on
the repo but absent from the section is deleted. The natural key for the diff is the
key's content (the ``key`` field), not its ``title`` -- GitHub allows duplicate titles,
but key content is the real identity of a deploy key. Matching normalizes to just the
algorithm and base64 body (see :func:`_normalize_key`): an ``ssh-keygen``-style trailing
comment, or the ambient whitespace a YAML block scalar can introduce, must not cause a
key that's otherwise unchanged to be planned as a spurious delete+recreate.

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

        existing = {_normalize_key(key.key): key for key in repo.get_keys()}
        wanted = desired.deploy_keys
        changes: list[Change] = []

        for item in wanted:
            current = existing.get(_normalize_key(item.key))
            if current is None:
                changes.append(self._create(repo, item))
            elif _deploy_key_differs(current, item):
                changes.append(self._delete(current))
                changes.append(self._create(repo, item))

        wanted_keys = {_normalize_key(item.key) for item in wanted}
        changes.extend(
            self._delete(key) for content, key in existing.items() if content not in wanted_keys
        )

        return changes

    def _create(self, repo: Repository, item: DeployKey) -> Change:
        def apply() -> None:
            # Matching tolerates ambient whitespace (a YAML block scalar can introduce a
            # trailing newline), but the API call itself must not send it -- strip before
            # create, preserving any real comment suffix as part of the key content.
            repo.create_key(item.title, item.key.strip(), read_only=item.read_only)

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


_KEY_FIELDS = 2  # algorithm + base64 body; an optional trailing comment is field 3+.


def _normalize_key(key: str) -> str:
    """The algorithm and base64 body only, dropping an optional trailing comment.

    ``ssh-keygen``'s default output always appends a ``user@host``-style comment, and a
    YAML block scalar can introduce trailing whitespace -- neither is part of the key's
    real identity, so both sides of the match are normalized to just the first two
    whitespace-separated fields.
    """
    parts = key.split()
    return " ".join(parts[:_KEY_FIELDS]) if len(parts) >= _KEY_FIELDS else key.strip()


def _deploy_key_differs(current: RepositoryKey, item: DeployKey) -> bool:
    """Whether the same-content key needs a delete+recreate to match title/read_only."""
    return current.title != item.title or current.read_only != item.read_only


def _summary(title: str, *, read_only: bool) -> dict[str, Any]:
    return {"title": title, "read_only": read_only}
