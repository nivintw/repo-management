# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Smoke test — replace with real tests."""

from repo_management import __version__


def test_version() -> None:
    """The package exposes a version string."""
    assert isinstance(__version__, str)
