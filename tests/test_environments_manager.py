# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the deployment environments manager."""

from __future__ import annotations

from typing import Literal, cast
from unittest.mock import MagicMock

import pytest

from repo_management.changes import Action
from repo_management.config import (
    ConfigError,
    DeploymentBranchPattern,
    DeploymentBranchPolicy,
    Environment,
    Reviewer,
    Secret,
    SharedConfig,
    Variable,
)
from repo_management.managers.environments import EnvironmentsManager

URL = "https://api.github.com/repos/o/r"
_POLICIES = f"{URL}/environments/prod/deployment-branch-policies"


def _reviewer_entry(type_: str, reviewer_id: int) -> MagicMock:
    entry = MagicMock(name=f"ProtectionRuleReviewer({type_}:{reviewer_id})")
    entry.type = type_
    entry.reviewer = MagicMock(name=f"Actor({reviewer_id})")
    entry.reviewer.id = reviewer_id
    return entry


def _rule(rule_type: str, **attrs: object) -> MagicMock:
    rule = MagicMock(name=f"ProtectionRule({rule_type})")
    rule.type = rule_type
    for key, value in attrs.items():
        setattr(rule, key, value)
    return rule


def _make_environment(
    name: str,
    *,
    wait_timer: int | None = None,
    reviewers: list[MagicMock] | None = None,
    prevent_self_review: bool | None = None,
    branch_policy: dict[str, bool] | None = None,
) -> MagicMock:
    env = MagicMock(name=f"Environment({name})")
    env.name = name
    rules = []
    if wait_timer is not None:
        rules.append(_rule("wait_timer", wait_timer=wait_timer))
    if reviewers is not None or prevent_self_review is not None:
        rules.append(
            _rule(
                "required_reviewers",
                prevent_self_review=prevent_self_review or False,
                reviewers=reviewers or [],
            )
        )
    env.protection_rules = rules
    if branch_policy is not None:
        policy = MagicMock(name="BranchPolicy")
        policy.protected_branches = branch_policy["protected_branches"]
        policy.custom_branch_policies = branch_policy["custom_branch_policies"]
        env.deployment_branch_policy = policy
    else:
        env.deployment_branch_policy = None
    env.get_secrets.return_value = []
    env.get_variables.return_value = []
    return env


def test_no_environments_is_noop(repo: MagicMock) -> None:
    """A repo config without an environments section yields no changes."""
    assert EnvironmentsManager().plan(repo, SharedConfig()) == []


def test_new_environment_creates_with_defaults(repo: MagicMock) -> None:
    """A brand-new environment with nothing set creates with API defaults."""
    repo.get_environments.return_value = []
    desired = SharedConfig(environments=[Environment(name="prod")])

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "environment:prod"
    change.apply()
    repo.create_environment.assert_called_once_with(
        "prod",
        wait_timer=0,
        reviewers=[],
        prevent_self_review=False,
        deployment_branch_policy=None,
    )


def test_new_environment_resolves_user_reviewer(repo: MagicMock) -> None:
    """A User reviewer's login is resolved to a numeric ID via GET /users/{login}."""
    repo.get_environments.return_value = []
    repo.requester.requestJsonAndCheck.return_value = ({}, {"id": 42})
    desired = SharedConfig(
        environments=[Environment(name="prod", reviewers=[Reviewer(type="User", login="octocat")])]
    )

    changes = EnvironmentsManager().plan(repo, desired)
    changes[0].apply()

    repo.requester.requestJsonAndCheck.assert_called_once_with("GET", "/users/octocat")
    call = repo.create_environment.call_args
    reviewers = call.kwargs["reviewers"]
    assert len(reviewers) == 1
    assert (reviewers[0].type, reviewers[0].id) == ("User", 42)


def test_new_environment_resolves_team_reviewer_via_org(repo: MagicMock) -> None:
    """A Team reviewer's slug is resolved via the repo's owning org."""
    repo.get_environments.return_value = []
    repo.organization = MagicMock(login="acme")
    repo.requester.requestJsonAndCheck.return_value = ({}, {"id": 7})
    desired = SharedConfig(
        environments=[Environment(name="prod", reviewers=[Reviewer(type="Team", slug="sre")])]
    )

    changes = EnvironmentsManager().plan(repo, desired)
    changes[0].apply()

    repo.requester.requestJsonAndCheck.assert_called_once_with("GET", "/orgs/acme/teams/sre")
    reviewers = repo.create_environment.call_args.kwargs["reviewers"]
    assert (reviewers[0].type, reviewers[0].id) == ("Team", 7)


def test_team_reviewer_without_org_raises(repo: MagicMock) -> None:
    """A Team reviewer on a non-org-owned repo is a clear config error, not a crash."""
    repo.get_environments.return_value = []
    repo.organization = None
    desired = SharedConfig(
        environments=[Environment(name="prod", reviewers=[Reviewer(type="Team", slug="sre")])]
    )

    with pytest.raises(ConfigError, match="org-owned"):
        EnvironmentsManager().plan(repo, desired)


def test_shared_reviewer_resolved_once_across_environments(repo: MagicMock) -> None:
    """A reviewer declared on multiple environments is only resolved via one API call."""
    repo.get_environments.return_value = []
    repo.requester.requestJsonAndCheck.return_value = ({}, {"id": 42})
    desired = SharedConfig(
        environments=[
            Environment(name="staging", reviewers=[Reviewer(type="User", login="octocat")]),
            Environment(name="prod", reviewers=[Reviewer(type="User", login="octocat")]),
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 2
    repo.requester.requestJsonAndCheck.assert_called_once_with("GET", "/users/octocat")


def test_new_environment_pushes_secrets_and_variables(repo: MagicMock) -> None:
    """Creating an environment with secrets/variables pushes them after create_environment."""
    repo.get_environments.return_value = []
    created_env = _make_environment("prod")
    repo.create_environment.return_value = created_env
    desired = SharedConfig(
        environments=[
            Environment(
                name="prod",
                secrets=[Secret(name="API_KEY", value="s3cr3t")],
                variables=[Variable(name="REGION", value="us-east-1")],
            )
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.after == {
        "wait_timer": 0,
        "reviewers": [],
        "prevent_self_review": False,
        "deployment_branch_policy": None,
        "secrets": ["API_KEY"],
        "variables": {"REGION": "us-east-1"},
    }
    assert change.secret is False  # only names/values of non-sensitive fields are shown
    change.apply()
    created_env.create_secret.assert_called_once_with("API_KEY", "s3cr3t")
    created_env.create_variable.assert_called_once_with("REGION", "us-east-1")


def test_new_environment_unresolvable_variable_degrades_to_diagnostic(
    repo: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating an environment with an unresolvable variable emits a diagnostic, not a crash.

    The environment CREATE still shows (with a placeholder for the unresolved value), and a
    separate `!` diagnostic is emitted so the plan is a hard failure — same policy the repo-level
    and existing-environment variable paths use.
    """
    monkeypatch.delenv("REGION_SRC", raising=False)
    repo.get_environments.return_value = []
    repo.create_environment.return_value = _make_environment("prod")
    desired = SharedConfig(
        environments=[
            Environment(
                name="prod", variables=[Variable(name="REGION", value_from_env="REGION_SRC")]
            )
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)  # must not raise

    create = next(c for c in changes if c.action is Action.CREATE)
    assert "unresolved" in cast("dict", create.after)["variables"]["REGION"]
    diagnostic = next(c for c in changes if c.unresolved)
    assert diagnostic.target == "environment:prod:variable:REGION"
    with pytest.raises(ConfigError):
        diagnostic.apply()


def test_existing_environment_in_sync_is_noop(repo: MagicMock) -> None:
    """An existing environment already matching produces no change."""
    current = _make_environment("prod", wait_timer=30)
    repo.get_environments.return_value = [current]
    desired = SharedConfig(environments=[Environment(name="prod", wait_timer=30)])
    assert EnvironmentsManager().plan(repo, desired) == []


def test_unknown_protection_rule_type_is_ignored(repo: MagicMock) -> None:
    """A protection-rule type this manager doesn't model (e.g. branch_policy) is ignored.

    GitHub's protection_rules list always includes a branch_policy-typed entry alongside
    wait_timer/required_reviewers, but that entry carries no data of its own -- the real
    policy is read separately via deployment_branch_policy -- so it must not cause a crash
    or a spurious diff.
    """
    current = _make_environment("prod", wait_timer=30)
    current.protection_rules.append(_rule("branch_policy"))
    repo.get_environments.return_value = [current]
    desired = SharedConfig(environments=[Environment(name="prod", wait_timer=30)])
    assert EnvironmentsManager().plan(repo, desired) == []


def test_existing_environment_wait_timer_change(repo: MagicMock) -> None:
    """A differing wait_timer yields an UPDATE that re-sends the same create_environment call."""
    current = _make_environment("prod", wait_timer=30)
    repo.get_environments.return_value = [current]
    desired = SharedConfig(environments=[Environment(name="prod", wait_timer=60)])

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    unmanaged = {"reviewers": [], "prevent_self_review": False, "deployment_branch_policy": None}
    assert change.before == {"wait_timer": 30, **unmanaged}
    assert change.after == {"wait_timer": 60, **unmanaged}
    change.apply()
    repo.create_environment.assert_called_once_with(
        "prod",
        wait_timer=60,
        reviewers=[],
        prevent_self_review=False,
        deployment_branch_policy=None,
    )


def test_unset_fields_preserve_current_value(repo: MagicMock) -> None:
    """Leaving prevent_self_review/reviewers/branch_policy unset preserves their live values."""
    current = _make_environment(
        "prod",
        wait_timer=30,
        reviewers=[_reviewer_entry("User", 99)],
        prevent_self_review=True,
        branch_policy={"protected_branches": True, "custom_branch_policies": False},
    )
    repo.get_environments.return_value = [current]
    desired = SharedConfig(environments=[Environment(name="prod", wait_timer=60)])

    changes = EnvironmentsManager().plan(repo, desired)
    changes[0].apply()

    call = repo.create_environment.call_args
    assert call.kwargs["wait_timer"] == 60
    assert call.kwargs["prevent_self_review"] is True
    assert (call.kwargs["reviewers"][0].type, call.kwargs["reviewers"][0].id) == ("User", 99)
    assert call.kwargs["deployment_branch_policy"].protected_branches is True
    assert call.kwargs["deployment_branch_policy"].custom_branch_policies is False


def test_existing_environment_reviewer_order_is_insensitive(repo: MagicMock) -> None:
    """Reviewers differing only in order are not treated as a change."""
    current = _make_environment(
        "prod", reviewers=[_reviewer_entry("User", 1), _reviewer_entry("Team", 2)]
    )
    repo.get_environments.return_value = [current]
    repo.requester.requestJsonAndCheck.side_effect = [({}, {"id": 2}), ({}, {"id": 1})]
    desired = SharedConfig(
        environments=[
            Environment(
                name="prod",
                reviewers=[Reviewer(type="Team", slug="sre"), Reviewer(type="User", login="a")],
            )
        ]
    )
    assert EnvironmentsManager().plan(repo, desired) == []


def test_existing_environment_secrets_diff(repo: MagicMock) -> None:
    """Existing-environment secrets/variables reuse the shared diff helpers with a prefix."""
    current = _make_environment("prod")
    current.get_secrets.return_value = []
    repo.get_environments.return_value = [current]
    desired = SharedConfig(
        environments=[Environment(name="prod", secrets=[Secret(name="NEW", value="v")])]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "environment:prod:secret:NEW"
    change.apply()
    current.create_secret.assert_called_once_with("NEW", "v")


def test_existing_environment_variables_diff(repo: MagicMock) -> None:
    """Existing-environment variables also reuse the shared diff helper with a prefix."""
    current = _make_environment("prod")
    repo.get_environments.return_value = [current]
    desired = SharedConfig(
        environments=[Environment(name="prod", variables=[Variable(name="REGION", value="eu")])]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "environment:prod:variable:REGION"
    change.apply()
    current.create_variable.assert_called_once_with("REGION", "eu")


def test_existing_environment_prevent_self_review_change(repo: MagicMock) -> None:
    """Explicitly setting prevent_self_review on an existing environment yields an UPDATE."""
    current = _make_environment("prod", prevent_self_review=False)
    repo.get_environments.return_value = [current]
    desired = SharedConfig(environments=[Environment(name="prod", prevent_self_review=True)])

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    assert repo.create_environment.call_args.kwargs["prevent_self_review"] is True


def test_unlisted_environment_is_deleted(repo: MagicMock) -> None:
    """A declared environments section is authoritative: an absent environment is deleted."""
    stale = _make_environment("staging")
    repo.get_environments.return_value = [stale]
    desired = SharedConfig(environments=[])

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "environment:staging"
    change.apply()
    repo.delete_environment.assert_called_once_with("staging")


def test_deployment_branch_policy_change(repo: MagicMock) -> None:
    """A differing deployment_branch_policy yields an UPDATE."""
    current = _make_environment(
        "prod", branch_policy={"protected_branches": False, "custom_branch_policies": False}
    )
    repo.get_environments.return_value = [current]
    desired = SharedConfig(
        environments=[
            Environment(
                name="prod",
                deployment_branch_policy=DeploymentBranchPolicy(custom_branch_policies=True),
            )
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    policy = repo.create_environment.call_args.kwargs["deployment_branch_policy"]
    assert policy.custom_branch_policies is True
    assert policy.protected_branches is False


def _policy_with_patterns(
    *patterns: tuple[str, Literal["branch", "tag"]],
) -> DeploymentBranchPolicy:
    return DeploymentBranchPolicy(
        custom_branch_policies=True,
        patterns=[DeploymentBranchPattern(name=name, type=type_) for name, type_ in patterns],
    )


def test_new_environment_pushes_declared_patterns(repo: MagicMock) -> None:
    """Creating an environment with custom patterns POSTs each after create_environment."""
    repo.url = URL
    repo.get_environments.return_value = []
    repo.create_environment.return_value = _make_environment("prod")
    desired = SharedConfig(
        environments=[
            Environment(name="prod", deployment_branch_policy=_policy_with_patterns(("v*", "tag")))
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    after = cast("dict[str, object]", change.after)
    assert after["patterns"] == [{"name": "v*", "type": "tag"}]
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "POST", _POLICIES, input={"name": "v*", "type": "tag"}
    )


def test_existing_environment_adds_pattern(repo: MagicMock) -> None:
    """A declared pattern absent from the environment's live set yields a pattern CREATE."""
    repo.url = URL
    current = _make_environment(
        "prod", branch_policy={"protected_branches": False, "custom_branch_policies": True}
    )
    repo.get_environments.return_value = [current]
    repo.requester.requestJsonAndCheck.return_value = ({}, {"branch_policies": []})
    desired = SharedConfig(
        environments=[
            Environment(name="prod", deployment_branch_policy=_policy_with_patterns(("v*", "tag")))
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "environment:prod:pattern:tag:v*"
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "POST", _POLICIES, input={"name": "v*", "type": "tag"}
    )


def test_existing_environment_removes_undeclared_pattern(repo: MagicMock) -> None:
    """A live pattern absent from the authoritative declared set yields a pattern DELETE."""
    repo.url = URL
    current = _make_environment(
        "prod", branch_policy={"protected_branches": False, "custom_branch_policies": True}
    )
    repo.get_environments.return_value = [current]
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"branch_policies": [{"id": 5, "name": "v*", "type": "tag"}]},
    )
    desired = SharedConfig(
        environments=[
            Environment(
                name="prod",
                deployment_branch_policy=DeploymentBranchPolicy(
                    custom_branch_policies=True, patterns=[]
                ),
            )
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "environment:prod:pattern:tag:v*"
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call("DELETE", f"{_POLICIES}/5")


def test_existing_environment_patterns_in_sync(repo: MagicMock) -> None:
    """A declared pattern set matching the live one yields no change."""
    repo.url = URL
    current = _make_environment(
        "prod", branch_policy={"protected_branches": False, "custom_branch_policies": True}
    )
    repo.get_environments.return_value = [current]
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"branch_policies": [{"id": 5, "name": "v*", "type": "tag"}]},
    )
    desired = SharedConfig(
        environments=[
            Environment(name="prod", deployment_branch_policy=_policy_with_patterns(("v*", "tag")))
        ]
    )
    assert EnvironmentsManager().plan(repo, desired) == []


def test_pattern_list_404_treated_as_empty(repo: MagicMock) -> None:
    """A 404 on the patterns read (custom policies not yet enabled) is an empty live set."""
    from github import GithubException  # noqa: PLC0415 — local to this narrow-scope test

    repo.url = URL
    current = _make_environment(
        "prod", branch_policy={"protected_branches": False, "custom_branch_policies": True}
    )
    repo.get_environments.return_value = [current]
    repo.requester.requestJsonAndCheck.side_effect = GithubException(404, {"message": "Not Found"})
    desired = SharedConfig(
        environments=[
            Environment(name="prod", deployment_branch_policy=_policy_with_patterns(("v*", "tag")))
        ]
    )

    changes = EnvironmentsManager().plan(repo, desired)

    assert [c.action for c in changes] == [Action.CREATE]


def test_pattern_list_non_404_propagates(repo: MagicMock) -> None:
    """A non-404 error on the patterns read surfaces rather than being swallowed as empty."""
    from github import GithubException  # noqa: PLC0415 — local to this narrow-scope test

    repo.url = URL
    current = _make_environment(
        "prod", branch_policy={"protected_branches": False, "custom_branch_policies": True}
    )
    repo.get_environments.return_value = [current]
    repo.requester.requestJsonAndCheck.side_effect = GithubException(500, {"message": "boom"})
    desired = SharedConfig(
        environments=[
            Environment(name="prod", deployment_branch_policy=_policy_with_patterns(("v*", "tag")))
        ]
    )

    with pytest.raises(GithubException):
        EnvironmentsManager().plan(repo, desired)
