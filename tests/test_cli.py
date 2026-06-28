# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest
from github import GithubException
from typer.testing import CliRunner

from repo_management import cli
from repo_management.changes import Action, Change
from repo_management.config import Config, ConfigError
from repo_management.reconciler import RepoPlan

runner = CliRunner()

VALID = "repos:\n  - owner/repo\n"


def write(tmp_path: Path, text: str = VALID) -> Path:
    """Write a config file and return its path."""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _change() -> Change:
    return Change("settings", Action.UPDATE, "description", "old", "new", lambda: None)


def test_validate_ok(tmp_path: Path) -> None:
    """Validate reports a valid config."""
    result = runner.invoke(cli.app, ["validate", "--config", str(write(tmp_path))])
    assert result.exit_code == 0
    assert "valid" in result.stdout


def test_validate_bad(tmp_path: Path) -> None:
    """Validate exits non-zero on an invalid config."""
    path = write(tmp_path, "repos:\n  - nope\n")
    result = runner.invoke(cli.app, ["validate", "--config", str(path)])
    assert result.exit_code == 1


def test_plan_shows_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan prints the changes returned by the reconciler."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [_change()])]
    )

    result = runner.invoke(cli.app, ["plan", "--config", str(write(tmp_path))])

    assert result.exit_code == 0
    assert "description" in result.stdout
    assert "1 change(s)" in result.stdout


def test_plan_in_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan reports an in-sync repo."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [])])

    result = runner.invoke(cli.app, ["plan", "--config", str(write(tmp_path))])

    assert result.exit_code == 0
    assert "in sync" in result.stdout


def test_plan_repo_filter_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan with a matching --repo narrows to that repo."""
    seen: list[int] = []

    def _capture(_client: object, cfg: Config, **_kw: object) -> list[RepoPlan]:
        seen.append(len(cfg.repos))
        return [RepoPlan("owner/repo", [])]

    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "plan_config", _capture)
    path = write(tmp_path, "repos:\n  - owner/repo\n  - owner/other\n")

    result = runner.invoke(cli.app, ["plan", "--config", str(path), "--repo", "owner/repo"])

    assert result.exit_code == 0
    assert seen == [1]


def test_plan_repo_filter_not_found(tmp_path: Path) -> None:
    """Plan with an unknown --repo exits non-zero."""
    result = runner.invoke(
        cli.app,
        ["plan", "--config", str(write(tmp_path)), "--repo", "other/repo"],
    )
    assert result.exit_code == 1


def test_plan_token_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing token surfaces as a non-zero exit."""

    def _raise(_token: str | None) -> object:
        msg = "no GitHub token"
        raise ConfigError(msg)

    monkeypatch.setattr(cli, "get_client", _raise)
    result = runner.invoke(cli.app, ["plan", "--config", str(write(tmp_path))])
    assert result.exit_code == 1


def test_plan_github_error_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GithubException during planning exits cleanly, not with a traceback."""

    def _raise(_client: object, _cfg: Config, **_kw: object) -> list[RepoPlan]:
        raise GithubException(403, {"message": "rate limited"}, None)

    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "plan_config", _raise)

    result = runner.invoke(cli.app, ["plan", "--config", str(write(tmp_path))])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_apply_github_error_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GithubException while applying exits cleanly with the repo named."""

    def _raise(_plan: RepoPlan) -> None:
        raise GithubException(422, {"message": "bad"}, None)

    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [_change()])]
    )
    monkeypatch.setattr(cli, "apply_plan", _raise)

    result = runner.invoke(cli.app, ["apply", "--config", str(write(tmp_path)), "--yes"])

    assert result.exit_code == 1


def test_apply_with_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply --yes applies without prompting."""
    applied: list[str] = []
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [_change()])]
    )
    monkeypatch.setattr(cli, "apply_plan", lambda plan: applied.append(plan.repo_name))

    result = runner.invoke(cli.app, ["apply", "--config", str(write(tmp_path)), "--yes"])

    assert result.exit_code == 0
    assert applied == ["owner/repo"]
    assert "applied 1 change(s)" in result.stdout


def test_apply_force_secrets_threads_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--force-secrets reaches plan_config; without it the flag defaults to False."""
    seen: list[bool] = []

    def _capture(_client: object, _cfg: Config, *, force_secrets: bool = False) -> list[RepoPlan]:
        seen.append(force_secrets)
        return [RepoPlan("owner/repo", [])]

    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "plan_config", _capture)

    path = str(write(tmp_path))
    assert runner.invoke(cli.app, ["apply", "--config", path, "--yes"]).exit_code == 0
    assert (
        runner.invoke(cli.app, ["apply", "--config", path, "--yes", "--force-secrets"]).exit_code
        == 0
    )
    assert seen == [False, True]


def test_apply_nothing_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply on an in-sync repo does nothing."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [])])
    called: list[str] = []
    monkeypatch.setattr(cli, "apply_plan", lambda plan: called.append(plan.repo_name))

    result = runner.invoke(cli.app, ["apply", "--config", str(write(tmp_path)), "--yes"])

    assert result.exit_code == 0
    assert "nothing to do" in result.stdout
    assert called == []


def test_apply_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Declining the confirmation aborts with a non-zero exit."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [_change()])]
    )
    applied: list[str] = []
    monkeypatch.setattr(cli, "apply_plan", lambda plan: applied.append(plan.repo_name))

    result = runner.invoke(cli.app, ["apply", "--config", str(write(tmp_path))], input="n\n")

    assert result.exit_code == 1
    assert applied == []


def test_no_args_shows_help() -> None:
    """Invoking with no command prints help."""
    result = runner.invoke(cli.app, [])
    assert result.exit_code != 0
    assert "Usage" in result.stdout


def test_main_invokes_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The console-script entry point runs the typer app."""
    called: list[bool] = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    cli.main()
    assert called == [True]
