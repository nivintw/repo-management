# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for GitHub client construction and repository lookup."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import GithubException

from repo_management.client import get_client, get_repo
from repo_management.config import ConfigError


def test_get_client_explicit_token() -> None:
    """An explicit token builds a client."""
    assert get_client("tok") is not None


def test_get_client_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client is built from GITHUB_TOKEN when no token is passed."""
    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    assert get_client() is not None


def test_get_client_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing token raises ConfigError."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="no GitHub token"):
        get_client()


def test_get_repo_success() -> None:
    """get_repo returns the repository from the client."""
    client = MagicMock()
    client.get_repo.return_value = "REPO"
    assert get_repo(client, "owner/repo") == "REPO"
    client.get_repo.assert_called_once_with("owner/repo")


def test_get_repo_failure() -> None:
    """A GithubException is wrapped in ConfigError."""
    client = MagicMock()
    client.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)
    with pytest.raises(ConfigError, match="cannot access"):
        get_repo(client, "owner/missing")
