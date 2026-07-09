# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions secrets.

Secret values are write-only in the GitHub API, so an existing secret's value cannot be read
back to diff it. Consequences:

- A secret that is **absent** is created.
- A secret that **already exists** is left untouched by default — since we can't tell whether
  its value is current, re-writing it on every apply is pure churn.
- A declared ``secrets`` section is authoritative: a secret absent from it is deleted.

Two things override that skip-if-exists default for an existing secret:

- ``force=True`` (surfaced as ``--force-secrets`` on the CLI) re-pushes every declared secret
  unconditionally — deliberate rotation, e.g. after issuing a new token.
- ``source_secrets`` — a ``{source-secret-name: updated_at}`` map of the source repo's own
  Actions secrets (see :func:`repo_management.client.source_secret_timestamps`) — re-pushes an
  existing secret only when its source changed more recently than the target's ``updated_at``.
  What we can't date on both sides (an inline ``value``, or a source with no known timestamp)
  keeps the skip-if-exists default. This is how a rotation at the source propagates to the
  fleet on the next apply without re-pushing every secret every run.

Values are never shown in plans. ``Repository.create_secret`` performs the libsodium encryption.

The diff logic itself lives in :mod:`repo_management.managers._secret_variable`, shared with
the environments manager's per-environment secrets (which passes no ``source_secrets`` and so
keeps the plain force/skip policy).
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
        """Build the manager.

        ``force`` re-pushes every existing secret; ``source_secrets`` re-pushes only those whose
        source secret changed more recently than the target's ``updated_at``. With neither, an
        existing secret is left untouched.
        """
        self._force = force
        self._source_secrets = source_secrets

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return redacted changes to create, optionally re-push, and delete secrets."""
        if desired.secrets is None:
            return []
        policy = SecretsPolicy(force=self._force, source_secrets=self._source_secrets)
        return plan_secrets(repo, desired.secrets, domain=self.domain, policy=policy)
