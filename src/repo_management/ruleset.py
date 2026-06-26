# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Repository ruleset schema.

Models the full GitHub repository ruleset surface for branch/tag targets: every documented
rule type (as a ``type``-discriminated union), bypass actors, and ref-name conditions.

Field names mirror the GitHub REST API, so serialization is just pydantic's
``model_dump(exclude_none=True)`` — an unset optional field is omitted from the request
body. Rules wrap their fields in the API's ``{type, parameters}`` envelope via
:meth:`_Rule.to_api`; the only field whose name differs from its API key carries a
``serialization_alias``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from repo_management.base import Strict


class _ApiModel(Strict):
    """A model that renders to a GitHub API fragment by dumping its set fields."""

    def to_api(self) -> dict[str, Any]:
        """Render to the API shape, omitting unset optional fields."""
        return self.model_dump(by_alias=True, exclude_none=True)


class _Rule(Strict):
    """Base for a single ruleset rule. Subclasses narrow ``type`` to a literal."""

    type: str

    def to_api(self) -> dict[str, Any]:
        """Render the rule into the API's ``{type, parameters}`` envelope."""
        rule: dict[str, Any] = {"type": self.type}
        params = self.model_dump(by_alias=True, exclude_none=True, exclude={"type"})
        if params:
            rule["parameters"] = params
        return rule


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


class UpdateRule(_Rule):
    """The ``update`` rule (restrict branch updates)."""

    type: Literal["update"]
    update_allows_fetch_and_merge: bool = False


class PullRequestRule(_Rule):
    """The ``pull_request`` rule (required reviews and merge gating)."""

    type: Literal["pull_request"]
    required_approving_review_count: int = 0
    dismiss_stale_reviews_on_push: bool = False
    require_code_owner_review: bool = False
    require_last_push_approval: bool = False
    required_review_thread_resolution: bool = False
    allowed_merge_methods: list[Literal["merge", "squash", "rebase"]] | None = None


class StatusCheck(_ApiModel):
    """A required status check (a context, optionally bound to an integration)."""

    context: str
    integration_id: int | None = None


class RequiredStatusChecksRule(_Rule):
    """The ``required_status_checks`` rule."""

    type: Literal["required_status_checks"]
    required_checks: list[StatusCheck] = Field(
        default_factory=list,
        serialization_alias="required_status_checks",
    )
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


class RequiredDeploymentsRule(_Rule):
    """The ``required_deployments`` rule."""

    type: Literal["required_deployments"]
    required_deployment_environments: list[str] = Field(default_factory=list)


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


class FilePathRestrictionRule(_Rule):
    """The ``file_path_restriction`` rule."""

    type: Literal["file_path_restriction"]
    restricted_file_paths: list[str] = Field(default_factory=list)


class MaxFilePathLengthRule(_Rule):
    """The ``max_file_path_length`` rule."""

    type: Literal["max_file_path_length"]
    max_file_path_length: int


class FileExtensionRestrictionRule(_Rule):
    """The ``file_extension_restriction`` rule."""

    type: Literal["file_extension_restriction"]
    restricted_file_extensions: list[str] = Field(default_factory=list)


class MaxFileSizeRule(_Rule):
    """The ``max_file_size`` rule (megabytes)."""

    type: Literal["max_file_size"]
    max_file_size: int


class Workflow(_ApiModel):
    """A required workflow file reference."""

    repository_id: int
    path: str
    ref: str | None = None
    sha: str | None = None


class WorkflowsRule(_Rule):
    """The ``workflows`` rule (required workflows that must pass)."""

    type: Literal["workflows"]
    workflows: list[Workflow] = Field(default_factory=list)
    do_not_enforce_on_create: bool = False


class CodeScanningTool(_ApiModel):
    """A code-scanning tool threshold configuration."""

    tool: str
    security_alerts_threshold: str = "high_or_higher"
    alerts_threshold: str = "errors"


class CodeScanningRule(_Rule):
    """The ``code_scanning`` rule."""

    type: Literal["code_scanning"]
    code_scanning_tools: list[CodeScanningTool] = Field(default_factory=list)


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


class BypassActor(_ApiModel):
    """An actor allowed to bypass the ruleset."""

    actor_type: Literal["Integration", "OrganizationAdmin", "RepositoryRole", "Team", "DeployKey"]
    actor_id: int | None = None
    bypass_mode: Literal["always", "pull_request"] = "always"


class RefNameCondition(Strict):
    """Branch/tag name include & exclude patterns (e.g. ``~DEFAULT_BRANCH``, ``~ALL``)."""

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class Conditions(_ApiModel):
    """Conditions that select which refs a ruleset applies to."""

    ref_name: RefNameCondition = Field(default_factory=RefNameCondition)


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
