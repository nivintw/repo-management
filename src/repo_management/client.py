# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""GitHub client construction and repository lookup."""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING

from github import Auth, Github, GithubException

from repo_management.config import ConfigError

if TYPE_CHECKING:
    from datetime import datetime

    from github.Repository import Repository

TOKEN_ENV = "GITHUB_TOKEN"  # noqa: S105 — env var name, not a secret
SOURCE_REPO_ENV = "GITHUB_REPOSITORY"


def get_client(token: str | None = None) -> Github:
    """Build an authenticated GitHub client.

    Args:
        token: A token to use directly. When omitted, the ``GITHUB_TOKEN``
            environment variable is read.

    Returns:
        An authenticated :class:`github.Github` client.

    Raises:
        ConfigError: If no token is available.
    """
    token = token or os.environ.get(TOKEN_ENV)
    if not token:
        msg = f"no GitHub token: pass one explicitly or set {TOKEN_ENV}"
        raise ConfigError(msg)
    return Github(auth=Auth.Token(token))


def get_repo(client: Github, full_name: str) -> Repository:
    """Fetch a repository by ``owner/name``.

    Args:
        client: An authenticated GitHub client.
        full_name: The repository in ``owner/name`` form.

    Returns:
        The :class:`github.Repository.Repository`.

    Raises:
        ConfigError: If the repository cannot be fetched.
    """
    try:
        return client.get_repo(full_name)
    except GithubException as exc:
        msg = f"cannot access repository {full_name!r}: {exc.data or exc}"
        raise ConfigError(msg) from exc


def source_secret_timestamps(client: Github) -> dict[str, datetime]:
    """Map each source Actions secret name to when it was last updated.

    The ``apply`` workflow runs inside a *source* repository whose own Actions secrets populate
    the ``value_from_env`` sources the CLI then propagates to the managed repos. GitHub never
    exposes a secret's value, but it does expose each secret's ``updated_at`` — read here from
    the source repo the very same way a target repo's secrets are read. This lets the secrets
    manager skip re-pushing a target secret whose value is already at least as new as the
    source, and overwrite only when the source secret changed more recently.

    The source repo is taken from ``GITHUB_REPOSITORY`` (always set under GitHub Actions).

    Two preconditions for a secret to be timestamp-propagated (both silently degrade to
    skip-if-exists, never a wrong overwrite — see the note on the bias below):

    - The env var must be named identically to the source secret it reads — ``FOO:
      ${{ secrets.FOO }}`` — because the map is keyed by source *secret* name while the manager
      looks it up by the config's ``value_from_env`` (env-var) name. A divergent mapping
      (``FOO: ${{ secrets.BAR }}``) simply won't match. This repo's ``test_workflow_secrets``
      enforces the identity for its own workflows.
    - The source secret must be a *repo-level* Actions secret; ``get_secrets()`` doesn't return
      org-level secrets inherited by the repo.

    Returns an empty map when ``GITHUB_REPOSITORY`` is unset (e.g. a local run) or the source
    secrets can't be read (the token lacks the permission). Callers then fall back to the
    write-only skip-if-exists policy rather than failing — so a read error biases toward leaving
    an existing secret in place, *not* propagating a rotation. That's non-blocking by design
    (one read error must not red the whole fleet reconcile), but it means ``--force-secrets``
    remains the only *guaranteed* way to push a rotation when this read is unavailable.
    """
    source = os.environ.get(SOURCE_REPO_ENV)
    if not source:
        return {}
    try:
        repo = client.get_repo(source)
        return {
            secret.name: secret.updated_at
            for secret in repo.get_secrets()
            if secret.updated_at is not None
        }
    except GithubException as exc:
        warnings.warn(
            f"cannot read source secret timestamps from {source!r} ({exc.data or exc}); "
            "existing secrets will NOT be re-pushed this run — rerun with --force-secrets to "
            "force a rotation to propagate",
            stacklevel=2,
        )
        return {}
