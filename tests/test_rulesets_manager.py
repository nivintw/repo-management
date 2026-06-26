# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the rulesets manager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from repo_management.changes import Action
from repo_management.config import SharedConfig
from repo_management.managers.rulesets import RulesetsManager
from repo_management.ruleset import Ruleset

URL = "https://api.github.com/repos/o/r"


def make_repo(list_data: list[dict[str, Any]], get_data: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock repo whose requester answers list/get and records writes."""
    repo = MagicMock()
    repo.url = URL

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url == f"{URL}/rulesets":
            return ({}, list_data)
        if verb == "GET" and url.startswith(f"{URL}/rulesets/"):
            return ({}, get_data)
        return ({}, {})  # POST / PUT

    repo.requester.requestJsonAndCheck.side_effect = request
    return repo


def ruleset(**overrides: object) -> Ruleset:
    """A simple desired ruleset for tests."""
    data: dict[str, Any] = {
        "name": "main",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "required_linear_history"}],
    }
    data.update(overrides)
    return Ruleset.model_validate(data)


def test_no_rulesets_is_noop() -> None:
    """A config without a rulesets section yields no changes."""
    repo = make_repo([])
    assert RulesetsManager().plan(repo, SharedConfig()) == []
    repo.requester.requestJsonAndCheck.assert_not_called()


def test_new_ruleset_is_created() -> None:
    """A ruleset absent on the repo yields a CREATE that POSTs the body."""
    repo = make_repo([])
    desired = SharedConfig(rulesets=[ruleset()])

    changes = RulesetsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "ruleset:main"
    assert change.before is None
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "POST",
        f"{URL}/rulesets",
        input=ruleset().to_api(),
    )


def test_matching_ruleset_is_skipped() -> None:
    """A live ruleset matching the desired spec yields no change."""
    desired = ruleset()
    current = {"id": 1, "source": "Repository", **desired.to_api()}
    repo = make_repo([{"id": 1, "name": "main"}], current)

    assert RulesetsManager().plan(repo, SharedConfig(rulesets=[desired])) == []


def test_param_order_does_not_cause_diff() -> None:
    """List ordering inside rule parameters doesn't spuriously trigger an update."""
    desired = ruleset(rules=[{"type": "required_status_checks", "required_checks": ["a", "b"]}])
    current_body = ruleset(
        rules=[{"type": "required_status_checks", "required_checks": ["b", "a"]}],
    ).to_api()
    repo = make_repo([{"id": 1, "name": "main"}], {"id": 1, **current_body})

    assert RulesetsManager().plan(repo, SharedConfig(rulesets=[desired])) == []


def test_differing_ruleset_is_updated() -> None:
    """A live ruleset differing from desired yields an UPDATE that PUTs to its id."""
    desired = ruleset(enforcement="active")
    current = {"id": 42, **ruleset(enforcement="disabled").to_api()}
    repo = make_repo([{"id": 42, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "PUT",
        f"{URL}/rulesets/42",
        input=desired.to_api(),
    )


def test_differing_conditions_triggers_update() -> None:
    """Different ref-name conditions trigger an update."""
    desired = ruleset()
    other = ruleset(conditions={"ref_name": {"include": ["refs/heads/release/*"], "exclude": []}})
    repo = make_repo([{"id": 1, "name": "main"}], {"id": 1, **other.to_api()})

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_differing_bypass_actors_triggers_update() -> None:
    """Different bypass actors trigger an update."""
    desired = ruleset(bypass_actors=[{"actor_type": "OrganizationAdmin"}])
    current = {"id": 1, **ruleset().to_api()}  # no bypass actors
    repo = make_repo([{"id": 1, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_rule_added_triggers_update() -> None:
    """Adding a rule type to the desired spec triggers an update."""
    desired = ruleset(rules=[{"type": "required_linear_history"}, {"type": "non_fast_forward"}])
    current = {"id": 1, **ruleset(rules=[{"type": "required_linear_history"}]).to_api()}
    repo = make_repo([{"id": 1, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE
