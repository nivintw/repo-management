# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions secrets.

Secret values are write-only in the GitHub API, so an existing secret's value cannot be read
back to diff it. Consequences:

- A secret that is **absent** is created.
- A secret that **already exists** is left untouched by default — since we can't tell whether
  its value is current, re-writing it on every apply is pure churn. To deliberately rotate a
  value (e.g. after issuing a new token), construct the manager with ``force=True`` (surfaced
  as ``--force-secrets`` on the CLI), which re-pushes every existing secret.
- A declared ``secrets`` section is authoritative: a secret absent from it is deleted.

Values are never shown in plans. ``Repository.create_secret`` performs the libsodium encryption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import Secret, SharedConfig


class SecretsManager:
    """Reconcile Actions secrets: create, (optionally) re-push, and delete to match the config."""

    domain = "secrets"

    def __init__(self, *, force: bool = False) -> None:
        """Build the manager; ``force`` re-pushes existing secret values instead of skipping."""
        self._force = force

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return redacted changes to create, optionally re-push, and delete secrets."""
        if desired.secrets is None:
            return []

        existing = {secret.name for secret in repo.get_secrets()}
        changes = [
            self._upsert(repo, secret, exists=secret.name in existing)
            for secret in desired.secrets
            if self._force or secret.name not in existing
        ]

        wanted = {secret.name for secret in desired.secrets}
        changes.extend(self._delete(repo, name) for name in existing if name not in wanted)
        return changes

    def _delete(self, repo: Repository, name: str) -> Change:
        def apply() -> None:
            repo.delete_secret(name)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"secret:{name}",
            before="(exists)",
            after=None,
            apply=apply,
        )

    def _upsert(self, repo: Repository, secret: Secret, *, exists: bool) -> Change:
        value = secret.resolve()

        def apply() -> None:
            repo.create_secret(secret.name, value)

        return Change(
            domain=self.domain,
            action=Action.UPDATE if exists else Action.CREATE,
            target=f"secret:{secret.name}",
            before="(exists)" if exists else None,
            after="(set)",
            apply=apply,
            secret=True,
        )
