# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Configuration schema and loading.

A config file lists the repositories to manage (`repos:`) and a single shared block of
config sections applied to every one of them. A file may `extends:` one or more base files
that are merged underneath it: scalars from the override win, and list sections merge by
each item's natural key (so a same-key item in the override replaces the base's item and
new items are appended).

Each declared section is *authoritative*: it is the complete desired set, so items present
on the repo but absent from the section are removed. A section left unset is *unmanaged* —
the reconciler leaves that whole domain untouched.
"""

from __future__ import annotations

import copy
import os
import re
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from repo_management.base import Strict
from repo_management.ruleset import Ruleset

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

Permission = Literal["pull", "triage", "push", "maintain", "admin"]

# GitHub login / team-slug charset: alphanumeric and hyphens, no leading/trailing hyphen.
# Rejects '/' in particular -- a Reviewer's login/slug is interpolated directly into a raw
# REST path (see managers/environments.py), so this is a hard boundary against a crafted
# value redirecting that request to an unintended API path.
_GITHUB_IDENTIFIER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")

_DEPLOY_KEY_FIELDS = 2  # algorithm + base64 body; an optional trailing comment is field 3+.


def normalize_deploy_key(key: str) -> str:
    """The algorithm and base64 body only, dropping an optional trailing comment.

    ``ssh-keygen``'s default output always appends a ``user@host``-style comment, and a
    YAML block scalar can introduce trailing whitespace -- neither is part of a deploy
    key's real identity. Shared by ``managers/deploy_keys.py`` (matching against live
    GitHub state) and the ``extends:`` merge below, so two config entries differing only
    by comment/whitespace can't survive a merge as if they were different keys.
    """
    parts = key.split()
    return " ".join(parts[:_DEPLOY_KEY_FIELDS]) if len(parts) >= _DEPLOY_KEY_FIELDS else key.strip()


# Section path -> the field that identifies an item, for by-key list merges.
_KEYED_LISTS: dict[tuple[str, ...], str] = {
    ("rulesets",): "name",
    ("labels",): "name",
    ("collaborators",): "username",
    ("teams",): "slug",
    ("codeowners",): "pattern",
    ("webhooks",): "url",
    ("secrets",): "name",
    ("variables",): "name",
    ("deploy_keys",): "key",
    ("autolinks",): "key_prefix",
    ("environments",): "name",
}

# Section path -> a normalizer for its keyed-merge field, for sections whose live-API
# identity differs from the literal config string. Absent from this map means the raw
# string is the identity (the common case).
_KEY_NORMALIZERS: dict[tuple[str, ...], Callable[[str], str]] = {
    ("deploy_keys",): normalize_deploy_key,
}


class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded or validated."""


class Settings(Strict):
    """Repository settings and merge options. Unset fields are left unmanaged."""

    description: str | None = None
    homepage: str | None = None
    private: bool | None = None
    # Enterprise orgs have a third visibility tier, ``internal``, that ``private: bool`` can't
    # express. Set ``visibility`` for the three-way (``public``/``private``/``internal``); it's
    # mutually exclusive with ``private`` (setting both is rejected below). A personal-account
    # repo can't be ``internal``, so ``private`` remains the natural choice there.
    visibility: Literal["public", "private", "internal"] | None = None
    topics: list[str] | None = None
    has_issues: bool | None = None
    has_wiki: bool | None = None
    has_projects: bool | None = None
    has_discussions: bool | None = None
    default_branch: str | None = None
    allow_squash_merge: bool | None = None
    allow_merge_commit: bool | None = None
    allow_rebase_merge: bool | None = None
    allow_auto_merge: bool | None = None
    delete_branch_on_merge: bool | None = None
    allow_update_branch: bool | None = None
    squash_merge_commit_title: Literal["PR_TITLE", "COMMIT_OR_PR_TITLE"] | None = None
    squash_merge_commit_message: Literal["PR_BODY", "COMMIT_MESSAGES", "BLANK"] | None = None
    merge_commit_title: Literal["PR_TITLE", "MERGE_MESSAGE"] | None = None
    merge_commit_message: Literal["PR_BODY", "PR_TITLE", "BLANK"] | None = None
    web_commit_signoff_required: bool | None = None
    is_template: bool | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def _visibility_xor_private(self) -> Settings:
        # ``visibility`` supersedes ``private`` (it can also express ``internal``); declaring
        # both invites an incoherent pair (e.g. ``private: false`` + ``visibility: private``),
        # so exactly-one-or-neither is enforced here rather than left to an apply-time surprise.
        if self.private is not None and self.visibility is not None:
            msg = "set only one of 'private' or 'visibility'"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _paired_merge_commit_fields(self) -> Settings:
        # GitHub's API requires each *_title field whenever its *_message counterpart is
        # set (the reverse isn't required): a title alone just sets a preference for when
        # the merge type is later enabled, but a message without its title is rejected.
        if self.squash_merge_commit_message is not None and self.squash_merge_commit_title is None:
            msg = (
                "'squash_merge_commit_title' is required when 'squash_merge_commit_message' is set"
            )
            raise ValueError(msg)
        if self.merge_commit_message is not None and self.merge_commit_title is None:
            msg = "'merge_commit_title' is required when 'merge_commit_message' is set"
            raise ValueError(msg)
        return self


class Label(Strict):
    """A repository issue/PR label.

    ``description`` is unmanaged when omitted (left as-is on GitHub); set it to manage it.
    """

    name: str
    color: str = "ededed"
    description: str | None = None

    @field_validator("color")
    @classmethod
    def _normalize_color(cls, value: str) -> str:
        # GitHub stores hex colors lowercased and without a leading '#'.
        return value.lstrip("#").lower()


class Collaborator(Strict):
    """A repository collaborator and their permission level."""

    username: str
    permission: Permission = "push"


class Webhook(Strict):
    """A repository webhook, matched against existing hooks by ``url``."""

    url: str
    events: list[str] = Field(default_factory=lambda: ["push"])
    active: bool = True
    content_type: Literal["json", "form"] = "json"
    insecure_ssl: bool = False
    secret_from_env: str | None = None

    def resolve_secret(self) -> str | None:
        """Return the webhook secret from the environment, or ``None`` if unset."""
        if self.secret_from_env is None:
            return None
        return _require_env(self.secret_from_env)


class DeployKey(Strict):
    """A repository deploy key, matched against existing keys by ``key`` content.

    GitHub's deploy-key API has no update endpoint: a key whose ``title``/``read_only``
    changed for the same ``key`` content is deleted and recreated, not updated in place.
    """

    title: str
    key: str
    read_only: bool = True


class Autolink(Strict):
    """A repository autolink reference, matched against existing ones by ``key_prefix``.

    GitHub's autolinks API has no update endpoint: a changed ``url_template``/
    ``is_alphanumeric`` for an existing ``key_prefix`` is deleted and recreated.
    """

    key_prefix: str
    url_template: str
    is_alphanumeric: bool = True

    @field_validator("url_template")
    @classmethod
    def _requires_num_placeholder(cls, value: str) -> str:
        if "<num>" not in value:
            msg = f"{value!r} must contain the '<num>' placeholder for GitHub's reference number"
            raise ValueError(msg)
        return value


class CodeownersEntry(Strict):
    """One CODEOWNERS rule: a path pattern and the owners responsible for it.

    Matched against existing entries by ``pattern`` for ``extends:`` merges. ``owners`` are
    GitHub usernames (``@user``), teams (``@org/team``), or email addresses — passed through
    verbatim; GitHub itself surfaces an owner that doesn't exist or lacks access.
    """

    pattern: str
    owners: list[str] = Field(min_length=1)


class TeamAccess(Strict):
    """A team's permission grant on a repository, matched by team ``slug``."""

    slug: str
    permission: Permission = "push"


class _EnvValued(Strict):
    """A named value sourced either literally or from the environment.

    Provide exactly one of ``value`` or ``value_from_env``; :meth:`resolve` returns the
    literal value or reads the named environment variable when the change is planned.
    """

    name: str
    value: str | None = None
    value_from_env: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> _EnvValued:
        if (self.value is None) == (self.value_from_env is None):
            msg = f"{self.name!r}: set exactly one of 'value' or 'value_from_env'"
            raise ValueError(msg)
        return self

    def resolve(self) -> str:
        """Return the value, reading the environment when needed."""
        if self.value is not None:
            return self.value
        assert self.value_from_env is not None  # noqa: S101 — guaranteed by validator
        return _require_env(self.value_from_env)


class Secret(_EnvValued):
    """An Actions secret. Provide exactly one of ``value`` or ``value_from_env``.

    Values are write-only on GitHub and never shown in plans.
    """


class Variable(_EnvValued):
    """An Actions repository variable. Provide exactly one of ``value`` or ``value_from_env``.

    Unlike secrets, variable values are not sensitive: they are readable on GitHub and
    shown in plain text in plans, so an existing variable is updated only when its value
    actually differs.
    """


class SelectedActions(Strict):
    """Which actions are allowed when ``allowed_actions`` is ``"selected"``.

    Unmanaged (``None``) unless ``allowed_actions: selected`` is also set — GitHub rejects
    this sub-config for any other policy.
    """

    github_owned_allowed: bool = True
    verified_allowed: bool = False
    patterns_allowed: list[str] = Field(default_factory=list)


class ForkPrWorkflowsPrivateRepos(Strict):
    """Fork-PR workflow settings for a private/internal repo (Settings → Actions → General).

    Nested (unlike the flat ``enabled``/``allowed_actions``/``sha_pinning_required`` trio, which
    predate this and can't be nested without a breaking config change) to group four related
    fields under one key and match the endpoint's own payload shape — the field names are the
    API keys, so the manager PUTs ``model_dump()`` verbatim.

    Each field is independently unmanaged (``None``) — an unmanaged field is written back with
    its live value on apply, so declaring only one of the four never clears the others. GitHub
    requires ``run_workflows_from_fork_pull_requests`` on every write, which the write-back of
    its live value satisfies when it is left unmanaged.
    """

    run_workflows_from_fork_pull_requests: bool | None = None
    send_write_tokens_to_workflows: bool | None = None
    send_secrets_and_variables: bool | None = None
    require_approval_for_fork_pr_workflows: bool | None = None


class ActionsConfig(Strict):
    """Actions settings across the seven ``/actions/permissions`` endpoints.

    Enablement, allowed-actions policy (incl. SHA-pinning), workflow permissions, external
    workflow access, artifact/log retention, and fork-PR settings. Unset fields are left
    unmanaged, consistent with :class:`Settings`.
    """

    enabled: bool | None = None
    allowed_actions: Literal["all", "local_only", "selected"] | None = None
    # "Require actions to be pinned to a full-length commit SHA" — a field on the same
    # permissions endpoint as enabled/allowed_actions above.
    sha_pinning_required: bool | None = None
    selected_actions: SelectedActions | None = None
    default_workflow_permissions: Literal["read", "write"] | None = None
    # "Allow GitHub Actions to create and approve pull requests" — the same
    # workflow-permissions endpoint as default_workflow_permissions above.
    can_approve_pull_request_reviews: bool | None = None
    # "Access" — which outside workflows may use this repo's actions/workflows. Meaningful for
    # private/internal repos; GitHub rejects a non-`none` value on a public repo at apply time.
    access_level: Literal["none", "user", "organization"] | None = None
    # Artifact & log retention period, in days. GitHub enforces the org-configured ceiling.
    artifact_and_log_retention_days: int | None = Field(default=None, gt=0)
    # "Fork pull request workflows from outside collaborators" approval policy (public repos).
    fork_pr_contributor_approval: (
        Literal[
            "first_time_contributors_new_to_github",
            "first_time_contributors",
            "all_external_contributors",
        ]
        | None
    ) = None
    # "Fork pull request workflows in private repositories" (private/internal repos).
    fork_pr_workflows_private_repos: ForkPrWorkflowsPrivateRepos | None = None

    @model_validator(mode="after")
    def _selected_actions_requires_selected_policy(self) -> ActionsConfig:
        if self.selected_actions is not None and self.allowed_actions != "selected":
            msg = "'selected_actions' requires 'allowed_actions: selected'"
            raise ValueError(msg)
        return self


class Security(Strict):
    """Repository security posture toggles. Unset fields are left unmanaged.

    ``secret_scanning``/``secret_scanning_push_protection`` are read from and written to
    GitHub's nested ``security_and_analysis`` object; the rest are independent endpoints.
    """

    secret_scanning: bool | None = None
    secret_scanning_push_protection: bool | None = None
    vulnerability_alerts: bool | None = None
    automated_security_fixes: bool | None = None
    private_vulnerability_reporting: bool | None = None


class Reviewer(Strict):
    """A required reviewer on a deployment environment: a GitHub user or team.

    Provide ``login`` for a ``User`` or ``slug`` for a ``Team`` — resolved to the numeric
    GitHub ID the API requires at plan time.
    """

    type: Literal["User", "Team"]
    login: str | None = None
    slug: str | None = None

    @field_validator("login", "slug")
    @classmethod
    def _safe_identifier(cls, value: str | None) -> str | None:
        if value is not None and not _GITHUB_IDENTIFIER.fullmatch(value):
            msg = f"{value!r} is not a valid GitHub login/team-slug"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _matching_identifier(self) -> Reviewer:
        if self.type == "User" and (self.login is None or self.slug is not None):
            msg = "a 'User' reviewer requires 'login' and must not set 'slug'"
            raise ValueError(msg)
        if self.type == "Team" and (self.slug is None or self.login is not None):
            msg = "a 'Team' reviewer requires 'slug' and must not set 'login'"
            raise ValueError(msg)
        return self


class DeploymentBranchPattern(Strict):
    """A single custom branch/tag pattern that may deploy to an environment (e.g. ``v*``)."""

    name: str
    type: Literal["branch", "tag"] = "branch"

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "a deployment-branch-policy pattern 'name' must be non-empty"
            raise ValueError(msg)
        return value


class DeploymentBranchPolicy(Strict):
    """Which branches/tags may deploy to an environment.

    ``protected_branches`` and ``custom_branch_policies`` are mutually exclusive on
    GitHub's API — setting both true is rejected at apply time with an opaque error, so
    it's rejected here instead, at config-validation time.

    ``custom_branch_policies: true`` only tells GitHub custom policies are *in effect*; it
    registers no patterns, so nothing can deploy until at least one is added. Declare the
    patterns themselves under ``patterns`` (each a ``{name, type}``); the manager diffs them
    against the environment's live patterns and creates/deletes to match. ``patterns`` unset
    leaves them unmanaged; an empty list is the authoritative "no patterns" state. Because
    patterns are the custom-policy mechanism, declaring them requires
    ``custom_branch_policies: true``.
    """

    protected_branches: bool = False
    custom_branch_policies: bool = False
    patterns: list[DeploymentBranchPattern] | None = None

    @model_validator(mode="after")
    def _mutually_exclusive(self) -> DeploymentBranchPolicy:
        if self.protected_branches and self.custom_branch_policies:
            msg = "'protected_branches' and 'custom_branch_policies' cannot both be true"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _patterns_require_custom(self) -> DeploymentBranchPolicy:
        if self.patterns is not None and not self.custom_branch_policies:
            msg = "'deployment_branch_policy.patterns' requires 'custom_branch_policies: true'"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _patterns_unique(self) -> DeploymentBranchPolicy:
        # A pattern's identity is (name, type); a duplicate would emit two CREATEs for the same
        # policy, the second of which 422s at apply. Reject it at load rather than mid-reconcile.
        if self.patterns is not None:
            keys = [(pattern.name, pattern.type) for pattern in self.patterns]
            if len(keys) != len(set(keys)):
                msg = "'deployment_branch_policy.patterns' has duplicate (name, type) entries"
                raise ValueError(msg)
        return self


class Environment(Strict):
    """A deployment environment: protection rules plus environment-scoped secrets/variables."""

    name: str
    wait_timer: int | None = None
    reviewers: list[Reviewer] | None = None
    prevent_self_review: bool | None = None
    deployment_branch_policy: DeploymentBranchPolicy | None = None
    secrets: list[Secret] | None = None
    variables: list[Variable] | None = None


class PagesSource(Strict):
    """The branch/path GitHub Pages builds from — only meaningful for ``build_type: legacy``."""

    branch: str
    path: Literal["/", "/docs"] = "/"

    @field_validator("branch")
    @classmethod
    def _branch_non_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "'source.branch' must be a non-empty branch name"
            raise ValueError(msg)
        return value


class Pages(Strict):
    """GitHub Pages configuration. ``enabled: false`` disables Pages if currently on.

    ``build_type`` and ``source`` must cohere the way GitHub's API enforces: a ``legacy``
    (classic-branch) build requires a ``source``; a ``workflow`` (GitHub Actions) build must
    not carry one. Both are validated here so a bad combination is a config-load error rather
    than an apply-time 422.
    """

    enabled: bool = True
    build_type: Literal["legacy", "workflow"] | None = None
    source: PagesSource | None = None
    cname: str | None = None
    https_enforced: bool | None = None

    @model_validator(mode="after")
    def _build_type_required_when_enabled(self) -> Pages:
        if self.enabled and self.build_type is None:
            msg = "'build_type' is required when 'enabled' is true"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _source_coheres_with_build_type(self) -> Pages:
        # GitHub 422s a legacy build with no source, and a workflow build that carries one.
        if self.build_type == "legacy" and self.source is None:
            msg = "'source' is required when 'build_type' is 'legacy'"
            raise ValueError(msg)
        if self.build_type == "workflow" and self.source is not None:
            msg = "'source' must not be set when 'build_type' is 'workflow'"
            raise ValueError(msg)
        return self


class SharedConfig(Strict):
    """The config sections applied to every repository in a :class:`Config`."""

    settings: Settings | None = None
    actions: ActionsConfig | None = None
    security: Security | None = None
    rulesets: list[Ruleset] | None = None
    labels: list[Label] | None = None
    collaborators: list[Collaborator] | None = None
    teams: list[TeamAccess] | None = None
    codeowners: list[CodeownersEntry] | None = None
    # The comment placed at the top of a managed CODEOWNERS file, as plain text (rendered with a
    # leading "# "). Unset falls back to the manager's default; only rendered when `codeowners`
    # writes a file, so it has no effect when `codeowners` is unset or authoritative-empty.
    codeowners_header: str | None = None
    webhooks: list[Webhook] | None = None
    secrets: list[Secret] | None = None
    variables: list[Variable] | None = None
    deploy_keys: list[DeployKey] | None = None
    autolinks: list[Autolink] | None = None
    environments: list[Environment] | None = None
    pages: Pages | None = None

    def env_sources(self) -> set[str]:
        """Return every environment-variable name this config reads a value from.

        The union of ``value_from_env`` across ``secrets`` and ``variables`` plus
        ``secret_from_env`` across ``webhooks`` — i.e. the env vars that must be set for an
        apply/plan of this config to resolve its values. The apply/plan workflows must export
        exactly the fleet's union of these (enforced by ``tests/test_workflow_secrets.py``).
        """
        names: set[str] = set()
        for secret in self.secrets or []:
            if secret.value_from_env is not None:
                names.add(secret.value_from_env)
        for webhook in self.webhooks or []:
            if webhook.secret_from_env is not None:
                names.add(webhook.secret_from_env)
        return names | self.variable_env_sources()

    def variable_env_sources(self) -> set[str]:
        """Return the env-var names read by *variables* (their ``value_from_env``) — plan's set.

        A variable's value is diff-input (shown in the plan and compared to decide
        update-vs-no-op), so ``plan`` must resolve it and therefore needs its env var exported.
        A secret's value is write-only payload resolved only at ``apply``, and a webhook secret
        likewise, so ``plan`` needs neither. This is the strict subset of :meth:`env_sources`
        the plan workflow exports; apply exports the full set. (See
        ``tests/test_workflow_secrets.py``.)
        """
        return {
            variable.value_from_env
            for variable in self.variables or []
            if variable.value_from_env is not None
        }


class Config(SharedConfig):
    """Top-level config: the repositories to manage plus the shared section block."""

    repos: list[str] = Field(min_length=1)

    @field_validator("repos")
    @classmethod
    def _full_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if name.count("/") != 1 or name.startswith("/") or name.endswith("/"):
                msg = f"repo name {name!r} must be in 'owner/repo' form"
                raise ValueError(msg)
        return value


# GitHub's single-select option palette (ProjectV2SingleSelectFieldOptionColor).
ProjectFieldColor = Literal["GRAY", "BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PINK", "PURPLE"]


class ProjectFieldOption(Strict):
    """One single-select option: its display name, color, and description.

    Matched against a field's live options by ``name``, so renaming the *color* or
    *description* of a same-named option updates it in place (preserving the option's id and
    the board items already assigned to it). An option present on the field but absent from
    the declared list is *removed* by an apply — and removing an option drops it from every
    item that had it, so a plan surfaces that as a destructive change before it's applied.
    """

    name: str
    color: ProjectFieldColor = "GRAY"
    description: str = ""

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "a single-select option 'name' must be non-empty"
            raise ValueError(msg)
        return value


class ProjectField(Strict):
    """A Projects v2 custom field. Only ``single_select`` fields carry ``options``.

    ``single_select`` requires a non-empty ``options`` list (GitHub rejects an option-less
    single-select); every other type must omit ``options``. The manager creates a missing
    field and, for single-selects, reconciles its options; it never changes an existing
    field's ``data_type`` (GitHub has no such mutation), so a type change must be made by
    hand.
    """

    name: str
    data_type: Literal["single_select", "date", "text", "number"] = "single_select"
    options: list[ProjectFieldOption] | None = None

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "a project field 'name' must be non-empty"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _options_match_type(self) -> ProjectField:
        if self.data_type == "single_select":
            if not self.options:
                msg = f"field {self.name!r}: 'single_select' requires a non-empty 'options' list"
                raise ValueError(msg)
            names = [option.name for option in self.options]
            if len(names) != len(set(names)):
                msg = f"field {self.name!r}: duplicate option names"
                raise ValueError(msg)
        elif self.options is not None:
            msg = f"field {self.name!r}: 'options' is only valid for a 'single_select' field"
            raise ValueError(msg)
        return self


class ProjectsConfig(Strict):
    """A GitHub Projects v2 board to manage: how to address it, and its custom-field schema.

    Deliberately models the board's **schema only** — the custom fields and their
    single-select options. Board *membership* (which issues are items) and per-item field
    *values* are owned by planning/automation tooling, not this declarative config, because
    they churn as issues open and close; see ``docs/projects.md``. Built-in fields
    (Status excepted, since it's a normal single-select) and any field not declared here are
    left unmanaged.

    The board is addressed by **exactly one** of ``number`` or ``title``, and the choice
    selects the semantics:

    - ``number`` **adopts** that exact board. GitHub assigns a number when a board is created,
      so a number always names a board that already exists; a number that doesn't resolve is
      an error, never an invitation to create one.
    - ``title`` **converges** on a board with that title, creating it when absent. This is the
      only way to declare a board that doesn't exist yet, precisely because its number can't
      be known in advance.

    ``title`` is an *address*, not a managed attribute: renaming a board out from under a
    title-addressed config reads as "the declared board is gone", and the next apply creates a
    new one. Pin with ``number`` when that matters.
    """

    owner: str
    owner_type: Literal["user", "organization"] = "user"
    number: int | None = None
    title: str | None = None
    fields: list[ProjectField] = Field(min_length=1)

    @field_validator("owner")
    @classmethod
    def _valid_owner(cls, value: str) -> str:
        if not _GITHUB_IDENTIFIER.fullmatch(value):
            msg = f"{value!r} is not a valid GitHub owner login"
            raise ValueError(msg)
        return value

    @field_validator("title")
    @classmethod
    def _title_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Canonicalize, don't just check: the title is matched against the live board by exact
        # equality, so storing " Roadmap" unstripped would address a board no lookup can find
        # — and every apply would create another one rather than adopting its own.
        title = value.strip()
        if not title:
            msg = "a board 'title' must be non-empty"
            raise ValueError(msg)
        return title

    @model_validator(mode="after")
    def _addressed_exactly_once(self) -> ProjectsConfig:
        if (self.number is None) == (self.title is None):
            msg = (
                "a board is addressed by exactly one of 'number' (adopt an existing board) "
                "or 'title' (converge on a board by name, creating it if absent)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _field_names_unique(self) -> ProjectsConfig:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            msg = "duplicate field names in 'fields'"
            raise ValueError(msg)
        return self

    @property
    def label(self) -> str:
        """A short display label for the board: ``owner/#2`` or ``owner/'Some Title'``."""
        if self.number is not None:
            return f"{self.owner}/#{self.number}"
        return f"{self.owner}/{self.title!r}"


def _require_env(name: str) -> str:
    # Treat empty as unset: in GitHub Actions `${{ secrets.X }}` for an unset secret expands
    # to "" (the var is defined but empty), so a presence-only check would silently propagate
    # an empty value to every managed repo. Fail fast instead.
    value = os.environ.get(name)
    if not value:
        msg = f"environment variable {name!r} is not set or is empty"
        raise ConfigError(msg)
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read config file {path}: {exc}"
        raise ConfigError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"config file {path} is not valid UTF-8: {exc}"
        raise ConfigError(msg) from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in {path}: {exc}"
        raise ConfigError(msg) from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"config root of {path} must be a mapping, got {type(data).__name__}"
        raise ConfigError(msg)
    return data


def _merge_by_key(
    base: list[Any], override: list[Any], key: str, normalize: Callable[[str], str] | None
) -> list[Any]:
    """Merge lists of mappings by ``key``: override replaces same-key items, appends new.

    ``normalize`` (when set) matches the identity the section's manager actually diffs
    against, so an item that differs only in a way the manager itself ignores (e.g. a
    deploy key's optional comment) is matched as the *same* item here too.

    Relies on dict insertion order: reassigning an existing key keeps its position, so a
    same-key override item replaces in place while new items land at the end.
    """
    merged: dict[Any, Any] = {}
    for index, item in enumerate([*base, *override]):
        # Only match on a plain string key; a missing, malformed, or non-string key value
        # (e.g. a list, which is also unhashable) is kept positionally and left for schema
        # validation to reject cleanly.
        raw_key = item.get(key) if isinstance(item, dict) else None
        if isinstance(raw_key, str):
            item_key = normalize(raw_key) if normalize else raw_key
        else:
            item_key = (index, "_unkeyed")
        merged[item_key] = item
    return list(merged.values())


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
    path: tuple[str, ...],
) -> dict[str, Any]:
    """Merge ``override`` onto ``base``: nested dicts recurse, keyed lists merge by key."""
    result = dict(base)
    for key, over_value in override.items():
        base_value = result.get(key)
        child_path = (*path, key)
        if isinstance(base_value, dict) and isinstance(over_value, dict):
            result[key] = _deep_merge(base_value, over_value, child_path)
        elif (
            child_path in _KEYED_LISTS
            and isinstance(base_value, list)
            and isinstance(over_value, list)
        ):
            result[key] = _merge_by_key(
                base_value, over_value, _KEYED_LISTS[child_path], _KEY_NORMALIZERS.get(child_path)
            )
        else:
            result[key] = over_value
    return result


def _resolve(
    path: Path,
    stack: tuple[Path, ...],
    cache: dict[Path, dict[str, Any]],
) -> dict[str, Any]:
    """Load a config file, resolving and merging any ``extends:`` bases beneath it.

    ``cache`` memoizes each fully-resolved file by absolute path so a shared base reached
    via several paths (a diamond) is read once, not re-expanded exponentially.
    """
    resolved = path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(p) for p in (*stack, resolved))
        msg = f"circular extends detected: {chain}"
        raise ConfigError(msg)
    if resolved in cache:
        return copy.deepcopy(cache[resolved])

    data = _read_yaml(path)
    extends = data.pop("extends", None)
    if extends is None:
        cache[resolved] = data
        return copy.deepcopy(data)

    bases = [extends] if isinstance(extends, str) else extends
    if not isinstance(bases, list) or not all(isinstance(item, str) for item in bases):
        msg = f"'extends' in {path} must be a string or list of strings"
        raise ConfigError(msg)

    merged: dict[str, Any] = {}
    for base in bases:
        base_data = _resolve(path.parent / base, (*stack, resolved), cache)
        merged = _deep_merge(merged, base_data, ())
    result = _deep_merge(merged, data, ())
    cache[resolved] = result
    return copy.deepcopy(result)


def load_config(path: Path) -> Config:
    """Load and validate a YAML config file, applying any ``extends:`` bases.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        The validated :class:`Config`.

    Raises:
        ConfigError: If a file is missing, not valid YAML/UTF-8, has a bad ``extends``
            chain, or fails schema validation.
    """
    data = _resolve(path, (), {})
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        msg = f"invalid configuration in {path}:\n{exc}"
        raise ConfigError(msg) from exc


def load_projects_config(path: Path) -> ProjectsConfig:
    """Load and validate a Projects v2 board config file.

    Separate from :func:`load_config`: a board is a single owner-level entity with its own
    schema (no ``repos:``, no ``extends:`` layering), reconciled by the ``projects`` CLI
    commands rather than the per-repo path.

    Args:
        path: Path to the YAML board configuration file.

    Returns:
        The validated :class:`ProjectsConfig`.

    Raises:
        ConfigError: If the file is missing, not valid YAML/UTF-8, or fails schema validation.
    """
    data = _read_yaml(path)
    try:
        return ProjectsConfig.model_validate(data)
    except ValidationError as exc:
        msg = f"invalid projects configuration in {path}:\n{exc}"
        raise ConfigError(msg) from exc


def _applied_config_paths(config_dir: Path) -> list[Path]:
    """The applied config files: every ``config/*.yml``, sorted, with the empty-dir guard.

    The single definition of "which files are applied configs": each carries its own
    ``repos:`` list and section block, and the fleet derivations are unions over them. The
    ``*.yaml`` layer files are only bases that applied configs ``extends:``, so the ``*.yml``
    glob deliberately skips them. An empty result is an error, not a silently-empty (and so
    fleet-wiping / fleet-blanking) set — every fleet derivation inherits that guard from here.

    Raises:
        ConfigError: If no ``*.yml`` config files are found.
    """
    paths = sorted(config_dir.glob("*.yml"))
    if not paths:
        msg = f"no applied config files found at {config_dir}/*.yml"
        raise ConfigError(msg)
    return paths


def fleet_repos(config_dir: Path) -> list[str]:
    """Return the managed-repo fleet: the union of every applied config's ``repos:`` list.

    The authoritative fleet definition. The central Renovate runner and the apply/plan token
    mint both scope their App token through it (the latter via :func:`fleet_repo_names`).
    Loading validates schema only — it never resolves ``value_from_env`` secrets — so this
    needs no credentials in the environment.

    Args:
        config_dir: Directory holding the applied ``*.yml`` config files.

    Returns:
        Every managed ``owner/repo``, sorted and de-duplicated.

    Raises:
        ConfigError: If no ``*.yml`` config files are found, or any fails to load.
    """
    repos: set[str] = set()
    for path in _applied_config_paths(config_dir):
        repos.update(load_config(path).repos)
    return sorted(repos)


def fleet_env_sources(config_dir: Path) -> set[str]:
    """Return the fleet's env-source set: every env var the applied configs read a value from.

    The union of :meth:`SharedConfig.env_sources` across every applied config — i.e.
    ``value_from_env`` (secrets/variables) plus ``secret_from_env`` (webhooks), the env vars
    the apply/plan workflows must export so the CLI can resolve and propagate them. The
    authoritative set for ``tests/test_workflow_secrets.py`` to check the workflows against,
    derived over the same applied-config set as :func:`fleet_repos` (so the two can't diverge
    on which files count).

    Args:
        config_dir: Directory holding the applied ``*.yml`` config files.

    Returns:
        Every env-var name sourced across the fleet's secrets/variables/webhooks.

    Raises:
        ConfigError: If no ``*.yml`` config files are found, or any fails to load.
    """
    names: set[str] = set()
    for path in _applied_config_paths(config_dir):
        names |= load_config(path).env_sources()
    return names


def fleet_variable_env_sources(config_dir: Path) -> set[str]:
    """Return the fleet's *variable* env-source set — the subset ``plan`` must export.

    The union of :meth:`SharedConfig.variable_env_sources` across every applied config: only
    ``value_from_env`` variables, since ``plan`` resolves variable values (diff-input) but not
    secret values (write-only, resolved at ``apply``). apply exports :func:`fleet_env_sources`
    (the full set); plan exports this strict subset. The authoritative plan-side set for
    ``tests/test_workflow_secrets.py``.

    Args:
        config_dir: Directory holding the applied ``*.yml`` config files.

    Returns:
        Every env-var name sourced by a fleet variable.

    Raises:
        ConfigError: If no ``*.yml`` config files are found, or any fails to load.
    """
    names: set[str] = set()
    for path in _applied_config_paths(config_dir):
        names |= load_config(path).variable_env_sources()
    return names


def fleet_repo_names(config_dir: Path) -> list[str]:
    """Return the fleet as bare repo names (owner stripped), for a per-owner App token.

    A scoped GitHub App token's ``repositories:`` is owner-relative — an App installation is
    per-owner, so one token can't span owners. This wraps :func:`fleet_repos` and strips the
    owner, but first enforces a single-owner fleet and fails LOUD on more than one: silently
    stripping a multi-owner fleet would scope the token to the wrong owner's same-named repo
    (or 422 the mint). The central Renovate runner (``list-repos --format names``) and the
    apply/plan token mint both derive their scope through here, so the rule lives in one place.

    Args:
        config_dir: Directory holding the applied ``*.yml`` config files.

    Returns:
        Every managed repo's bare name, sorted and de-duplicated.

    Raises:
        ConfigError: If no configs are found, any fails to load, or the fleet spans >1 owner.
    """
    repos = fleet_repos(config_dir)
    owners = {repo.split("/", 1)[0] for repo in repos}
    if len(owners) > 1:
        msg = (
            "a single-owner fleet is required to derive bare repo names (a GitHub App token "
            f"is per-owner); found {len(owners)} owners: {', '.join(sorted(owners))}"
        )
        raise ConfigError(msg)
    return [repo.split("/", 1)[1] for repo in repos]
