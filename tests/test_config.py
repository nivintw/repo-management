# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_management.config import (
    Config,
    ConfigError,
    RepoConfig,
    Secret,
    Webhook,
    load_config,
)


def write(tmp_path: Path, text: str) -> Path:
    """Write ``text`` to a temp config file and return its path."""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_minimal(tmp_path: Path) -> None:
    """A minimal config with one repo loads and validates."""
    path = write(tmp_path, "repos:\n  - name: owner/repo\n")
    config = load_config(path)
    assert isinstance(config, Config)
    assert config.repos[0].name == "owner/repo"


def test_load_full(tmp_path: Path) -> None:
    """A config exercising every section validates into typed models."""
    path = write(
        tmp_path,
        """
repos:
  - name: owner/repo
    settings:
      description: hello
      private: true
      topics: [a, b]
    branch_protection:
      main:
        required_approving_review_count: 1
    labels:
      prune: true
      items:
        - {name: bug, color: ff0000, description: broken}
    collaborators:
      - {username: alice, permission: admin}
    webhooks:
      - {url: https://e.x/hook, events: [push]}
    secrets:
      - {name: TOK, value: shhh}
""",
    )
    config = load_config(path)
    repo = config.repos[0]
    assert repo.settings is not None
    assert repo.settings.topics == ["a", "b"]
    assert repo.branch_protection is not None
    assert repo.branch_protection["main"].required_approving_review_count == 1
    assert repo.labels is not None
    assert repo.labels.prune is True
    assert repo.collaborators is not None
    assert repo.collaborators[0].permission == "admin"


def test_unknown_key_rejected(tmp_path: Path) -> None:
    """Unknown keys are rejected to catch config typos."""
    path = write(tmp_path, "repos:\n  - name: owner/repo\n    bogus: 1\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_bad_repo_name(tmp_path: Path) -> None:
    """A repo name not in owner/repo form is rejected."""
    path = write(tmp_path, "repos:\n  - name: justname\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_file(tmp_path: Path) -> None:
    """A missing config file raises ConfigError."""
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml(tmp_path: Path) -> None:
    """Malformed YAML raises ConfigError."""
    path = write(tmp_path, "repos: [unterminated\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_non_mapping_root(tmp_path: Path) -> None:
    """A non-mapping YAML root raises ConfigError."""
    path = write(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(path)


def test_secret_requires_exactly_one_source() -> None:
    """A secret with neither or both value sources is rejected."""
    with pytest.raises(ValueError, match="exactly one"):
        Secret(name="X")
    with pytest.raises(ValueError, match="exactly one"):
        Secret(name="X", value="a", value_from_env="B")


def test_secret_resolve_literal() -> None:
    """A secret with a literal value resolves to it."""
    assert Secret(name="X", value="abc").resolve() == "abc"


def test_secret_resolve_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret sourced from the environment resolves to the env value."""
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


def test_repo_config_defaults() -> None:
    """An unset section defaults to None/empty, meaning unmanaged."""
    repo = RepoConfig(name="o/r")
    assert repo.settings is None
    assert repo.branch_protection is None
    assert repo.labels is None
