# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the team-grants manager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from repo_management.changes import Action
from repo_management.config import ConfigError, SharedConfig, TeamAccess
from repo_management.managers.teams import TeamsManager, _role

URL = "https://api.github.com/repos/acme/widget"


def make_repo(teams: list[dict[str, Any]]) -> MagicMock:
    """Build a mock org-owned repo whose requester answers the teams listing."""
    repo = MagicMock()
    repo.url = URL
    repo.full_name = "acme/widget"
    repo.organization = MagicMock(login="acme")

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url.split("?", maxsplit=1)[0] == f"{URL}/teams":
            # Match "&page=1" (not "page=1"), which also appears inside "per_page=100".
            return ({}, teams if "&page=1" in url else [])
        return ({}, {})

    repo.requester.requestJsonAndCheck.side_effect = request
    return repo


def _team(slug: str, permission: str) -> dict[str, Any]:
    # GitHub's listing carries a per-role `permissions` object; the effective role is the
    # highest flag set. Model just the requested role as the top true one.
    order = ["pull", "triage", "push", "maintain", "admin"]
    perms = {role: order.index(role) <= order.index(permission) for role in order}
    return {"slug": slug, "permission": permission, "permissions": perms}


def test_no_teams_is_noop(repo: MagicMock) -> None:
    """A config without a teams section yields no changes."""
    assert TeamsManager().plan(repo, SharedConfig()) == []
    repo.requester.requestJsonAndCheck.assert_not_called()


def test_teams_on_non_org_repo_raises(repo: MagicMock) -> None:
    """Teams are org-scoped: declaring them on a personal-account repo is a config error."""
    repo.organization = None
    desired = SharedConfig(teams=[TeamAccess(slug="sre", permission="push")])
    with pytest.raises(ConfigError, match="org-owned"):
        TeamsManager().plan(repo, desired)


def test_new_team_grant_is_created() -> None:
    """A team with no current access yields a CREATE that PUTs the org-scoped grant."""
    repo = make_repo([])
    desired = SharedConfig(teams=[TeamAccess(slug="sre", permission="admin")])

    changes = TeamsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "team:sre"
    assert (change.before, change.after) == (None, "admin")
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "PUT", "/orgs/acme/teams/sre/repos/acme/widget", input={"permission": "admin"}
    )


def test_matching_grant_is_noop() -> None:
    """A team already at the desired permission yields no change."""
    repo = make_repo([_team("sre", "push")])
    desired = SharedConfig(teams=[TeamAccess(slug="sre", permission="push")])
    assert TeamsManager().plan(repo, desired) == []


def test_differing_grant_is_updated() -> None:
    """A team at a different permission yields an UPDATE."""
    repo = make_repo([_team("sre", "pull")])
    desired = SharedConfig(teams=[TeamAccess(slug="sre", permission="maintain")])

    changes = TeamsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert (change.before, change.after) == ("pull", "maintain")
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "PUT", "/orgs/acme/teams/sre/repos/acme/widget", input={"permission": "maintain"}
    )


def test_unlisted_team_is_revoked() -> None:
    """A declared teams section is authoritative: a team with access absent from it is revoked."""
    repo = make_repo([_team("sre", "push"), _team("legacy", "admin")])
    desired = SharedConfig(teams=[TeamAccess(slug="sre", permission="push")])

    changes = TeamsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "team:legacy"
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "DELETE", "/orgs/acme/teams/legacy/repos/acme/widget"
    )


def test_list_paginates() -> None:
    """The teams listing walks pages so a repo with >100 grants isn't partially seen."""
    page1 = [_team(f"t{i}", "pull") for i in range(100)]

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url.split("?", maxsplit=1)[0] == f"{URL}/teams":
            # Match "&page=N", not "page=N": "page=1" is a substring of "per_page=100".
            if "&page=1" in url:
                return ({}, page1)
            if "&page=2" in url:
                return ({}, [_team("t100", "pull")])
            return ({}, [])
        return ({}, {})

    repo = MagicMock()
    repo.url = URL
    repo.full_name = "acme/widget"
    repo.organization = MagicMock(login="acme")
    repo.requester.requestJsonAndCheck.side_effect = request

    # Authoritative-empty revokes every listed team — 101 DELETE changes prove both pages read.
    changes = TeamsManager().plan(repo, SharedConfig(teams=[]))
    assert len(changes) == 101
    assert all(change.action is Action.DELETE for change in changes)


def test_role_falls_back_to_legacy_permission() -> None:
    """When the permissions object is absent, the legacy scalar permission is used."""
    assert _role({"slug": "x", "permission": "push"}) == "push"
    assert _role({"slug": "x"}) == "pull"
    assert _role({"slug": "x", "permissions": {"admin": True, "push": True}}) == "admin"
