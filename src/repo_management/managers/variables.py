# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository Actions variables.

Unlike secrets, variable values are readable, so an existing variable's value can be
diffed: it is updated only when the desired value actually differs. A declared
``variables`` section is authoritative — variables absent from the config are deleted.
Values are not sensitive and are shown in plain text in plans.

The diff logic itself lives in :mod:`repo_management.managers._secret_variable`, shared with
the environments manager's per-environment variables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_management.managers._secret_variable import plan_variables

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.changes import Change
    from repo_management.config import SharedConfig


class VariablesManager:
    """Reconcile Actions variables: a declared section is the authoritative, complete set."""

    domain = "variables"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, update, and delete variables to match the config."""
        if desired.variables is None:
            return []
        return plan_variables(repo, desired.variables, domain=self.domain)
