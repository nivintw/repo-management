# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the ruleset schema and its API translation."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from repo_management.ruleset import (
    BypassActor,
    CodeScanningRule,
    Conditions,
    CopilotCodeReviewRule,
    FileExtensionRestrictionRule,
    FilePathRestrictionRule,
    MaxFilePathLengthRule,
    MaxFileSizeRule,
    MergeQueueRule,
    PatternRule,
    PullRequestRule,
    RequiredDeploymentsRule,
    RequiredStatusChecksRule,
    Rule,
    Ruleset,
    SimpleRule,
    UpdateRule,
    WorkflowsRule,
)


def test_simple_rule_has_no_parameters() -> None:
    """A parameterless rule renders as just a type."""
    rule = SimpleRule(type="required_linear_history")
    assert rule.to_api() == {"type": "required_linear_history"}


def test_pattern_rule() -> None:
    """A pattern rule renders operator/pattern/negate, and name only when set."""
    rule = PatternRule(type="branch_name_pattern", operator="starts_with", pattern="rel/")
    assert rule.to_api() == {
        "type": "branch_name_pattern",
        "parameters": {"operator": "starts_with", "pattern": "rel/", "negate": False},
    }
    named = PatternRule(type="commit_message_pattern", operator="regex", pattern="x", name="n")
    assert named.to_api()["parameters"]["name"] == "n"


def test_pull_request_rule() -> None:
    """The pull_request rule renders all review parameters."""
    params = PullRequestRule(type="pull_request", required_approving_review_count=2).to_api()[
        "parameters"
    ]
    assert params["required_approving_review_count"] == 2
    assert params["require_code_owner_review"] is False


def test_status_checks_string_coercion() -> None:
    """required_checks accepts plain strings and the {context, integration_id} form."""
    rule = RequiredStatusChecksRule.model_validate(
        {
            "type": "required_status_checks",
            "required_checks": ["ci", {"context": "lint", "integration_id": 7}],
        },
    )
    checks = rule.to_api()["parameters"]["required_status_checks"]
    assert checks == [{"context": "ci"}, {"context": "lint", "integration_id": 7}]


def test_workflows_rule() -> None:
    """The workflows rule renders workflow references, omitting unset ref/sha."""
    rule = WorkflowsRule.model_validate(
        {"type": "workflows", "workflows": [{"repository_id": 1, "path": "ci.yml"}]},
    )
    assert rule.to_api()["parameters"]["workflows"] == [{"repository_id": 1, "path": "ci.yml"}]


def test_max_file_size_rule() -> None:
    """A scalar-parameter rule renders its single parameter."""
    rule = MaxFileSizeRule(type="max_file_size", max_file_size=100)
    assert rule.to_api() == {"type": "max_file_size", "parameters": {"max_file_size": 100}}


def test_update_rule() -> None:
    """The update rule renders its fetch-and-merge flag."""
    assert UpdateRule(type="update").to_api() == {
        "type": "update",
        "parameters": {"update_allows_fetch_and_merge": False},
    }


def test_pull_request_allowed_merge_methods() -> None:
    """allowed_merge_methods is included only when set."""
    rule = PullRequestRule(type="pull_request", allowed_merge_methods=["squash"])
    assert rule.to_api()["parameters"]["allowed_merge_methods"] == ["squash"]


def test_required_deployments_rule() -> None:
    """The required_deployments rule renders its environment list."""
    rule = RequiredDeploymentsRule(
        type="required_deployments",
        required_deployment_environments=["prod"],
    )
    assert rule.to_api()["parameters"] == {"required_deployment_environments": ["prod"]}


def test_merge_queue_rule() -> None:
    """The merge_queue rule renders its parameters."""
    params = MergeQueueRule(type="merge_queue", merge_method="SQUASH").to_api()["parameters"]
    assert params["merge_method"] == "SQUASH"
    assert params["grouping_strategy"] == "ALLGREEN"


def test_file_rules() -> None:
    """The file-path/extension/length rules render their parameters."""
    assert FilePathRestrictionRule(
        type="file_path_restriction",
        restricted_file_paths=["secrets/*"],
    ).to_api()["parameters"] == {"restricted_file_paths": ["secrets/*"]}
    assert MaxFilePathLengthRule(type="max_file_path_length", max_file_path_length=200).to_api()[
        "parameters"
    ] == {"max_file_path_length": 200}
    assert FileExtensionRestrictionRule(
        type="file_extension_restriction",
        restricted_file_extensions=[".exe"],
    ).to_api()["parameters"] == {"restricted_file_extensions": [".exe"]}


def test_workflow_ref_and_sha() -> None:
    """A workflow reference includes ref/sha when set."""
    rule = WorkflowsRule.model_validate(
        {
            "type": "workflows",
            "workflows": [
                {"repository_id": 1, "path": "ci.yml", "ref": "refs/heads/main", "sha": "abc"},
            ],
        },
    )
    workflow = rule.to_api()["parameters"]["workflows"][0]
    assert workflow["ref"] == "refs/heads/main"
    assert workflow["sha"] == "abc"


def test_code_scanning_rule() -> None:
    """The code_scanning rule renders its tool thresholds."""
    rule = CodeScanningRule.model_validate(
        {"type": "code_scanning", "code_scanning_tools": [{"tool": "CodeQL"}]},
    )
    tool = rule.to_api()["parameters"]["code_scanning_tools"][0]
    assert tool == {
        "tool": "CodeQL",
        "security_alerts_threshold": "high_or_higher",
        "alerts_threshold": "errors",
    }


def test_status_checks_non_list_rejected() -> None:
    """A non-list required_checks is passed through the coercer and then rejected."""
    with pytest.raises(ValidationError):
        RequiredStatusChecksRule.model_validate(
            {"type": "required_status_checks", "required_checks": "ci"},
        )


def test_unknown_rule_type_rejected() -> None:
    """An unknown rule type fails discriminated-union validation."""
    adapter: TypeAdapter[object] = TypeAdapter(Rule)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "made_up_rule"})


def test_bypass_actor() -> None:
    """A bypass actor renders type/mode, and actor_id only when set."""
    assert BypassActor(actor_type="OrganizationAdmin").to_api() == {
        "actor_type": "OrganizationAdmin",
        "bypass_mode": "always",
    }
    assert BypassActor(actor_type="Team", actor_id=5, bypass_mode="pull_request").to_api() == {
        "actor_type": "Team",
        "bypass_mode": "pull_request",
        "actor_id": 5,
    }


def test_copilot_code_review_rule() -> None:
    """The copilot_code_review rule renders its two boolean parameters."""
    rule = CopilotCodeReviewRule(
        type="copilot_code_review",
        review_on_push=True,
        review_draft_pull_requests=True,
    )
    assert rule.to_api() == {
        "type": "copilot_code_review",
        "parameters": {"review_on_push": True, "review_draft_pull_requests": True},
    }


def test_copilot_code_review_rule_via_union() -> None:
    """copilot_code_review is a first-class member of the discriminated Rule union."""
    adapter: TypeAdapter[object] = TypeAdapter(Rule)
    rule = adapter.validate_python({"type": "copilot_code_review", "review_on_push": True})
    assert isinstance(rule, CopilotCodeReviewRule)


def test_push_ruleset_valid() -> None:
    """A push ruleset carrying only push-only rules loads and renders empty conditions."""
    ruleset = Ruleset.model_validate(
        {
            "name": "no-binaries",
            "target": "push",
            "rules": [
                {"type": "file_extension_restriction", "restricted_file_extensions": [".exe"]}
            ],
        },
    )
    body = ruleset.to_api()
    assert body["target"] == "push"
    assert body["conditions"] == {}
    assert body["rules"] == [
        {
            "type": "file_extension_restriction",
            "parameters": {"restricted_file_extensions": [".exe"]},
        },
    ]


def test_push_only_rule_rejected_on_branch_target() -> None:
    """A push-only rule attached to a branch target is a load-time error, not an apply 422."""
    with pytest.raises(ValidationError, match="require 'target: push'"):
        Ruleset.model_validate(
            {
                "name": "bad",
                "target": "branch",
                "rules": [{"type": "max_file_size", "max_file_size": 100}],
            },
        )


def test_branch_rule_rejected_on_push_target() -> None:
    """A branch/tag rule attached to a push target is a load-time error."""
    with pytest.raises(ValidationError, match="require a branch/tag target"):
        Ruleset.model_validate(
            {"name": "bad", "target": "push", "rules": [{"type": "non_fast_forward"}]},
        )


def test_push_ruleset_rejects_ref_name_condition() -> None:
    """A push ruleset selects no refs, so a ref_name condition is rejected at load."""
    with pytest.raises(ValidationError, match=r"must not set 'conditions\.ref_name'"):
        Ruleset.model_validate(
            {
                "name": "bad",
                "target": "push",
                "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
                "rules": [{"type": "max_file_size", "max_file_size": 100}],
            },
        )


def test_bypass_actor_deploy_key_rejects_actor_id() -> None:
    """A DeployKey bypass actor must not carry an actor_id."""
    with pytest.raises(ValidationError, match="'DeployKey' bypass actor must not set 'actor_id'"):
        BypassActor(actor_type="DeployKey", actor_id=5)


@pytest.mark.parametrize("actor_type", ["Integration", "RepositoryRole", "Team"])
def test_bypass_actor_requires_actor_id(actor_type: str) -> None:
    """Integration/RepositoryRole/Team each require a concrete actor_id."""
    with pytest.raises(ValidationError, match="requires 'actor_id'"):
        BypassActor.model_validate({"actor_type": actor_type})


def test_bypass_actor_org_admin_ignores_actor_id() -> None:
    """OrganizationAdmin ignores actor_id: both an absent and a present id load."""
    assert BypassActor(actor_type="OrganizationAdmin").actor_id is None
    assert BypassActor(actor_type="OrganizationAdmin", actor_id=1).actor_id == 1


def test_conditions_default() -> None:
    """Conditions render include/exclude ref-name lists."""
    assert Conditions().to_api() == {"ref_name": {"include": [], "exclude": []}}


def test_ruleset_to_api_full() -> None:
    """A whole ruleset renders into a complete API body."""
    ruleset = Ruleset.model_validate(
        {
            "name": "main",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "bypass_actors": [{"actor_type": "OrganizationAdmin"}],
            "rules": [{"type": "non_fast_forward"}],
        },
    )
    body = ruleset.to_api()
    assert body["name"] == "main"
    assert body["target"] == "branch"
    assert body["enforcement"] == "active"
    assert body["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    assert body["rules"] == [{"type": "non_fast_forward"}]
    assert body["bypass_actors"] == [{"actor_type": "OrganizationAdmin", "bypass_mode": "always"}]
