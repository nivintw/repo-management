# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Repository ruleset schema.

Models GitHub repository rulesets for branch, tag, and push targets: rule types (as a
``type``-discriminated union), bypass actors, and ref-name conditions.

The schema mirrors the GitHub REST API, field names and ``{type, parameters}`` rule envelope
included, so serialization is just pydantic's ``model_dump(exclude_none=True)``: an unset
optional field is omitted from the request body. Anything the API accepts here keeps the API's
spelling; conveniences are additions on top of it (a bare string for a required status check,
``actor_slug`` for a bypass actor), never replacements.

A rule's ``parameters`` defaults wherever every field in it has a default, so ``{type: update}``
is valid; a rule with a required field (a pattern, a size limit) requires ``parameters`` too.

GitHub partitions rule types by target: the four file-oriented rules
(``file_path_restriction``, ``max_file_path_length``, ``file_extension_restriction``,
``max_file_size``) attach only to a ``push`` ruleset, and every other rule type attaches only
to a ``branch``/``tag`` ruleset. :class:`Ruleset` enforces that partition at load time so an
invalid target/rule pairing fails fast rather than 422-ing at apply.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from repo_management.base import Strict


class _ApiModel(Strict):
    """A model that renders to a GitHub API fragment by dumping its set fields."""

    def to_api(self) -> dict[str, Any]:
        """Render to the API shape, omitting unset optional fields."""
        return self.model_dump(exclude_none=True)


class SimpleRule(_ApiModel):
    """A parameterless rule (creation, deletion, linear history, etc.)."""

    type: Literal[
        "creation",
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "required_signatures",
    ]


class PatternParameters(Strict):
    """Parameters shared by the name/email/branch/tag pattern rules."""

    operator: Literal["starts_with", "ends_with", "contains", "regex"]
    pattern: str
    name: str | None = None
    negate: bool = False


class PatternRule(_ApiModel):
    """A name/email/branch/tag pattern rule."""

    type: Literal[
        "commit_message_pattern",
        "commit_author_email_pattern",
        "committer_email_pattern",
        "branch_name_pattern",
        "tag_name_pattern",
    ]
    parameters: PatternParameters


class UpdateParameters(Strict):
    """Parameters of the ``update`` rule."""

    update_allows_fetch_and_merge: bool = False


class UpdateRule(_ApiModel):
    """The ``update`` rule (restrict branch updates)."""

    type: Literal["update"]
    parameters: UpdateParameters = Field(default_factory=UpdateParameters)


class PullRequestParameters(Strict):
    """Parameters of the ``pull_request`` rule."""

    required_approving_review_count: int = 0
    dismiss_stale_reviews_on_push: bool = False
    require_code_owner_review: bool = False
    require_last_push_approval: bool = False
    required_review_thread_resolution: bool = False
    allowed_merge_methods: list[Literal["merge", "squash", "rebase"]] | None = None


class PullRequestRule(_ApiModel):
    """The ``pull_request`` rule (required reviews and merge gating)."""

    type: Literal["pull_request"]
    parameters: PullRequestParameters = Field(default_factory=PullRequestParameters)


class StatusCheck(Strict):
    """A required status check (a context, optionally bound to an integration)."""

    context: str
    integration_id: int | None = None


class RequiredStatusChecksParameters(Strict):
    """Parameters of the ``required_status_checks`` rule."""

    required_status_checks: list[StatusCheck] = Field(default_factory=list)
    strict_required_status_checks_policy: bool = False
    do_not_enforce_on_create: bool = False

    @field_validator("required_status_checks", mode="before")
    @classmethod
    def _coerce_strings(cls, value: object) -> object:
        # Accept the shorthand `required_status_checks: [ci, lint]` alongside the API's
        # `{context, integration_id}` object form.
        if isinstance(value, list):
            return [{"context": item} if isinstance(item, str) else item for item in value]
        return value


class RequiredStatusChecksRule(_ApiModel):
    """The ``required_status_checks`` rule."""

    type: Literal["required_status_checks"]
    parameters: RequiredStatusChecksParameters = Field(
        default_factory=RequiredStatusChecksParameters
    )


class RequiredDeploymentsParameters(Strict):
    """Parameters of the ``required_deployments`` rule."""

    required_deployment_environments: list[str] = Field(default_factory=list)


class RequiredDeploymentsRule(_ApiModel):
    """The ``required_deployments`` rule."""

    type: Literal["required_deployments"]
    parameters: RequiredDeploymentsParameters = Field(default_factory=RequiredDeploymentsParameters)


class MergeQueueParameters(Strict):
    """Parameters of the ``merge_queue`` rule."""

    check_response_timeout_minutes: int = 60
    grouping_strategy: Literal["ALLGREEN", "HEADGREEN"] = "ALLGREEN"
    max_entries_to_build: int = 5
    max_entries_to_merge: int = 5
    merge_method: Literal["MERGE", "SQUASH", "REBASE"] = "MERGE"
    min_entries_to_merge: int = 1
    min_entries_to_merge_wait_minutes: int = 5


class MergeQueueRule(_ApiModel):
    """The ``merge_queue`` rule."""

    type: Literal["merge_queue"]
    parameters: MergeQueueParameters = Field(default_factory=MergeQueueParameters)


class FilePathRestrictionParameters(Strict):
    """Parameters of the ``file_path_restriction`` rule."""

    restricted_file_paths: list[str] = Field(default_factory=list)


class FilePathRestrictionRule(_ApiModel):
    """The ``file_path_restriction`` rule."""

    type: Literal["file_path_restriction"]
    parameters: FilePathRestrictionParameters = Field(default_factory=FilePathRestrictionParameters)


class MaxFilePathLengthParameters(Strict):
    """Parameters of the ``max_file_path_length`` rule."""

    max_file_path_length: int


class MaxFilePathLengthRule(_ApiModel):
    """The ``max_file_path_length`` rule."""

    type: Literal["max_file_path_length"]
    parameters: MaxFilePathLengthParameters


class FileExtensionRestrictionParameters(Strict):
    """Parameters of the ``file_extension_restriction`` rule."""

    restricted_file_extensions: list[str] = Field(default_factory=list)


class FileExtensionRestrictionRule(_ApiModel):
    """The ``file_extension_restriction`` rule."""

    type: Literal["file_extension_restriction"]
    parameters: FileExtensionRestrictionParameters = Field(
        default_factory=FileExtensionRestrictionParameters
    )


class MaxFileSizeParameters(Strict):
    """Parameters of the ``max_file_size`` rule (megabytes)."""

    max_file_size: int


class MaxFileSizeRule(_ApiModel):
    """The ``max_file_size`` rule."""

    type: Literal["max_file_size"]
    parameters: MaxFileSizeParameters


class Workflow(Strict):
    """A required workflow file reference."""

    repository_id: int
    path: str
    ref: str | None = None
    sha: str | None = None


class WorkflowsParameters(Strict):
    """Parameters of the ``workflows`` rule."""

    workflows: list[Workflow] = Field(default_factory=list)
    do_not_enforce_on_create: bool = False


class WorkflowsRule(_ApiModel):
    """The ``workflows`` rule (required workflows that must pass)."""

    type: Literal["workflows"]
    parameters: WorkflowsParameters = Field(default_factory=WorkflowsParameters)


class CodeScanningTool(Strict):
    """A code-scanning tool threshold configuration."""

    tool: str
    security_alerts_threshold: str = "high_or_higher"
    alerts_threshold: str = "errors"


class CodeScanningParameters(Strict):
    """Parameters of the ``code_scanning`` rule."""

    code_scanning_tools: list[CodeScanningTool] = Field(default_factory=list)


class CodeScanningRule(_ApiModel):
    """The ``code_scanning`` rule."""

    type: Literal["code_scanning"]
    parameters: CodeScanningParameters = Field(default_factory=CodeScanningParameters)


class CopilotCodeReviewParameters(Strict):
    """Parameters of the ``copilot_code_review`` rule."""

    review_on_push: bool = False
    review_draft_pull_requests: bool = False


class CopilotCodeReviewRule(_ApiModel):
    """The ``copilot_code_review`` rule (automatic Copilot review on the PR flow).

    Supersedes the deprecated ``automatic_copilot_code_review_enabled`` parameter that used
    to hang off the ``pull_request`` rule; it is a branch-target rule.
    """

    type: Literal["copilot_code_review"]
    parameters: CopilotCodeReviewParameters = Field(default_factory=CopilotCodeReviewParameters)


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


# Bypass-actor types that require a concrete numeric ``actor_id`` — an App id, role id, or team
# id respectively — which may be given literally (``actor_id``) or resolved from a human-readable
# ``actor_slug``. ``OrganizationAdmin`` ignores ``actor_id`` and ``DeployKey`` forbids it (neither
# has a slug to resolve), both handled explicitly below. Partition confirmed against GitHub's
# rulesets REST docs: "Required for Integration, RepositoryRole, Team, and User actor types. If
# actor_type is OrganizationAdmin, actor_id is ignored. If actor_type is DeployKey, this should
# be null."
_ACTOR_ID_REQUIRED = frozenset({"Integration", "RepositoryRole", "Team"})

# Resolves a bypass actor's (actor_type, slug) to the numeric actor_id GitHub's API expects.
# The rulesets manager supplies one backed by live API lookups; ``to_api`` calls it only for an
# actor that carries an ``actor_slug``.
BypassActorIdResolver = Callable[[str, str], int]


class BypassActor(_ApiModel):
    """An actor allowed to bypass the ruleset.

    GitHub pairs ``actor_id`` with ``actor_type``: ``Integration``/``RepositoryRole``/``Team``
    each need a concrete id, ``DeployKey`` must not carry one, and ``OrganizationAdmin`` ignores
    it (any value or none is accepted). The combinations GitHub's API rejects are rejected here
    at load rather than left to 422 at apply.

    An id-requiring actor may instead be named by ``actor_slug`` — an App slug, team slug, or
    (custom) repository-role name — which is resolved to its ``actor_id`` at plan time, so a human
    never has to hand-write an opaque numeric id. Exactly one of ``actor_id``/``actor_slug`` is
    set for those types; the slug never reaches GitHub (``to_api`` resolves it away).
    """

    actor_type: Literal["Integration", "OrganizationAdmin", "RepositoryRole", "Team", "DeployKey"]
    actor_id: int | None = None
    actor_slug: str | None = None
    bypass_mode: Literal["always", "pull_request"] = "always"

    @field_validator("actor_slug")
    @classmethod
    def _slug_is_a_clean_segment(cls, value: str | None) -> str | None:
        # Reject at load what would otherwise resolve wrong at plan: an empty slug (issues a
        # malformed `/apps/` request) and a slug carrying a path separator or newline. The latter
        # matters because the resolver interpolates the slug into an API path — a value like
        # `../../orgs/other/teams/admins` could otherwise traverse to a *different* org's team and
        # silently install the wrong bypass id (a security control). Role *names* may contain
        # spaces, so only '/', CR, and LF are forbidden, not all whitespace.
        if value is None:
            return value
        if not value.strip():
            msg = "'actor_slug' must not be empty"
            raise ValueError(msg)
        if any(char in value for char in "/\r\n"):
            msg = "'actor_slug' must not contain '/', a carriage return, or a newline"
            raise ValueError(msg)
        # Percent-encoding leaves dots alone, so a dot segment would still change the path.
        if value in {".", ".."}:
            msg = "'actor_slug' must not be '.' or '..'"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _actor_id_matches_type(self) -> BypassActor:
        if self.actor_type == "DeployKey":
            if self.actor_id is not None or self.actor_slug is not None:
                msg = "a 'DeployKey' bypass actor takes neither 'actor_id' nor 'actor_slug'"
                raise ValueError(msg)
        elif self.actor_type == "OrganizationAdmin":
            # OrganizationAdmin ignores actor_id and has no slug to resolve.
            if self.actor_slug is not None:
                msg = "an 'OrganizationAdmin' bypass actor does not take 'actor_slug'"
                raise ValueError(msg)
        elif (self.actor_id is None) == (self.actor_slug is None):
            # Integration/RepositoryRole/Team: exactly one of actor_id / actor_slug.
            msg = (
                f"a {self.actor_type!r} bypass actor requires exactly one of "
                "'actor_id' or 'actor_slug'"
            )
            raise ValueError(msg)
        return self

    def to_api(self, resolve_slug: BypassActorIdResolver | None = None) -> dict[str, Any]:
        """Render to the API shape, resolving ``actor_slug`` to a concrete ``actor_id``.

        ``actor_slug`` is never sent to GitHub: when set, it's replaced by the ``actor_id`` the
        resolver returns. A resolver is required iff this actor carries a slug.
        """
        # Reuse the base render, then swap our config-only actor_slug for the resolved actor_id.
        data = super().to_api()
        data.pop("actor_slug", None)
        if self.actor_slug is not None:
            if resolve_slug is None:
                msg = f"resolving bypass actor slug {self.actor_slug!r} needs a resolver"
                raise ValueError(msg)
            data["actor_id"] = resolve_slug(self.actor_type, self.actor_slug)
        return data


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

    def to_api(self, resolve_slug: BypassActorIdResolver | None = None) -> dict[str, Any]:
        """Render the whole ruleset into a GitHub REST API request body.

        ``resolve_slug`` is threaded to each bypass actor to turn an ``actor_slug`` into its
        numeric ``actor_id`` (see :meth:`BypassActor.to_api`); it's only invoked for actors that
        carry a slug.
        """
        # A push ruleset carries no ref_name conditions (validated above), so it renders an
        # empty conditions object rather than the branch/tag include/exclude shape.
        conditions = {} if self.target == "push" else self.conditions.to_api()
        return {
            "name": self.name,
            "target": self.target,
            "enforcement": self.enforcement,
            "bypass_actors": [actor.to_api(resolve_slug) for actor in self.bypass_actors],
            "conditions": conditions,
            "rules": [rule.to_api() for rule in self.rules],
        }
