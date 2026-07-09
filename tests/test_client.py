# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for GitHub client construction and repository lookup."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from conftest import make_secret
from github import GithubException

from repo_management.client import get_client, get_repo, source_secret_timestamps
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


def test_source_secret_timestamps_maps_name_to_updated_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source repo's secrets are read into a name -> updated_at map (values skipped)."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/source")
    updated = datetime(2026, 6, 1, tzinfo=UTC)
    client = MagicMock()
    client.get_repo.return_value.get_secrets.return_value = [
        make_secret("TOKEN", updated_at=updated),
        make_secret("UNDATED", updated_at=None),  # dropped — nothing to compare against
    ]

    assert source_secret_timestamps(client) == {"TOKEN": updated}
    client.get_repo.assert_called_once_with("owner/source")


def test_source_secret_timestamps_unset_repo_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no GITHUB_REPOSITORY (a local run) the map is empty and no API call is made."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    client = MagicMock()

    assert source_secret_timestamps(client) == {}
    client.get_repo.assert_not_called()


def test_source_secret_timestamps_unreadable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A permission error reading the source secrets degrades to an empty map with a warning.

    The realistic failure is the token lacking secrets:read, which surfaces from
    ``get_secrets()`` (not ``get_repo``) — point the mock there so this test would catch a
    regression that moved the fetch outside the try.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/source")
    client = MagicMock()
    client.get_repo.return_value.get_secrets.side_effect = GithubException(
        403, {"message": "Resource not accessible by integration"}, None
    )

    with pytest.warns(UserWarning, match="force-secrets"):
        assert source_secret_timestamps(client) == {}
