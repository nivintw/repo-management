# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Repository ruleset schema.

Models the full GitHub repository ruleset surface for branch/tag targets: every documented
rule type (as a ``type``-discriminated union), bypass actors, and ref-name conditions. Each
model knows how to render itself into the GitHub REST API's ``{type, parameters}`` shape via
``to_api`` so the manager can build request bodies directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from repo_management.base import Strict


class _Rule(Strict):
    """Base for a single ruleset rule. Subclasses narrow ``type`` to a literal."""

    type: str

    def to_api(self) -> dict[str, Any]:
        """Render the rule into the API's ``{type, parameters}`` shape."""
        rule: dict[str, Any] = {"type": self.type}
        params = self._parameters()
        if params:
            rule["parameters"] = params
        return rule

    def _parameters(self) -> dict[str, Any]:
        return {}


class SimpleRule(_Rule):
    """A parameterless rule (creation, deletion, linear history, etc.)."""

    type: Literal[
        "creation",
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "required_signatures",
    ]


class PatternRule(_Rule):
    """A name/email/branch/tag pattern rule sharing operator + pattern parameters."""

    type: Literal[
        "commit_message_pattern",
        "commit_author_email_pattern",
        "committer_email_pattern",
        "branch_name_pattern",
        "tag_name_pattern",
    ]
    operator: Literal["starts_with", "ends_with", "contains", "regex"]
    pattern: str
    name: str | None = None
    negate: bool = False

    def _parameters(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "operator": self.operator,
            "pattern": self.pattern,
            "negate": self.negate,
        }
        if self.name is not None:
            params["name"] = self.name
        return params


class UpdateRule(_Rule):
    """The ``update`` rule (restrict branch updates)."""

    type: Literal["update"]
    update_allows_fetch_and_merge: bool = False

    def _parameters(self) -> dict[str, Any]:
        return {"update_allows_fetch_and_merge": self.update_allows_fetch_and_merge}


class PullRequestRule(_Rule):
    """The ``pull_request`` rule (required reviews and merge gating)."""

    type: Literal["pull_request"]
    required_approving_review_count: int = 0
    dismiss_stale_reviews_on_push: bool = False
    require_code_owner_review: bool = False
    require_last_push_approval: bool = False
    required_review_thread_resolution: bool = False
    allowed_merge_methods: list[Literal["merge", "squash", "rebase"]] | None = None

    def _parameters(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "required_approving_review_count": self.required_approving_review_count,
            "dismiss_stale_reviews_on_push": self.dismiss_stale_reviews_on_push,
            "require_code_owner_review": self.require_code_owner_review,
            "require_last_push_approval": self.require_last_push_approval,
            "required_review_thread_resolution": self.required_review_thread_resolution,
        }
        if self.allowed_merge_methods is not None:
            params["allowed_merge_methods"] = self.allowed_merge_methods
        return params


class StatusCheck(Strict):
    """A required status check (a context, optionally bound to an integration)."""

    context: str
    integration_id: int | None = None

    def to_api(self) -> dict[str, Any]:
        """Render the check into the API shape, omitting an unset integration id."""
        check: dict[str, Any] = {"context": self.context}
        if self.integration_id is not None:
            check["integration_id"] = self.integration_id
        return check


class RequiredStatusChecksRule(_Rule):
    """The ``required_status_checks`` rule."""

    type: Literal["required_status_checks"]
    required_checks: list[StatusCheck] = Field(default_factory=list)
    strict_required_status_checks_policy: bool = False
    do_not_enforce_on_create: bool = False

    @field_validator("required_checks", mode="before")
    @classmethod
    def _coerce_strings(cls, value: object) -> object:
        # Allow the ergonomic `required_checks: [ci, lint]` form alongside the full
        # `{context, integration_id}` object form.
        if isinstance(value, list):
            return [{"context": item} if isinstance(item, str) else item for item in value]
        return value

    def _parameters(self) -> dict[str, Any]:
        return {
            "required_status_checks": [check.to_api() for check in self.required_checks],
            "strict_required_status_checks_policy": self.strict_required_status_checks_policy,
            "do_not_enforce_on_create": self.do_not_enforce_on_create,
        }


class RequiredDeploymentsRule(_Rule):
    """The ``required_deployments`` rule."""

    type: Literal["required_deployments"]
    required_deployment_environments: list[str] = Field(default_factory=list)

    def _parameters(self) -> dict[str, Any]:
        return {"required_deployment_environments": self.required_deployment_environments}


class MergeQueueRule(_Rule):
    """The ``merge_queue`` rule."""

    type: Literal["merge_queue"]
    check_response_timeout_minutes: int = 60
    grouping_strategy: Literal["ALLGREEN", "HEADGREEN"] = "ALLGREEN"
    max_entries_to_build: int = 5
    max_entries_to_merge: int = 5
    merge_method: Literal["MERGE", "SQUASH", "REBASE"] = "MERGE"
    min_entries_to_merge: int = 1
    min_entries_to_merge_wait_minutes: int = 5

    def _parameters(self) -> dict[str, Any]:
        return {
            "check_response_timeout_minutes": self.check_response_timeout_minutes,
            "grouping_strategy": self.grouping_strategy,
            "max_entries_to_build": self.max_entries_to_build,
            "max_entries_to_merge": self.max_entries_to_merge,
            "merge_method": self.merge_method,
            "min_entries_to_merge": self.min_entries_to_merge,
            "min_entries_to_merge_wait_minutes": self.min_entries_to_merge_wait_minutes,
        }


class FilePathRestrictionRule(_Rule):
    """The ``file_path_restriction`` rule."""

    type: Literal["file_path_restriction"]
    restricted_file_paths: list[str] = Field(default_factory=list)

    def _parameters(self) -> dict[str, Any]:
        return {"restricted_file_paths": self.restricted_file_paths}


class MaxFilePathLengthRule(_Rule):
    """The ``max_file_path_length`` rule."""

    type: Literal["max_file_path_length"]
    max_file_path_length: int

    def _parameters(self) -> dict[str, Any]:
        return {"max_file_path_length": self.max_file_path_length}


class FileExtensionRestrictionRule(_Rule):
    """The ``file_extension_restriction`` rule."""

    type: Literal["file_extension_restriction"]
    restricted_file_extensions: list[str] = Field(default_factory=list)

    def _parameters(self) -> dict[str, Any]:
        return {"restricted_file_extensions": self.restricted_file_extensions}


class MaxFileSizeRule(_Rule):
    """The ``max_file_size`` rule (megabytes)."""

    type: Literal["max_file_size"]
    max_file_size: int

    def _parameters(self) -> dict[str, Any]:
        return {"max_file_size": self.max_file_size}


class Workflow(Strict):
    """A required workflow file reference."""

    repository_id: int
    path: str
    ref: str | None = None
    sha: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Render the workflow reference, omitting unset ref/sha."""
        workflow: dict[str, Any] = {"repository_id": self.repository_id, "path": self.path}
        if self.ref is not None:
            workflow["ref"] = self.ref
        if self.sha is not None:
            workflow["sha"] = self.sha
        return workflow


class WorkflowsRule(_Rule):
    """The ``workflows`` rule (required workflows that must pass)."""

    type: Literal["workflows"]
    workflows: list[Workflow] = Field(default_factory=list)
    do_not_enforce_on_create: bool = False

    def _parameters(self) -> dict[str, Any]:
        return {
            "workflows": [workflow.to_api() for workflow in self.workflows],
            "do_not_enforce_on_create": self.do_not_enforce_on_create,
        }


class CodeScanningTool(Strict):
    """A code-scanning tool threshold configuration."""

    tool: str
    security_alerts_threshold: str = "high_or_higher"
    alerts_threshold: str = "errors"

    def to_api(self) -> dict[str, Any]:
        """Render the tool configuration into the API shape."""
        return {
            "tool": self.tool,
            "security_alerts_threshold": self.security_alerts_threshold,
            "alerts_threshold": self.alerts_threshold,
        }


class CodeScanningRule(_Rule):
    """The ``code_scanning`` rule."""

    type: Literal["code_scanning"]
    code_scanning_tools: list[CodeScanningTool] = Field(default_factory=list)

    def _parameters(self) -> dict[str, Any]:
        return {"code_scanning_tools": [tool.to_api() for tool in self.code_scanning_tools]}


Rule = Annotated[
    SimpleRule
    | PatternRule
    | UpdateRule
    | PullRequestRule
    | RequiredStatusChecksRule
    | RequiredDeploymentsRule
    | MergeQueueRule
    | FilePathRestrictionRule
    | MaxFilePathLengthRule
    | FileExtensionRestrictionRule
    | MaxFileSizeRule
    | WorkflowsRule
    | CodeScanningRule,
    Field(discriminator="type"),
]


class BypassActor(Strict):
    """An actor allowed to bypass the ruleset."""

    actor_type: Literal["Integration", "OrganizationAdmin", "RepositoryRole", "Team", "DeployKey"]
    actor_id: int | None = None
    bypass_mode: Literal["always", "pull_request"] = "always"

    def to_api(self) -> dict[str, Any]:
        """Render the bypass actor into the API shape."""
        actor: dict[str, Any] = {"actor_type": self.actor_type, "bypass_mode": self.bypass_mode}
        if self.actor_id is not None:
            actor["actor_id"] = self.actor_id
        return actor


class RefNameCondition(Strict):
    """Branch/tag name include & exclude patterns (e.g. ``~DEFAULT_BRANCH``, ``~ALL``)."""

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class Conditions(Strict):
    """Conditions that select which refs a ruleset applies to."""

    ref_name: RefNameCondition = Field(default_factory=RefNameCondition)

    def to_api(self) -> dict[str, Any]:
        """Render the conditions into the API shape."""
        return {"ref_name": {"include": self.ref_name.include, "exclude": self.ref_name.exclude}}


class Ruleset(Strict):
    """A repository ruleset, matched against existing rulesets by ``name``."""

    name: str
    target: Literal["branch", "tag"] = "branch"
    enforcement: Literal["active", "evaluate", "disabled"] = "active"
    bypass_actors: list[BypassActor] = Field(default_factory=list)
    conditions: Conditions = Field(default_factory=Conditions)
    rules: list[Rule] = Field(default_factory=list)

    def to_api(self) -> dict[str, Any]:
        """Render the whole ruleset into a GitHub REST API request body."""
        return {
            "name": self.name,
            "target": self.target,
            "enforcement": self.enforcement,
            "bypass_actors": [actor.to_api() for actor in self.bypass_actors],
            "conditions": self.conditions.to_api(),
            "rules": [rule.to_api() for rule in self.rules],
        }
