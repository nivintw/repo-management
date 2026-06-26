# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for config loading, validation, and extends/merge."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_management.config import (
    Config,
    ConfigError,
    Label,
    Secret,
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


def test_webhook_resolve_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """A webhook secret resolves from the environment, or None when unset."""
    assert Webhook(url="https://e.x").resolve_secret() is None
    monkeypatch.setenv("HOOK_SECRET", "s3cr3t")
    assert Webhook(url="https://e.x", secret_from_env="HOOK_SECRET").resolve_secret() == "s3cr3t"


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
