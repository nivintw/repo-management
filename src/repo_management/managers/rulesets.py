# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository rulesets.

PyGithub has no ruleset support, so this manager drives the REST API directly through the
authenticated requester. Rulesets are matched against existing ones by ``name``. The list
endpoint omits rules/conditions, so each candidate match is fetched in full before diffing.
This manager is additive: it creates and updates rulesets but never deletes one absent from
the config.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import SharedConfig


class RulesetsManager:
    """Create and update repository rulesets, matched by name."""

    domain = "rulesets"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create or update each configured ruleset."""
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
        return changes

    def _list(self, repo: Repository) -> list[dict[str, Any]]:
        _, data = repo.requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets")
        return data

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


def _summary(api: dict[str, Any]) -> dict[str, Any]:
    """A concise, readable view of a ruleset for plan output."""
    rules = api.get("rules") or []
    return {
        "target": api.get("target"),
        "enforcement": api.get("enforcement"),
        "rules": sorted(rule["type"] for rule in rules),
    }


def _matches(desired: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether the live ruleset already satisfies the desired spec.

    Only the fields the desired spec declares are compared, so server-supplied defaults and
    extra metadata don't cause spurious diffs.
    """
    if any(desired[key] != current.get(key) for key in ("name", "target", "enforcement")):
        return False
    if _conditions(desired) != _conditions(current):
        return False
    if _actors(desired) != _actors(current):
        return False
    return _rules_match(desired.get("rules") or [], current.get("rules") or [])


def _conditions(api: dict[str, Any]) -> tuple[list[str], list[str]]:
    ref_name = (api.get("conditions") or {}).get("ref_name") or {}
    return sorted(ref_name.get("include") or []), sorted(ref_name.get("exclude") or [])


def _actors(api: dict[str, Any]) -> list[tuple[Any, Any, Any]]:
    actors = api.get("bypass_actors") or []
    return sorted(
        (actor.get("actor_type"), actor.get("actor_id"), actor.get("bypass_mode"))
        for actor in actors
    )


def _rules_match(desired: list[dict[str, Any]], current: list[dict[str, Any]]) -> bool:
    desired_by_type = {rule["type"]: rule.get("parameters") or {} for rule in desired}
    current_by_type = {rule["type"]: rule.get("parameters") or {} for rule in current}
    if set(desired_by_type) != set(current_by_type):
        return False
    return all(
        _norm(value) == _norm(current_by_type[rule_type].get(key))
        for rule_type, params in desired_by_type.items()
        for key, value in params.items()
    )


def _norm(value: object) -> object:
    """Normalize a parameter value so list ordering doesn't cause spurious diffs."""
    if isinstance(value, list):
        return sorted(
            json.dumps(item, sort_keys=True) if isinstance(item, dict) else repr(item)
            for item in value
        )
    return value
