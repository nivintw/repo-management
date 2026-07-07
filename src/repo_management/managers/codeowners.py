# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for a repository's ``CODEOWNERS`` file.

Manages the single canonical ``.github/CODEOWNERS`` blob through the Contents API. A declared
``codeowners`` section is authoritative: the file is created/updated to exactly the rendered
entries, and an empty list (``codeowners: []``) is the authoritative "no owners" state, which
deletes the file if present. An unset section is unmanaged, consistent with every other
manager.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from github import GithubException

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import CodeownersEntry, SharedConfig

# The canonical path GitHub reads CODEOWNERS from (it also checks the repo root and docs/, but
# .github/ is the conventional home and the single path this manager owns).
_PATH = ".github/CODEOWNERS"
_HEADER = "# Managed by repo-management — do not edit by hand."
_MESSAGE = "chore: Reconcile CODEOWNERS via repo-management"


class CodeownersManager:
    """Reconcile the ``.github/CODEOWNERS`` file to match the declared owners."""

    domain = "codeowners"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return at most one change to create, update, or delete CODEOWNERS."""
        if desired.codeowners is None:
            return []

        wanted = _render(desired.codeowners)
        current = self._get(repo)

        if wanted is None:  # authoritative-absent (empty list)
            return [] if current is None else [self._delete(repo, current[1])]
        if current is None:
            return [self._create(repo, wanted)]
        text, sha = current
        if text == wanted:
            return []
        return [self._update(repo, wanted, sha)]

    def _get(self, repo: Repository) -> tuple[str, str] | None:
        try:
            content = repo.get_contents(_PATH)
        except GithubException as exc:
            if exc.status == HTTPStatus.NOT_FOUND:
                return None
            raise
        # get_contents returns a list only for a directory path; CODEOWNERS is a file.
        if isinstance(content, list):
            msg = f"expected {_PATH} to be a file, got a directory"
            raise TypeError(msg)
        return content.decoded_content.decode("utf-8"), content.sha

    def _create(self, repo: Repository, wanted: str) -> Change:
        def apply() -> None:
            repo.create_file(_PATH, _MESSAGE, wanted)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=_PATH,
            before=None,
            after=wanted,
            apply=apply,
        )

    def _update(self, repo: Repository, wanted: str, sha: str) -> Change:
        def apply() -> None:
            repo.update_file(_PATH, _MESSAGE, wanted, sha)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=_PATH,
            before="<current CODEOWNERS>",
            after=wanted,
            apply=apply,
        )

    def _delete(self, repo: Repository, sha: str) -> Change:
        def apply() -> None:
            repo.delete_file(_PATH, _MESSAGE, sha)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=_PATH,
            before=_PATH,
            after=None,
            apply=apply,
        )


def _render(entries: list[CodeownersEntry]) -> str | None:
    """Render entries to a CODEOWNERS file body, or ``None`` for an authoritative-empty set."""
    if not entries:
        return None
    lines = [_HEADER, *(f"{entry.pattern} {' '.join(entry.owners)}" for entry in entries)]
    return "\n".join(lines) + "\n"
