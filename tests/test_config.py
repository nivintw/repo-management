# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for config loading, validation, and extends/merge."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_management.config import (
    ActionsConfig,
    Config,
    ConfigError,
    DeploymentBranchPolicy,
    Label,
    Pages,
    Reviewer,
    Secret,
    SelectedActions,
    Settings,
    Variable,
    Webhook,
    load_config,
)


def write(tmp_path: Path, text: str, name: str = "config.yaml") -> Path:
    """Write ``text`` to a temp file and return its path."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_minimal(tmp_path: Path) -> None:
    """A minimal config with just a repo list loads and validates."""
    config = load_config(write(tmp_path, "repos:\n  - owner/repo\n"))
    assert isinstance(config, Config)
    assert config.repos == ["owner/repo"]
    assert config.settings is None


def test_load_full(tmp_path: Path) -> None:
    """A config exercising every section validates into typed models."""
    path = write(
        tmp_path,
        """
repos:
  - owner/repo
  - owner/other
settings:
  description: hello
  topics: [a, b]
rulesets:
  - name: main protection
    enforcement: active
    conditions:
      ref_name: {include: ["~DEFAULT_BRANCH"], exclude: []}
    rules:
      - {type: pull_request, required_approving_review_count: 1}
      - {type: required_linear_history}
labels:
  - {name: bug, color: ff0000}
collaborators:
  - {username: alice, permission: admin}
webhooks:
  - {url: https://e.x/hook, events: [push]}
secrets:
  - {name: TOK, value: shhh}
""",
    )
    config = load_config(path)
    assert config.repos == ["owner/repo", "owner/other"]
    assert config.settings is not None
    assert config.rulesets is not None
    assert config.rulesets[0].rules[0].type == "pull_request"
    assert config.labels is not None
    assert config.labels[0].name == "bug"


def test_env_sources_unions_secret_variable_and_webhook_names(tmp_path: Path) -> None:
    """env_sources() returns every value_from_env / secret_from_env across all sections."""
    config = load_config(
        write(
            tmp_path,
            """
repos:
  - owner/repo
secrets:
  - {name: TOK, value_from_env: TOK_ENV}
  - {name: INLINE, value: literal}
variables:
  - {name: VAR, value_from_env: VAR_ENV}
webhooks:
  - {url: https://e.x/hook, secret_from_env: HOOK_ENV}
""",
        )
    )
    # Only env-backed values appear; the inline-valued secret contributes nothing.
    assert config.env_sources() == {"TOK_ENV", "VAR_ENV", "HOOK_ENV"}


def test_env_sources_empty_without_env_backed_values(tmp_path: Path) -> None:
    """A config whose values are all inline (or absent) has an empty env_sources set."""
    config = load_config(
        write(tmp_path, "repos:\n  - owner/repo\nsecrets:\n  - {name: T, value: x}\n")
    )
    assert config.env_sources() == set()


def test_repos_required(tmp_path: Path) -> None:
    """A config with no repos is rejected."""
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "settings: {description: x}\n"))


def test_empty_repos_rejected(tmp_path: Path) -> None:
    """An empty repo list is rejected (min_length=1)."""
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "repos: []\n"))


def test_bad_repo_name(tmp_path: Path) -> None:
    """A repo name not in owner/repo form is rejected."""
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "repos:\n  - justname\n"))


def test_unknown_key_rejected(tmp_path: Path) -> None:
    """Unknown keys are rejected to catch config typos."""
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "repos:\n  - owner/repo\nbogus: 1\n"))


def test_missing_file(tmp_path: Path) -> None:
    """A missing config file raises ConfigError."""
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml(tmp_path: Path) -> None:
    """Malformed YAML raises ConfigError."""
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "repos: [unterminated\n"))


def test_non_mapping_root(tmp_path: Path) -> None:
    """A non-mapping YAML root raises ConfigError."""
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(write(tmp_path, "- a\n- b\n"))


def test_non_utf8_file(tmp_path: Path) -> None:
    """A non-UTF-8 file raises ConfigError, not an uncaught UnicodeDecodeError."""
    path = tmp_path / "config.yaml"
    path.write_bytes(b"\xff\xfe repos: []")
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_config(path)


def test_label_color_normalized() -> None:
    """Label color is lowercased and stripped of a leading '#'."""
    assert Label(name="bug", color="#FF00AA").color == "ff00aa"


def test_secret_requires_exactly_one_source() -> None:
    """A secret with neither or both value sources is rejected."""
    with pytest.raises(ValueError, match="exactly one"):
        Secret(name="X")
    with pytest.raises(ValueError, match="exactly one"):
        Secret(name="X", value="a", value_from_env="B")


def test_secret_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret resolves from a literal or the environment."""
    assert Secret(name="X", value="abc").resolve() == "abc"
    monkeypatch.setenv("MY_SECRET", "fromenv")
    assert Secret(name="X", value_from_env="MY_SECRET").resolve() == "fromenv"


def test_secret_resolve_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing environment variable raises ConfigError."""
    monkeypatch.delenv("MISSING", raising=False)
    with pytest.raises(ConfigError, match="not set"):
        Secret(name="X", value_from_env="MISSING").resolve()


def test_secret_resolve_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty environment variable is treated as unset (Actions expands unset secrets to '')."""
    monkeypatch.setenv("EMPTY", "")
    with pytest.raises(ConfigError, match="not set or is empty"):
        Secret(name="X", value_from_env="EMPTY").resolve()


def test_selected_actions_requires_selected_policy() -> None:
    """selected_actions is rejected unless allowed_actions is 'selected'."""
    with pytest.raises(ValueError, match="requires 'allowed_actions: selected'"):
        ActionsConfig(selected_actions=SelectedActions())
    with pytest.raises(ValueError, match="requires 'allowed_actions: selected'"):
        ActionsConfig(allowed_actions="all", selected_actions=SelectedActions())
    ActionsConfig(allowed_actions="selected", selected_actions=SelectedActions())


def test_reviewer_requires_matching_identifier() -> None:
    """A User reviewer needs login (not slug); a Team reviewer needs slug (not login)."""
    with pytest.raises(ValueError, match="'User' reviewer requires 'login'"):
        Reviewer(type="User", slug="team")
    with pytest.raises(ValueError, match="'Team' reviewer requires 'slug'"):
        Reviewer(type="Team", login="octocat")
    Reviewer(type="User", login="octocat")
    Reviewer(type="Team", slug="team")


def test_reviewer_rejects_unsafe_identifier() -> None:
    """A login/slug outside GitHub's identifier charset is rejected.

    login/slug are interpolated directly into a raw REST path (managers/environments.py),
    so a value containing '/' or other path-breaking characters must be rejected at the
    config layer rather than reaching an API call.
    """
    with pytest.raises(ValueError, match="not a valid GitHub login"):
        Reviewer(type="Team", slug="../../repos/other-org/private")
    with pytest.raises(ValueError, match="not a valid GitHub login"):
        Reviewer(type="User", login="a/b")
    with pytest.raises(ValueError, match="not a valid GitHub login"):
        Reviewer(type="User", login="-leading-hyphen")


def test_deployment_branch_policy_rejects_both_true() -> None:
    """protected_branches and custom_branch_policies are mutually exclusive on GitHub's API."""
    with pytest.raises(ValueError, match="cannot both be true"):
        DeploymentBranchPolicy(protected_branches=True, custom_branch_policies=True)
    DeploymentBranchPolicy(protected_branches=True)
    DeploymentBranchPolicy(custom_branch_policies=True)
    DeploymentBranchPolicy()


def test_settings_requires_title_when_message_is_set() -> None:
    """GitHub rejects a *_message field without its *_title counterpart in the same PATCH.

    A title alone is fine (it just sets a preference for later); the reverse pairing isn't
    required.
    """
    with pytest.raises(ValueError, match="'squash_merge_commit_title' is required"):
        Settings(squash_merge_commit_message="BLANK")
    with pytest.raises(ValueError, match="'merge_commit_title' is required"):
        Settings(merge_commit_message="BLANK")
    Settings(squash_merge_commit_title="PR_TITLE")
    Settings(squash_merge_commit_title="PR_TITLE", squash_merge_commit_message="BLANK")


def test_pages_requires_build_type_when_enabled() -> None:
    """Pages requires build_type unless explicitly disabled."""
    with pytest.raises(ValueError, match="'build_type' is required"):
        Pages()
    Pages(build_type="workflow")
    Pages(enabled=False)


def test_variable_requires_exactly_one_source() -> None:
    """A variable with neither or both value sources is rejected."""
    with pytest.raises(ValueError, match="exactly one"):
        Variable(name="X")
    with pytest.raises(ValueError, match="exactly one"):
        Variable(name="X", value="a", value_from_env="B")


def test_variable_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable resolves from a literal or the environment."""
    assert Variable(name="X", value="abc").resolve() == "abc"
    monkeypatch.setenv("MY_VAR", "fromenv")
    assert Variable(name="X", value_from_env="MY_VAR").resolve() == "fromenv"


def test_variable_resolve_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable sourced from an empty env var is treated as unset (shared _require_env)."""
    monkeypatch.setenv("EMPTY", "")
    with pytest.raises(ConfigError, match="not set or is empty"):
        Variable(name="X", value_from_env="EMPTY").resolve()


def test_webhook_resolve_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """A webhook secret resolves from the environment, or None when unset."""
    assert Webhook(url="https://e.x").resolve_secret() is None
    monkeypatch.setenv("HOOK_SECRET", "s3cr3t")
    assert Webhook(url="https://e.x", secret_from_env="HOOK_SECRET").resolve_secret() == "s3cr3t"


def test_webhook_resolve_empty_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A webhook secret sourced from an empty env var is treated as unset (shared _require_env)."""
    monkeypatch.setenv("EMPTY", "")
    with pytest.raises(ConfigError, match="not set or is empty"):
        Webhook(url="https://e.x", secret_from_env="EMPTY").resolve_secret()


# --- extends / merge ---------------------------------------------------------------


def test_extends_scalar_override_wins(tmp_path: Path) -> None:
    """An override file's scalar settings win over the base."""
    write(tmp_path, "settings:\n  private: true\n  has_wiki: true\n", name="base.yaml")
    override = write(
        tmp_path,
        "extends: base.yaml\nrepos: [o/r]\nsettings:\n  has_wiki: false\n",
    )
    config = load_config(override)
    assert config.settings is not None
    assert config.settings.private is True  # inherited
    assert config.settings.has_wiki is False  # overridden


def test_extends_lists_merge_by_key(tmp_path: Path) -> None:
    """Override list items replace same-key base items and append new ones."""
    write(
        tmp_path,
        """
rulesets:
  - {name: main, enforcement: active}
  - {name: tags, enforcement: active, target: tag}
""",
        name="base.yaml",
    )
    override = write(
        tmp_path,
        """
extends: base.yaml
repos: [o/r]
rulesets:
  - {name: main, enforcement: evaluate}
  - {name: release, enforcement: active}
""",
    )
    config = load_config(override)
    assert config.rulesets is not None
    by_name = {r.name: r for r in config.rulesets}
    assert by_name["main"].enforcement == "evaluate"  # replaced
    assert by_name["tags"].enforcement == "active"  # preserved
    assert "release" in by_name  # appended
    assert [r.name for r in config.rulesets] == ["main", "tags", "release"]


def test_extends_lists_merge_by_key_deploy_keys_and_autolinks(tmp_path: Path) -> None:
    """deploy_keys/autolinks merge by their own natural key, same as rulesets/labels."""
    write(
        tmp_path,
        """
deploy_keys:
  - {title: ci, key: "ssh-ed25519 AAA", read_only: true}
autolinks:
  - {key_prefix: "TICKET-", url_template: "https://old.example/<num>"}
""",
        name="base.yaml",
    )
    override = write(
        tmp_path,
        """
extends: base.yaml
repos: [o/r]
deploy_keys:
  - {title: ci, key: "ssh-ed25519 AAA", read_only: false}
  - {title: deploy, key: "ssh-ed25519 BBB"}
autolinks:
  - {key_prefix: "TICKET-", url_template: "https://new.example/<num>"}
""",
    )
    config = load_config(override)
    assert config.deploy_keys is not None
    by_key = {k.key: k for k in config.deploy_keys}
    assert by_key["ssh-ed25519 AAA"].read_only is False  # replaced
    assert "ssh-ed25519 BBB" in by_key  # appended
    assert config.autolinks is not None
    assert config.autolinks[0].url_template == "https://new.example/<num>"  # replaced


def test_extends_lists_merge_by_key_environments(tmp_path: Path) -> None:
    """Environments merges by name, same as every other keyed-list section."""
    write(tmp_path, "environments:\n  - {name: staging, wait_timer: 5}\n", name="base.yaml")
    override = write(
        tmp_path,
        """
extends: base.yaml
repos: [o/r]
environments:
  - {name: staging, wait_timer: 30}
  - {name: prod, wait_timer: 60}
""",
    )
    config = load_config(override)
    assert config.environments is not None
    by_name = {e.name: e for e in config.environments}
    assert by_name["staging"].wait_timer == 30  # replaced
    assert "prod" in by_name  # appended


def test_extends_list_of_bases(tmp_path: Path) -> None:
    """Extends accepts a list of bases merged in order."""
    write(tmp_path, "settings: {private: true}\n", name="a.yaml")
    write(tmp_path, "settings: {has_wiki: false}\n", name="b.yaml")
    override = write(tmp_path, "extends: [a.yaml, b.yaml]\nrepos: [o/r]\n")
    config = load_config(override)
    assert config.settings is not None
    assert config.settings.private is True
    assert config.settings.has_wiki is False


def test_extends_nested(tmp_path: Path) -> None:
    """A base may itself extend another base (recursive resolution)."""
    write(tmp_path, "settings: {private: true}\n", name="grand.yaml")
    write(tmp_path, "extends: grand.yaml\nsettings: {has_wiki: false}\n", name="base.yaml")
    override = write(tmp_path, "extends: base.yaml\nrepos: [o/r]\n")
    config = load_config(override)
    assert config.settings is not None
    assert config.settings.private is True
    assert config.settings.has_wiki is False


def test_extends_cycle_detected(tmp_path: Path) -> None:
    """A circular extends chain raises ConfigError instead of recursing forever."""
    write(tmp_path, "extends: b.yaml\nrepos: [o/r]\n", name="a.yaml")
    write(tmp_path, "extends: a.yaml\n", name="b.yaml")
    with pytest.raises(ConfigError, match="circular extends"):
        load_config(tmp_path / "a.yaml")


def test_extends_missing_base(tmp_path: Path) -> None:
    """A missing base file raises ConfigError."""
    override = write(tmp_path, "extends: nope.yaml\nrepos: [o/r]\n")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(override)


def test_extends_bad_type(tmp_path: Path) -> None:
    """A non-string extends value raises ConfigError."""
    override = write(tmp_path, "extends: 42\nrepos: [o/r]\n")
    with pytest.raises(ConfigError, match="must be a string or list"):
        load_config(override)


def test_extends_empty_base(tmp_path: Path) -> None:
    """An empty base file resolves to an empty mapping and merges cleanly."""
    write(tmp_path, "", name="base.yaml")
    override = write(tmp_path, "extends: base.yaml\nrepos: [o/r]\n")
    config = load_config(override)
    assert config.repos == ["o/r"]


def test_extends_diamond(tmp_path: Path) -> None:
    """A shared base reached via two branches resolves once and merges cleanly."""
    write(tmp_path, "settings: {private: true}\n", name="grand.yaml")
    write(tmp_path, "extends: grand.yaml\nsettings: {has_wiki: false}\n", name="left.yaml")
    write(tmp_path, "extends: grand.yaml\nsettings: {has_issues: true}\n", name="right.yaml")
    override = write(tmp_path, "extends: [left.yaml, right.yaml]\nrepos: [o/r]\n")
    config = load_config(override)
    assert config.settings is not None
    assert config.settings.private is True  # from the shared grandparent
    assert config.settings.has_wiki is False  # from left
    assert config.settings.has_issues is True  # from right


def test_extends_multi_base_same_key_last_wins(tmp_path: Path) -> None:
    """When two bases set the same keyed-list item, the later base wins."""
    write(tmp_path, "rulesets: [{name: main, enforcement: active}]\n", name="a.yaml")
    write(tmp_path, "rulesets: [{name: main, enforcement: disabled}]\n", name="b.yaml")
    override = write(tmp_path, "extends: [a.yaml, b.yaml]\nrepos: [o/r]\n")
    config = load_config(override)
    assert config.rulesets is not None
    assert len(config.rulesets) == 1
    assert config.rulesets[0].enforcement == "disabled"  # b, merged after a


def test_extends_unhashable_merge_key_clean_error(tmp_path: Path) -> None:
    """A malformed (non-string) merge key fails schema validation, not with a TypeError."""
    write(tmp_path, "rulesets: [{name: [a, b], enforcement: active}]\n", name="base.yaml")
    override = write(
        tmp_path,
        "extends: base.yaml\nrepos: [o/r]\nrulesets: [{name: [a, b], enforcement: disabled}]\n",
    )
    with pytest.raises(ConfigError):
        load_config(override)
