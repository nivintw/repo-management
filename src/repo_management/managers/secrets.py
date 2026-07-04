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

The diff logic itself lives in :mod:`repo_management.managers._secret_variable`, shared with
the environments manager's per-environment secrets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.managers._secret_variable import plan_secrets

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.changes import Change
    from repo_management.config import SharedConfig


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
        return plan_secrets(repo, desired.secrets, domain=self.domain, force=self._force)
