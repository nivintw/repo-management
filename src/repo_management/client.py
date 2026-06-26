# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""GitHub client construction and repository lookup."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from github import Auth, Github, GithubException

from repo_management.config import ConfigError

if TYPE_CHECKING:
    from github.Repository import Repository

TOKEN_ENV = "GITHUB_TOKEN"  # noqa: S105 — env var name, not a secret


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
