# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions secrets.

Secret values are write-only in the GitHub API, so an existing secret's value cannot be read
back to diff it. Consequences:

- A secret that is **absent** is created.
- A secret that **already exists** is left untouched by default — since we can't tell whether
  its value is current, re-writing it on every apply is pure churn.
- A declared ``secrets`` section is authoritative: a secret absent from it is deleted.

When an *existing* secret is nonetheless re-pushed — via ``force``, or via a source-timestamp
comparison — is decided by :class:`~repo_management.managers._secret_variable.SecretsPolicy`.
Values are never shown in plans; ``Repository.create_secret`` performs the libsodium encryption.

The diff logic itself lives in :mod:`repo_management.managers._secret_variable`, shared with the
environments manager's per-environment secrets. Only this repo-level manager passes a
``SecretsPolicy``; environment-scoped secrets keep the bare skip-if-exists default (the
source-timestamp policy is scoped to repo secrets, which is all this feature targets — and all
the fleet uses).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.managers._secret_variable import SecretsPolicy, plan_secrets

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from github.Repository import Repository

    from repo_management.changes import Change
    from repo_management.config import SharedConfig


class SecretsManager:
    """Reconcile Actions secrets: create, (optionally) re-push, and delete to match the config."""

    domain = "secrets"

    def __init__(
        self, *, force: bool = False, source_secrets: Mapping[str, datetime] | None = None
    ) -> None:
        """Build the manager; see :class:`SecretsPolicy` for what these knobs do."""
        self._policy = SecretsPolicy(force=force, source_secrets=source_secrets)

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return redacted changes to create, optionally re-push, and delete secrets."""
        if desired.secrets is None:
            return []
        return plan_secrets(repo, desired.secrets, domain=self.domain, policy=self._policy)
