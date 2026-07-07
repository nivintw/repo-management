# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository rulesets.

PyGithub has no ruleset support, so this manager drives the REST API directly through the
authenticated requester. Rulesets are matched against existing ones by ``name``. The list
endpoint omits rules/conditions, so each candidate match is fetched in full before diffing.

A declared ``rulesets`` section is authoritative: rulesets are created and updated to match
the config, and repo-level rulesets absent from the config are deleted. Listing passes
``includes_parents=false`` so inherited org/enterprise rulesets are never matched or
deleted through the repo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import SharedConfig

# GitHub's list-rulesets page cap; requesting the max minimizes round-trips.
_PER_PAGE = 100


class RulesetsManager:
    """Create and update repository rulesets, matched by name."""

    domain = "rulesets"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, update, and delete rulesets to match the config."""
        if desired.rulesets is None:
            return []

        existing = {item["name"]: item["id"] for item in self._list(repo)}
        changes: list[Change] = []
        for ruleset in desired.rulesets:
            body = ruleset.to_api()
            ruleset_id = existing.get(ruleset.name)
            if ruleset_id is None:
                changes.append(self._create(repo, ruleset.name, body))
            else:
                current = self._get(repo, ruleset_id)
                if not _matches(body, current):
                    changes.append(self._update(repo, ruleset_id, ruleset.name, body, current))

        wanted = {ruleset.name for ruleset in desired.rulesets}
        changes.extend(
            self._delete(repo, ruleset_id, name)
            for name, ruleset_id in existing.items()
            if name not in wanted
        )
        return changes

    def _list(self, repo: Repository) -> list[dict[str, Any]]:
        # includes_parents=false: manage only this repo's own rulesets, not ones inherited
        # from the org/enterprise (which can't be edited or deleted through the repo).
        # Paginate: the endpoint caps a page at 100 (defaults to 30), so a repo owning more
        # than a page of rulesets would otherwise silently drop the overflow from the diff.
        rulesets: list[dict[str, Any]] = []
        page = 1
        while True:
            _, data = repo.requester.requestJsonAndCheck(
                "GET",
                f"{repo.url}/rulesets?includes_parents=false&per_page={_PER_PAGE}&page={page}",
            )
            if not data:
                break
            rulesets.extend(data)
            if len(data) < _PER_PAGE:
                break
            page += 1
        return rulesets

    def _get(self, repo: Repository, ruleset_id: int) -> dict[str, Any]:
        _, data = repo.requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets/{ruleset_id}")
        return data

    def _create(self, repo: Repository, name: str, body: dict[str, Any]) -> Change:
        def apply() -> None:
            repo.requester.requestJsonAndCheck("POST", f"{repo.url}/rulesets", input=body)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"ruleset:{name}",
            before=None,
            after=_summary(body),
            apply=apply,
        )

    def _update(
        self,
        repo: Repository,
        ruleset_id: int,
        name: str,
        body: dict[str, Any],
        current: dict[str, Any],
    ) -> Change:
        url = f"{repo.url}/rulesets/{ruleset_id}"

        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT", url, input=body)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=f"ruleset:{name}",
            before=_summary(current),
            after=_summary(body),
            apply=apply,
        )

    def _delete(self, repo: Repository, ruleset_id: int, name: str) -> Change:
        url = f"{repo.url}/rulesets/{ruleset_id}"

        def apply() -> None:
            repo.requester.requestJsonAndCheck("DELETE", url)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"ruleset:{name}",
            before=f"ruleset:{name}",
            after=None,
            apply=apply,
        )


def _summary(api: dict[str, Any]) -> dict[str, Any]:
    """A concise, readable view of a ruleset for plan output."""
    rules = api.get("rules") or []
    return {
        "target": api.get("target"),
        "enforcement": api.get("enforcement"),
        "rules": sorted(rule["type"] for rule in rules),
    }


_UNMATCHED = object()


def _matches(desired: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether the live ruleset already matches the desired spec.

    A declared ruleset is authoritative, so its declared *lists* (rules, bypass actors,
    ref-name patterns) must match the live ones exactly — an extra or missing item is drift
    that triggers an update. *Dict* fields are matched as a subset, ignoring keys the spec
    never sets (server-supplied metadata like ``integration_id``, ``actor_id``, and
    timestamps), which we can't control and which would otherwise cause perpetual churn.
    Lists are compared order-insensitively.
    """
    return _satisfied(desired, current)


def _satisfied(desired: object, current: object) -> bool:
    """Whether ``current`` matches ``desired``: dicts by subset, lists exactly."""
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return False
        current_map: dict[Any, Any] = current
        return all(
            key in current_map and _satisfied(value, current_map[key])
            for key, value in desired.items()
        )
    if isinstance(desired, list):
        if not isinstance(current, list) or len(current) != len(desired):
            return False
        # Order-insensitive: pair each desired item with a distinct live item it matches.
        remaining: list[Any] = list(current)
        for item in desired:
            match = next((c for c in remaining if _satisfied(item, c)), _UNMATCHED)
            if match is _UNMATCHED:
                return False
            remaining.remove(match)
        return True
    return desired == current
