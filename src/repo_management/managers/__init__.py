# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Domain managers and the registry the reconciler iterates over.

Each manager handles one slice of repository configuration. A manager exposes a
``domain`` name and a ``plan`` method returning the :class:`~repo_management.changes.Change`
objects needed to bring that slice into the desired state. Managers act only when their
config section is present; an absent section is left entirely unmanaged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from repo_management.managers.actions import ActionsManager
from repo_management.managers.autolinks import AutolinksManager
from repo_management.managers.codeowners import CodeownersManager
from repo_management.managers.collaborators import CollaboratorsManager
from repo_management.managers.deploy_keys import DeployKeysManager
from repo_management.managers.environments import EnvironmentsManager
from repo_management.managers.labels import LabelsManager
from repo_management.managers.pages import PagesManager
from repo_management.managers.rulesets import RulesetsManager
from repo_management.managers.secrets import SecretsManager
from repo_management.managers.security import SecurityManager
from repo_management.managers.settings import SettingsManager
from repo_management.managers.teams import TeamsManager
from repo_management.managers.variables import VariablesManager
from repo_management.managers.webhooks import WebhooksManager

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.changes import Change
    from repo_management.config import SharedConfig


class Manager(Protocol):
    """The interface every domain manager implements."""

    domain: str

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return the changes needed to reconcile this domain for ``repo``."""
        ...


def build_managers(*, force_secrets: bool = False) -> list[Manager]:
    """Build the ordered manager registry the reconciler runs for each repo.

    ``force_secrets`` re-pushes existing secret values (rotation) instead of skipping them;
    every other manager is stateless, so the flag only reaches :class:`SecretsManager`.
    """
    return [
        SettingsManager(),
        ActionsManager(),
        SecurityManager(),
        RulesetsManager(),
        LabelsManager(),
        CollaboratorsManager(),
        TeamsManager(),
        CodeownersManager(),
        WebhooksManager(),
        DeployKeysManager(),
        AutolinksManager(),
        PagesManager(),
        SecretsManager(force=force_secrets),
        VariablesManager(),
        EnvironmentsManager(),
    ]


__all__ = ["Manager", "build_managers"]
