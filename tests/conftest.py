# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Shared pytest fixtures and helpers for the test suite."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def repo() -> MagicMock:
    """Return a bare mock standing in for a PyGithub ``Repository``."""
    return MagicMock(name="Repository")


def make_label(name: str, color: str, description: str | None) -> MagicMock:
    """Build a mock PyGithub label with the given attributes."""
    label = MagicMock(name=f"Label({name})")
    label.name = name
    label.color = color
    label.description = description
    return label


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


def make_secret(name: str) -> MagicMock:
    """Build a mock PyGithub secret exposing only its name."""
    secret = MagicMock(name=f"Secret({name})")
    secret.name = name
    return secret
