# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""How a mode and an empty or omitted section interact, across the access-granting managers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from conftest import make_deploy_key, make_user
from test_teams_manager import _team, make_repo

from repo_management.changes import Action
from repo_management.config import SharedConfig
from repo_management.managers.collaborators import CollaboratorsManager
from repo_management.managers.deploy_keys import DeployKeysManager
from repo_management.managers.teams import TeamsManager

if TYPE_CHECKING:
    from collections.abc import Callable


def _repo_with_collaborator() -> MagicMock:
    repo = MagicMock()
    repo.get_collaborators.return_value = [make_user("Rogue")]
    return repo


def _repo_with_team() -> MagicMock:
    return make_repo([_team("Rogue", "push")])


def _repo_with_deploy_key() -> MagicMock:
    repo = MagicMock()
    repo.get_keys.return_value = [make_deploy_key(title="Rogue", key="ssh-ed25519 ROGUE")]
    return repo


# Each section with its manager, a repo carrying one unlisted entry, and that entry's plan target.
# Teams' target is the live slug, which is the one a revoke has to use.
_SECTIONS = pytest.mark.parametrize(
    ("section", "manager", "make", "target"),
    [
        ("collaborators", CollaboratorsManager, _repo_with_collaborator, "collaborator:Rogue"),
        ("teams", TeamsManager, _repo_with_team, "team:Rogue"),
        ("deploy_keys", DeployKeysManager, _repo_with_deploy_key, "deploy_key:Rogue"),
    ],
    ids=["collaborators", "teams", "deploy_keys"],
)


@_SECTIONS
def test_mode_without_section_is_unmanaged(
    section: str, manager: type[Any], make: Callable[[], MagicMock], target: str
) -> None:
    """An omitted section outranks its mode, even though modes merge through extends separately.

    The dangerous misreading is a mode with no section removing everyone on every repo.
    """
    del target
    desired = SharedConfig.model_validate({f"{section}_mode": "authoritative"})

    assert manager().plan(make(), desired) == []


@_SECTIONS
def test_empty_section_is_a_noop_under_add_only(
    section: str, manager: type[Any], make: Callable[[], MagicMock], target: str
) -> None:
    """An empty section removed everything in 1.x, and removes nothing now."""
    del target
    desired = SharedConfig.model_validate({section: []})

    assert manager().plan(make(), desired) == []


@_SECTIONS
def test_empty_section_removes_everything_when_authoritative(
    section: str, manager: type[Any], make: Callable[[], MagicMock], target: str
) -> None:
    """An empty authoritative section is the way to remove everyone, and must keep working."""
    desired = SharedConfig.model_validate({section: [], f"{section}_mode": "authoritative"})

    changes = manager().plan(make(), desired)

    assert [(change.action, change.target) for change in changes] == [(Action.DELETE, target)]
