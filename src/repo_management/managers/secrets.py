# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions secrets.

Secret values are write-only in the GitHub API, so an existing secret's value cannot be
read back to diff it. A secret that is absent is created; a secret that already exists is
updated unconditionally (we cannot prove its value is current). Values are never shown in
plans. ``Repository.create_secret`` performs the libsodium encryption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import Secret, SharedConfig


class SecretsManager:
    """Reconcile Actions secrets, creating or updating each configured secret."""

    domain = "secrets"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return a redacted change per secret that must be created or updated."""
        if desired.secrets is None:
            return []

        existing = {secret.name for secret in repo.get_secrets()}
        return [
            self._secret_change(repo, secret, exists=secret.name in existing)
            for secret in desired.secrets
        ]

    def _secret_change(self, repo: Repository, secret: Secret, *, exists: bool) -> Change:
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
