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

    Idempotency check: everything the desired body declares must already be present in the
    live ruleset. Fields/items the spec omits (server-supplied defaults and metadata like
    ``integration_id``, ``actor_id``, timestamps) are ignored, so they don't cause a
    perpetual diff. Lists are matched order-insensitively.
    """
    return _satisfied(desired, current)


def _satisfied(desired: object, current: object) -> bool:
    """Whether ``current`` contains everything ``desired`` declares (recursive subset)."""
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return False
        current_map: dict[Any, Any] = current
        return all(
            key in current_map and _satisfied(value, current_map[key])
            for key, value in desired.items()
        )
    if isinstance(desired, list):
        if not isinstance(current, list):
            return False
        candidates: list[Any] = current
        return all(any(_satisfied(item, candidate) for candidate in candidates) for item in desired)
    return desired == current
