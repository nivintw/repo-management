# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Repository ruleset schema.

Models the full GitHub repository ruleset surface for branch, tag, and push targets: every
documented rule type (as a ``type``-discriminated union), bypass actors, and ref-name
conditions.

Field names mirror the GitHub REST API, so serialization is just pydantic's
``model_dump(exclude_none=True)`` — an unset optional field is omitted from the request
body. Rules wrap their fields in the API's ``{type, parameters}`` envelope via
:meth:`_Rule.to_api`; the only field whose name differs from its API key carries a
``serialization_alias``.

GitHub partitions rule types by target: the four file-oriented rules
(``file_path_restriction``, ``max_file_path_length``, ``file_extension_restriction``,
``max_file_size``) attach only to a ``push`` ruleset, and every other rule type attaches only
to a ``branch``/``tag`` ruleset. :class:`Ruleset` enforces that partition at load time so an
invalid target/rule pairing fails fast rather than 422-ing at apply.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

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


class CopilotCodeReviewRule(_Rule):
    """The ``copilot_code_review`` rule (automatic Copilot review on the PR flow).

    Supersedes the deprecated ``automatic_copilot_code_review_enabled`` parameter that used
    to hang off the ``pull_request`` rule; it is a branch-target rule.
    """

    type: Literal["copilot_code_review"]
    review_on_push: bool = False
    review_draft_pull_requests: bool = False


# The four file-oriented rule types GitHub accepts only on a ``push`` ruleset. Every other
# rule type is branch/tag-only. :class:`Ruleset` enforces this partition at load.
PUSH_ONLY_RULE_TYPES = frozenset(
    {
        "file_path_restriction",
        "max_file_path_length",
        "file_extension_restriction",
        "max_file_size",
    }
)


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
    | CodeScanningRule
    | CopilotCodeReviewRule,
    Field(discriminator="type"),
]


# Bypass-actor types that require a concrete numeric ``actor_id`` (an App id, role id, or
# team id respectively). ``OrganizationAdmin`` ignores ``actor_id`` and ``DeployKey`` forbids
# it — both handled explicitly below. Partition confirmed against GitHub's rulesets REST docs:
# "Required for Integration, RepositoryRole, Team, and User actor types. If actor_type is
# OrganizationAdmin, actor_id is ignored. If actor_type is DeployKey, this should be null."
_ACTOR_ID_REQUIRED = frozenset({"Integration", "RepositoryRole", "Team"})


class BypassActor(_ApiModel):
    """An actor allowed to bypass the ruleset.

    GitHub pairs ``actor_id`` with ``actor_type``: ``Integration``/``RepositoryRole``/``Team``
    each need a concrete id, ``DeployKey`` must not carry one, and ``OrganizationAdmin`` ignores
    it (any value or none is accepted). The combinations GitHub's API rejects are rejected here
    at load rather than left to 422 at apply.
    """

    actor_type: Literal["Integration", "OrganizationAdmin", "RepositoryRole", "Team", "DeployKey"]
    actor_id: int | None = None
    bypass_mode: Literal["always", "pull_request"] = "always"

    @model_validator(mode="after")
    def _actor_id_matches_type(self) -> BypassActor:
        if self.actor_type == "DeployKey":
            if self.actor_id is not None:
                msg = "a 'DeployKey' bypass actor must not set 'actor_id'"
                raise ValueError(msg)
        elif self.actor_type in _ACTOR_ID_REQUIRED and self.actor_id is None:
            # OrganizationAdmin ignores actor_id, so it falls through with no constraint.
            msg = f"a {self.actor_type!r} bypass actor requires 'actor_id'"
            raise ValueError(msg)
        return self


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
    target: Literal["branch", "tag", "push"] = "branch"
    enforcement: Literal["active", "evaluate", "disabled"] = "active"
    bypass_actors: list[BypassActor] = Field(default_factory=list)
    conditions: Conditions = Field(default_factory=Conditions)
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _target_rule_partition(self) -> Ruleset:
        # GitHub accepts the four file-oriented rule types only on a push ruleset, and every
        # other rule type only on a branch/tag ruleset — enforce that split at load rather
        # than let an invalid pairing 422 at apply.
        if self.target == "push":
            offenders = sorted({rule.type for rule in self.rules} - PUSH_ONLY_RULE_TYPES)
            if offenders:
                msg = (
                    f"a push ruleset accepts only {sorted(PUSH_ONLY_RULE_TYPES)}; "
                    f"rule type(s) {offenders} require a branch/tag target"
                )
                raise ValueError(msg)
            # Push rulesets don't select refs — a ref_name condition is rejected by the API.
            if self.conditions.ref_name.include or self.conditions.ref_name.exclude:
                msg = "a push ruleset must not set 'conditions.ref_name'"
                raise ValueError(msg)
        else:
            offenders = sorted({rule.type for rule in self.rules} & PUSH_ONLY_RULE_TYPES)
            if offenders:
                msg = (
                    f"rule type(s) {offenders} require 'target: push'; "
                    f"they can't attach to a {self.target!r} ruleset"
                )
                raise ValueError(msg)
        return self

    def to_api(self) -> dict[str, Any]:
        """Render the whole ruleset into a GitHub REST API request body."""
        # A push ruleset carries no ref_name conditions (validated above), so it renders an
        # empty conditions object rather than the branch/tag include/exclude shape.
        conditions = {} if self.target == "push" else self.conditions.to_api()
        return {
            "name": self.name,
            "target": self.target,
            "enforcement": self.enforcement,
            "bypass_actors": [actor.to_api() for actor in self.bypass_actors],
            "conditions": conditions,
            "rules": [rule.to_api() for rule in self.rules],
        }
