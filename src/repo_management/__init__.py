# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Repo Management."""

from importlib.metadata import PackageNotFoundError, version

# Single source of truth: the installed distribution's version. release-please bumps the
# version in pyproject.toml, which is what the built/installed package metadata reflects, so
# this never drifts the way a hand-edited constant would. The lookup name must stay equal to
# the distribution's `name` in pyproject.toml (both are project_slug at generation time). Fall
# back gracefully when the distribution isn't installed (a bare source checkout) so importing
# the package never hard-fails.
try:
    __version__ = version("repo-management")
# Hit on an uninstalled source checkout — or if the dist `name` was renamed away from this
# lookup, in which case fix the name rather than relying on this sentinel.
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"
