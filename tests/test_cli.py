# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the command-line interface."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from github import GithubException
from typer.testing import CliRunner

from repo_management import cli
from repo_management.changes import Action, Change
from repo_management.config import Config, ConfigError
from repo_management.reconciler import RepoPlan
from repo_management.roadmap import BoardItem, StatusFieldInfo

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


def _diagnostic() -> Change:
    def _raise() -> None:
        msg = "a diagnostic must never be applied"
        raise AssertionError(msg)

    return Change("variables", Action.UPDATE, "variable:REGION", None, None, _raise, error="unset")


def test_plan_hard_errors_on_unresolved_but_shows_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan prints every resolvable line, then exits non-zero because a value is unresolved."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli,
        "plan_config",
        lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [_change(), _diagnostic()])],
    )

    result = runner.invoke(cli.app, ["plan", "--config", str(write(tmp_path))])

    assert result.exit_code == 1
    assert "description" in result.stdout  # the resolvable change still shows
    # The `!` diagnostic line renders with target + error (Rich eats the [domain] tag on every
    # line, diagnostics and ordinary changes alike — a pre-existing display quirk, not this fix's).
    assert "variable:REGION: unset" in result.stdout
    assert "1 change(s)" in result.stdout  # the diagnostic isn't counted as a change
    assert "unresolved value(s)" in result.stderr


def test_apply_refuses_when_a_value_is_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply refuses to write anything when the plan carries an unresolved value."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [_diagnostic()])]
    )
    called: list[str] = []
    monkeypatch.setattr(cli, "apply_plan", lambda plan: called.append(plan.repo_name))

    result = runner.invoke(cli.app, ["apply", "--config", str(write(tmp_path)), "--yes"])

    assert result.exit_code == 1
    assert "unresolved value(s)" in result.stderr
    assert called == []  # nothing was applied


def test_apply_preflight_refuses_missing_secret_with_zero_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secret whose value can't be resolved aborts apply before any write (preflight pass).

    Secret values resolve lazily at the write, so they never become plan-time diagnostics; the
    preflight pass is what restores apply's pre-write, all-or-nothing guarantee for them.
    """

    def _bad_preflight() -> None:
        msg = "environment variable 'TOK_SRC' is not set or is empty"
        raise ConfigError(msg)

    applied: list[str] = []
    change = Change(
        "secrets",
        Action.CREATE,
        "secret:TOK",
        None,
        "(set)",
        lambda: applied.append("TOK"),
        secret=True,
        preflight=_bad_preflight,
    )
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(
        cli, "plan_config", lambda _c, _cfg, **_kw: [RepoPlan("owner/repo", [change])]
    )
    ran: list[str] = []
    monkeypatch.setattr(cli, "apply_plan", lambda plan: ran.append(plan.repo_name))

    result = runner.invoke(cli.app, ["apply", "--config", str(write(tmp_path)), "--yes"])

    assert result.exit_code == 1
    assert applied == []  # the write closure never ran
    assert ran == []  # apply_plan never reached — aborted before the write loop
    assert "TOK_SRC" in result.stderr


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


def _fleet(tmp_path: Path) -> Path:
    """Write a two-file config dir (one repo each) and return the directory."""
    (tmp_path / "a.yml").write_text("repos:\n  - owner/beta\n", encoding="utf-8")
    (tmp_path / "b.yml").write_text("repos:\n  - owner/alpha\n", encoding="utf-8")
    # A *.yaml layer must be ignored (it is a base, not an applied config).
    (tmp_path / "base.yaml").write_text("repos:\n  - owner/should-be-ignored\n", encoding="utf-8")
    return tmp_path


def test_list_repos_lines_sorted(tmp_path: Path) -> None:
    """list-repos prints the union of *.yml repos, sorted, one per line, skipping *.yaml."""
    result = runner.invoke(cli.app, ["list-repos", "--config-dir", str(_fleet(tmp_path))])

    assert result.exit_code == 0
    assert result.stdout == "owner/alpha\nowner/beta\n"


def test_list_repos_names_are_owner_relative_csv(tmp_path: Path) -> None:
    """The names format emits one comma-separated line of bare names for a scoped token."""
    result = runner.invoke(
        cli.app, ["list-repos", "--config-dir", str(_fleet(tmp_path)), "--format", "names"]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "alpha,beta"


def test_list_repos_empty_dir_errors(tmp_path: Path) -> None:
    """An empty config dir exits non-zero rather than printing an empty (fleet-wiping) set."""
    result = runner.invoke(cli.app, ["list-repos", "--config-dir", str(tmp_path)])

    assert result.exit_code == 1


def test_list_repos_names_rejects_multiple_owners(tmp_path: Path) -> None:
    """`--format names` fails loud on a multi-owner fleet rather than scoping the token wrong.

    A GitHub App token is per-owner, so stripping the owner from a cross-owner fleet would
    scope the token to the wrong owner's same-named repo. The command must error instead.
    """
    (tmp_path / "a.yml").write_text("repos:\n  - alice/svc\n", encoding="utf-8")
    (tmp_path / "b.yml").write_text("repos:\n  - bob/svc\n", encoding="utf-8")

    result = runner.invoke(
        cli.app, ["list-repos", "--config-dir", str(tmp_path), "--format", "names"]
    )

    assert result.exit_code == 1
    # The human-default `lines` format has no such restriction.
    lines = runner.invoke(cli.app, ["list-repos", "--config-dir", str(tmp_path)])
    assert lines.exit_code == 0
    assert lines.stdout == "alice/svc\nbob/svc\n"


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


# --- projects sub-app -------------------------------------------------------------------

PROJECTS = "owner: nivintw\nnumber: 2\nfields:\n  - name: Target\n    data_type: date\n"


def write_projects(tmp_path: Path, text: str = PROJECTS) -> Path:
    """Write a projects board config file and return its path."""
    path = tmp_path / "projects.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _stub_manager(monkeypatch: pytest.MonkeyPatch, plan_result: list[Change] | Exception) -> None:
    """Wire the projects CLI onto a fake manager whose `plan` returns/raises `plan_result`."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "GraphQLClient", lambda _client: object())

    class _Manager:
        def __init__(self, _gql: object) -> None: ...

        def plan(self, _desired: object) -> list[Change]:
            if isinstance(plan_result, Exception):
                raise plan_result
            return plan_result

    monkeypatch.setattr(cli, "ProjectsManager", _Manager)


def test_projects_validate_ok(tmp_path: Path) -> None:
    """Projects validate reports a valid board config."""
    result = runner.invoke(cli.app, ["projects", "validate", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 0
    assert "valid" in result.stdout


def test_projects_validate_bad(tmp_path: Path) -> None:
    """Projects validate exits non-zero on an invalid board config."""
    path = write_projects(tmp_path, "owner: nivintw\nnumber: 2\nfields: []\n")
    result = runner.invoke(cli.app, ["projects", "validate", "-c", str(path)])
    assert result.exit_code == 1


def test_projects_plan_shows_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Projects plan prints the changes the manager returns."""
    _stub_manager(monkeypatch, [_change()])
    result = runner.invoke(cli.app, ["projects", "plan", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 0
    assert "1 change(s)" in result.stdout


def test_projects_plan_in_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Projects plan reports an in-sync board."""
    _stub_manager(monkeypatch, [])
    result = runner.invoke(cli.app, ["projects", "plan", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 0
    assert "in sync" in result.stdout


def test_projects_apply_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Projects apply runs each change's apply() after confirmation."""
    applied: list[bool] = []
    change = Change("projects", Action.CREATE, "field:X", None, {}, lambda: applied.append(True))
    _stub_manager(monkeypatch, [change])
    result = runner.invoke(
        cli.app, ["projects", "apply", "-c", str(write_projects(tmp_path)), "--yes"]
    )
    assert result.exit_code == 0
    assert applied == [True]
    assert "applied 1 change(s)" in result.stdout


def test_projects_apply_nothing_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Projects apply short-circuits when the board is already in sync."""
    _stub_manager(monkeypatch, [])
    result = runner.invoke(
        cli.app, ["projects", "apply", "-c", str(write_projects(tmp_path)), "--yes"]
    )
    assert result.exit_code == 0
    assert "nothing to do" in result.stdout


def test_projects_apply_aborts_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Declining the confirmation prompt aborts without applying."""
    applied: list[bool] = []
    change = Change("projects", Action.CREATE, "field:X", None, {}, lambda: applied.append(True))
    _stub_manager(monkeypatch, [change])
    result = runner.invoke(
        cli.app, ["projects", "apply", "-c", str(write_projects(tmp_path))], input="n\n"
    )
    assert result.exit_code == 1
    assert applied == []


def test_projects_plan_board_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A board the token can't read exits non-zero with the error surfaced."""
    _stub_manager(monkeypatch, cli.ProjectNotFoundError("board not found"))
    result = runner.invoke(cli.app, ["projects", "plan", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 1


# --- projects roadmap automations (status / reconcile / insights) -----------------------


def _stub_board(monkeypatch: pytest.MonkeyPatch, board: cli.Board) -> None:
    """Wire the roadmap commands onto a fixed board, bypassing the network."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "GraphQLClient", lambda _client: object())
    monkeypatch.setattr(cli, "fetch_board", lambda _gql, _cfg: board)


def _board(
    last_update: str | None = None,
    *,
    items: list[BoardItem] | None = None,
    with_status_field: bool = True,
) -> cli.Board:
    # Default: one closed item, so the board is non-empty (the status command's empty-board
    # guard would otherwise reject it) and computes COMPLETE (nothing open).
    return cli.Board(
        id="PROJ",
        title="Fleet Roadmap",
        url="https://example/2",
        last_update=last_update,
        phase_order=[],
        status_field=StatusFieldInfo(id="F", options={"Todo": "o"}) if with_status_field else None,
        items=[
            BoardItem(
                id="I1", repo="r", number=1, title="t", state="CLOSED", closed_at="2026-07-01"
            )
        ]
        if items is None
        else items,
    )


def test_projects_status_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Status --dry-run prints the computed label and body without posting."""
    _stub_board(monkeypatch, _board())
    posted: list[bool] = []
    monkeypatch.setattr(cli, "post_status_update", lambda *_a: posted.append(True))
    result = runner.invoke(
        cli.app, ["projects", "status", "-c", str(write_projects(tmp_path)), "--dry-run"]
    )
    assert result.exit_code == 0
    assert posted == []
    assert "COMPLETE" in result.stdout  # empty board => nothing open => COMPLETE


def test_projects_status_posts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Status posts when no recent update exists."""
    _stub_board(monkeypatch, _board())
    posted: list[str] = []
    monkeypatch.setattr(
        cli, "post_status_update", lambda _g, _b, health, _body: posted.append(health)
    )
    result = runner.invoke(cli.app, ["projects", "status", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 0
    assert posted == ["COMPLETE"]


def test_projects_status_dedupes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Status skips (no post) when a recent update is within the dedupe window."""
    _stub_board(monkeypatch, _board(last_update="2026-07-08T00:00:00Z"))
    monkeypatch.setattr(cli.dt, "datetime", _FixedDatetime)
    posted: list[bool] = []
    monkeypatch.setattr(cli, "post_status_update", lambda *_a: posted.append(True))
    result = runner.invoke(cli.app, ["projects", "status", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 0
    assert posted == []
    assert "skip" in result.stdout


def test_projects_reconcile_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconcile --dry-run prints planned changes without applying."""
    _stub_board(monkeypatch, _board())
    applied: list[bool] = []
    change = Change(
        "roadmap", Action.UPDATE, "status:x#1", "Todo", "Done", lambda: applied.append(True)
    )
    monkeypatch.setattr(cli, "plan_reconcile", lambda *_a, **_k: [change])
    result = runner.invoke(
        cli.app, ["projects", "reconcile", "-c", str(write_projects(tmp_path)), "--dry-run"]
    )
    assert result.exit_code == 0
    assert applied == []
    assert "1 change(s)" in result.stdout


def test_projects_reconcile_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconcile --yes applies each planned change."""
    _stub_board(monkeypatch, _board())
    applied: list[bool] = []
    change = Change(
        "roadmap", Action.UPDATE, "status:x#1", "Todo", "Done", lambda: applied.append(True)
    )
    monkeypatch.setattr(cli, "plan_reconcile", lambda *_a, **_k: [change])
    result = runner.invoke(
        cli.app, ["projects", "reconcile", "-c", str(write_projects(tmp_path)), "--yes"]
    )
    assert result.exit_code == 0
    assert applied == [True]


def test_projects_reconcile_in_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconcile reports an in-sync board when nothing needs changing."""
    _stub_board(monkeypatch, _board())
    monkeypatch.setattr(cli, "plan_reconcile", lambda *_a, **_k: [])
    result = runner.invoke(cli.app, ["projects", "reconcile", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 0
    assert "in sync" in result.stdout


def test_projects_insights_writes_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Insights renders the SVG to the requested output path."""
    _stub_board(monkeypatch, _board())
    monkeypatch.setattr(cli, "render_insights_svg", lambda _board: "<svg>ok</svg>")
    out = tmp_path / "sub" / "insights.svg"
    result = runner.invoke(
        cli.app,
        ["projects", "insights", "-c", str(write_projects(tmp_path)), "-o", str(out)],
    )
    assert result.exit_code == 0
    assert out.read_text(encoding="utf-8") == "<svg>ok</svg>"


def test_projects_plan_github_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GithubException while planning the schema exits cleanly."""
    _stub_manager(monkeypatch, GithubException(403, {"message": "nope"}, None))
    result = runner.invoke(cli.app, ["projects", "plan", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 1


def test_projects_apply_github_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GithubException while applying a schema change exits cleanly."""

    def _boom() -> None:
        raise GithubException(422, {"message": "bad"}, None)

    _stub_manager(monkeypatch, [Change("projects", Action.CREATE, "field:X", None, {}, _boom)])
    result = runner.invoke(
        cli.app, ["projects", "apply", "-c", str(write_projects(tmp_path)), "--yes"]
    )
    assert result.exit_code == 1


def test_projects_status_empty_board_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Status refuses to post on a board with no issues/PRs (#135 fail-loud), even with --force."""
    _stub_board(monkeypatch, _board(items=[]))
    posted: list[bool] = []
    monkeypatch.setattr(cli, "post_status_update", lambda *_a: posted.append(True))
    result = runner.invoke(
        cli.app, ["projects", "status", "-c", str(write_projects(tmp_path)), "--force"]
    )
    assert result.exit_code == 1
    assert posted == []


def test_projects_reconcile_no_status_field_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconcile fails loud (not a green no-op) when the board has no Status field."""
    _stub_board(monkeypatch, _board(with_status_field=False))
    result = runner.invoke(cli.app, ["projects", "reconcile", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 1


def test_projects_reconcile_negative_archive_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A negative --archive-after-days disables archival (passes archive_after_days=None)."""
    _stub_board(monkeypatch, _board())
    seen: list[int | None] = []

    def _capture(
        _gql: object, _board: object, _today: object, *, archive_after_days: int | None
    ) -> list[Change]:
        seen.append(archive_after_days)
        return []

    monkeypatch.setattr(cli, "plan_reconcile", _capture)
    result = runner.invoke(
        cli.app,
        [
            "projects",
            "reconcile",
            "-c",
            str(write_projects(tmp_path)),
            "--archive-after-days",
            "-1",
        ],
    )
    assert result.exit_code == 0
    assert seen == [None]


def test_projects_status_board_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A board the token can't read exits non-zero from a roadmap command."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "GraphQLClient", lambda _client: object())

    def _raise(_gql: object, _cfg: object) -> cli.Board:
        msg = "board not found"
        raise cli.ProjectNotFoundError(msg)

    monkeypatch.setattr(cli, "fetch_board", _raise)
    result = runner.invoke(cli.app, ["projects", "status", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 1


def test_projects_insights_github_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GithubException while reading the board exits cleanly from a roadmap command."""
    monkeypatch.setattr(cli, "get_client", lambda _token: object())
    monkeypatch.setattr(cli, "GraphQLClient", lambda _client: object())

    def _raise(_gql: object, _cfg: object) -> cli.Board:
        raise GithubException(403, {"message": "nope"}, None)

    monkeypatch.setattr(cli, "fetch_board", _raise)
    result = runner.invoke(cli.app, ["projects", "insights", "-c", str(write_projects(tmp_path))])
    assert result.exit_code == 1


def test_projects_reconcile_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Declining the reconcile confirmation aborts without applying."""
    _stub_board(monkeypatch, _board())
    applied: list[bool] = []
    change = Change(
        "roadmap", Action.UPDATE, "status:x#1", "Todo", "Done", lambda: applied.append(True)
    )
    monkeypatch.setattr(cli, "plan_reconcile", lambda *_a, **_k: [change])
    result = runner.invoke(
        cli.app, ["projects", "reconcile", "-c", str(write_projects(tmp_path))], input="n\n"
    )
    assert result.exit_code == 1
    assert applied == []


def test_projects_reconcile_apply_github_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GithubException while applying a reconcile change exits cleanly."""
    _stub_board(monkeypatch, _board())

    def _boom() -> None:
        raise GithubException(422, {"message": "bad"}, None)

    change = Change("roadmap", Action.UPDATE, "status:x#1", "Todo", "Done", _boom)
    monkeypatch.setattr(cli, "plan_reconcile", lambda *_a, **_k: [change])
    result = runner.invoke(
        cli.app, ["projects", "reconcile", "-c", str(write_projects(tmp_path)), "--yes"]
    )
    assert result.exit_code == 1


class _FixedDatetime(dt.datetime):
    """A datetime whose `now()` is pinned, so the dedupe window is deterministic."""

    @classmethod
    def now(cls, tz: dt.tzinfo | None = None) -> _FixedDatetime:
        return cls(2026, 7, 8, tzinfo=tz)
