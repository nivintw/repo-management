# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for team → repository permission grants.

The sibling to :class:`~repo_management.managers.collaborators.CollaboratorsManager`, but for
teams rather than individual users. Teams exist only inside an organization, so this manager
requires an org-owned repository; a declared ``teams`` section on a personal-account repo is a
config error.

A declared ``teams`` section is authoritative: each team's permission is granted/updated, and
a team with access absent from the config has its grant revoked. PyGithub has no clean
team-grant surface, so — like ``RulesetsManager`` — this drives the REST API directly through
the authenticated requester: the org-scoped ``PUT``/``DELETE
/orgs/{org}/teams/{slug}/repos/{owner}/{repo}`` write endpoints, and the repo-scoped
``GET {repo.url}/teams`` listing for the current grants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change
from repo_management.config import ConfigError

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import SharedConfig, TeamAccess

# GitHub's list-teams page cap; requesting the max minimizes round-trips.
_PER_PAGE = 100
# Repository roles from most to least privileged — the granular permission is the highest flag
# set in a team's `permissions` object (the legacy scalar `permission` collapses roles).
_ROLES = ("admin", "maintain", "push", "triage", "pull")


class TeamsManager:
    """Grant, update, and revoke team access to match the config."""

    domain = "teams"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to grant, re-permission, and revoke team access to match config."""
        if desired.teams is None:
            return []

        org = repo.organization
        if org is None:
            msg = "a 'teams' section requires an org-owned repository (teams are org-scoped)"
            raise ConfigError(msg)

        existing = {team["slug"]: _role(team) for team in self._list(repo)}
        changes: list[Change] = []
        for team in desired.teams:
            change = self._grant_change(repo, org.login, team, existing.get(team.slug))
            if change is not None:
                changes.append(change)

        wanted = {team.slug for team in desired.teams}
        changes.extend(
            self._revoke(repo, org.login, slug) for slug in existing if slug not in wanted
        )
        return changes

    def _list(self, repo: Repository) -> list[dict[str, Any]]:
        teams: list[dict[str, Any]] = []
        page = 1
        while True:
            _, data = repo.requester.requestJsonAndCheck(
                "GET",
                f"{repo.url}/teams?per_page={_PER_PAGE}&page={page}",
            )
            if not data:
                break
            teams.extend(data)
            if len(data) < _PER_PAGE:
                break
            page += 1
        return teams

    def _grant_change(
        self, repo: Repository, org_login: str, team: TeamAccess, current: str | None
    ) -> Change | None:
        if current == team.permission:
            return None

        url = f"/orgs/{org_login}/teams/{team.slug}/repos/{repo.full_name}"

        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT", url, input={"permission": team.permission})

        is_new = current is None
        return Change(
            domain=self.domain,
            action=Action.CREATE if is_new else Action.UPDATE,
            target=f"team:{team.slug}",
            before=None if is_new else current,
            after=team.permission,
            apply=apply,
        )

    def _revoke(self, repo: Repository, org_login: str, slug: str) -> Change:
        url = f"/orgs/{org_login}/teams/{slug}/repos/{repo.full_name}"

        def apply() -> None:
            repo.requester.requestJsonAndCheck("DELETE", url)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"team:{slug}",
            before=slug,
            after=None,
            apply=apply,
        )


def _role(team: dict[str, Any]) -> str:
    """Derive a team's granular repo role from its API listing entry.

    The listing carries a ``permissions`` object of per-role booleans; the effective role is
    the highest one set. Falls back to the legacy scalar ``permission`` if it's absent.
    """
    permissions = team.get("permissions") or {}
    for role in _ROLES:
        if permissions.get(role):
            return role
    return team.get("permission", "pull")
