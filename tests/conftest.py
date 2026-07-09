# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Shared pytest fixtures and helpers for the test suite."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from datetime import datetime


@pytest.fixture(autouse=True)
def _hermetic_source_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite independent of ambient CI env.

    GitHub Actions sets ``GITHUB_REPOSITORY``, which would make the reconciler's source-secret
    lookup fire against a mock client. Clear it so tests only exercise that path when they set
    it deliberately.
    """
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)


@pytest.fixture
def repo() -> MagicMock:
    """Return a mock standing in for a PyGithub ``Repository``.

    ``get_collaborators`` defaults to empty so the authoritative-prune pass has nothing to
    remove unless a test populates it.
    """
    mock = MagicMock(name="Repository")
    mock.get_collaborators.return_value = []
    return mock


def make_user(login: str) -> MagicMock:
    """Build a mock PyGithub ``NamedUser`` exposing only its login."""
    user = MagicMock(name=f"NamedUser({login})")
    user.login = login
    return user


def make_label(name: str, color: str, description: str | None) -> MagicMock:
    """Build a mock PyGithub label with the given attributes."""
    label = MagicMock(name=f"Label({name})")
    label.name = name
    label.color = color
    label.description = description
    return label


def make_autolink(
    key_prefix: str, url_template: str, *, is_alphanumeric: bool = True, autolink_id: int = 1
) -> MagicMock:
    """Build a mock PyGithub autolink with the given attributes."""
    autolink = MagicMock(name=f"Autolink({key_prefix})")
    autolink.id = autolink_id
    autolink.key_prefix = key_prefix
    autolink.url_template = url_template
    autolink.is_alphanumeric = is_alphanumeric
    return autolink


def make_hook(
    url: str,
    events: list[str],
    *,
    active: bool,
    content_type: str = "json",
    insecure_ssl: str = "0",
) -> MagicMock:
    """Build a mock PyGithub webhook with the given config."""
    hook = MagicMock(name=f"Hook({url})")
    hook.events = events
    hook.active = active
    hook.config = {"url": url, "content_type": content_type, "insecure_ssl": insecure_ssl}
    return hook


def make_secret(name: str, updated_at: datetime | None = None) -> MagicMock:
    """Build a mock PyGithub secret exposing its name and last-updated time."""
    secret = MagicMock(name=f"Secret({name})")
    secret.name = name
    secret.updated_at = updated_at
    return secret


def make_variable(name: str, value: str) -> MagicMock:
    """Build a mock PyGithub variable exposing its name and (readable) value."""
    variable = MagicMock(name=f"Variable({name})")
    variable.name = name
    variable.value = value
    return variable


def make_deploy_key(title: str, key: str, *, read_only: bool = True) -> MagicMock:
    """Build a mock PyGithub ``RepositoryKey`` with the given attributes."""
    deploy_key = MagicMock(name=f"RepositoryKey({title})")
    deploy_key.title = title
    deploy_key.key = key
    deploy_key.read_only = read_only
    return deploy_key
