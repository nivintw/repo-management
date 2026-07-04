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
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from repo_management.base import Strict
from repo_management.ruleset import Ruleset

if TYPE_CHECKING:
    from pathlib import Path

Permission = Literal["pull", "triage", "push", "maintain", "admin"]

# Section path -> the field that identifies an item, for by-key list merges.
_KEYED_LISTS: dict[tuple[str, ...], str] = {
    ("rulesets",): "name",
    ("labels",): "name",
    ("collaborators",): "username",
    ("webhooks",): "url",
    ("secrets",): "name",
    ("variables",): "name",
}


class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded or validated."""


class Settings(Strict):
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


class ActionsConfig(Strict):
    """Actions permissions: enablement, allowed-actions policy, and workflow permissions.

    Unset fields are left unmanaged, consistent with :class:`Settings`.
    """

    enabled: bool | None = None
    allowed_actions: Literal["all", "local_only", "selected"] | None = None
    selected_actions: SelectedActions | None = None
    default_workflow_permissions: Literal["read", "write"] | None = None
    # "Allow GitHub Actions to create and approve pull requests" — the same
    # workflow-permissions endpoint as default_workflow_permissions above.
    can_approve_pull_request_reviews: bool | None = None


class SharedConfig(Strict):
    """The config sections applied to every repository in a :class:`Config`."""

    settings: Settings | None = None
    actions: ActionsConfig | None = None
    rulesets: list[Ruleset] | None = None
    labels: list[Label] | None = None
    collaborators: list[Collaborator] | None = None
    webhooks: list[Webhook] | None = None
    secrets: list[Secret] | None = None
    variables: list[Variable] | None = None

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
        for variable in self.variables or []:
            if variable.value_from_env is not None:
                names.add(variable.value_from_env)
        for webhook in self.webhooks or []:
            if webhook.secret_from_env is not None:
                names.add(webhook.secret_from_env)
        return names


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


def _merge_by_key(base: list[Any], override: list[Any], key: str) -> list[Any]:
    """Merge lists of mappings by ``key``: override replaces same-key items, appends new.

    Relies on dict insertion order: reassigning an existing key keeps its position, so a
    same-key override item replaces in place while new items land at the end.
    """
    merged: dict[Any, Any] = {}
    for index, item in enumerate([*base, *override]):
        # Only match on a plain string key; a missing, malformed, or non-string key value
        # (e.g. a list, which is also unhashable) is kept positionally and left for schema
        # validation to reject cleanly.
        raw_key = item.get(key) if isinstance(item, dict) else None
        item_key = raw_key if isinstance(raw_key, str) else (index, "_unkeyed")
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
            result[key] = _merge_by_key(base_value, over_value, _KEYED_LISTS[child_path])
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
