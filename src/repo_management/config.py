# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Configuration schema for the repository manager.

The YAML config is validated into these pydantic models. A field left unset (``None``)
means *unmanaged* — the reconciler leaves the corresponding GitHub setting untouched.
Only fields explicitly present in the YAML are reconciled.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

if TYPE_CHECKING:
    from pathlib import Path

Permission = Literal["pull", "triage", "push", "maintain", "admin"]


class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded or validated."""


class _Strict(BaseModel):
    """Base model that rejects unknown keys, catching config typos early."""

    model_config = ConfigDict(extra="forbid")


class Settings(_Strict):
    """Repository settings and merge options. Unset fields are left unmanaged."""

    description: str | None = None
    homepage: str | None = None
    private: bool | None = None
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


class BranchProtection(_Strict):
    """Protection rules for a single branch. Unset fields are left unmanaged."""

    required_approving_review_count: int | None = None
    dismiss_stale_reviews: bool | None = None
    require_code_owner_reviews: bool | None = None
    required_status_checks: list[str] | None = None
    strict_status_checks: bool | None = None
    enforce_admins: bool | None = None
    required_linear_history: bool | None = None
    allow_force_pushes: bool | None = None
    allow_deletions: bool | None = None
    required_conversation_resolution: bool | None = None


class Label(_Strict):
    """A repository issue/PR label.

    ``description`` is unmanaged when omitted (left as-is on GitHub); set it to manage it.
    """

    name: str
    color: str = "ededed"
    description: str | None = None

    @field_validator("color")
    @classmethod
    def _normalize_color(cls, value: str) -> str:
        # GitHub stores hex colors lowercased and without a leading '#'; normalize so the
        # diff doesn't report a phantom change on every run.
        return value.lstrip("#").lower()


class Labels(_Strict):
    """Desired set of labels. ``prune`` deletes labels not listed here."""

    prune: bool = False
    items: list[Label] = Field(default_factory=list)


class Collaborator(_Strict):
    """A repository collaborator and their permission level."""

    username: str
    permission: Permission = "push"


class Webhook(_Strict):
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


class Secret(_Strict):
    """An Actions secret. Provide exactly one of ``value`` or ``value_from_env``."""

    name: str
    value: str | None = None
    value_from_env: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Secret:
        if (self.value is None) == (self.value_from_env is None):
            msg = f"secret {self.name!r}: set exactly one of 'value' or 'value_from_env'"
            raise ValueError(msg)
        return self

    def resolve(self) -> str:
        """Return the secret value, reading the environment when needed."""
        if self.value is not None:
            return self.value
        assert self.value_from_env is not None  # noqa: S101 — guaranteed by validator
        return _require_env(self.value_from_env)


class RepoConfig(_Strict):
    """Desired configuration for one repository, addressed as ``owner/name``."""

    name: str
    settings: Settings | None = None
    branch_protection: dict[str, BranchProtection] | None = None
    labels: Labels | None = None
    collaborators: list[Collaborator] | None = None
    webhooks: list[Webhook] | None = None
    secrets: list[Secret] | None = None

    @model_validator(mode="after")
    def _full_name(self) -> RepoConfig:
        if self.name.count("/") != 1 or self.name.startswith("/") or self.name.endswith("/"):
            msg = f"repo name {self.name!r} must be in 'owner/repo' form"
            raise ValueError(msg)
        return self


class Config(_Strict):
    """Top-level config: a list of repositories to manage."""

    repos: list[RepoConfig] = Field(default_factory=list)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        msg = f"environment variable {name!r} is not set"
        raise ConfigError(msg)
    return value


def load_config(path: Path) -> Config:
    """Load and validate a YAML config file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        The validated :class:`Config`.

    Raises:
        ConfigError: If the file is missing, not valid YAML, or fails validation.
    """
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

    if not isinstance(data, dict):
        msg = f"config root must be a mapping, got {type(data).__name__}"
        raise ConfigError(msg)

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        msg = f"invalid configuration in {path}:\n{exc}"
        raise ConfigError(msg) from exc
