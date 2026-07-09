# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Command-line interface: ``validate``, ``plan``, and ``apply``."""

from __future__ import annotations

import datetime as dt
import enum
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from github import GithubException
from rich.console import Console

from repo_management.client import get_client
from repo_management.config import (
    Config,
    ConfigError,
    ProjectsConfig,
    fleet_repo_names,
    fleet_repos,
    load_config,
    load_projects_config,
)
from repo_management.graphql import GraphQLClient
from repo_management.managers.projects import ProjectNotFoundError, ProjectsManager
from repo_management.reconciler import RepoPlan, apply_plan, plan_config
from repo_management.roadmap import (
    Board,
    build_status_update,
    days_since_last_update,
    fetch_board,
    plan_reconcile,
    post_status_update,
    render_insights_svg,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from repo_management.changes import Change

app = typer.Typer(
    help="YAML-config-driven GitHub repository manager.",
    no_args_is_help=True,
    add_completion=False,
    # Never dump frame locals on error — they can contain the token or secret values.
    pretty_exceptions_show_locals=False,
)
console = Console()
err_console = Console(stderr=True)


class ReposFormat(enum.StrEnum):
    """Output shape for ``list-repos``."""

    lines = "lines"
    names = "names"


_ConfigOpt = Annotated[
    Path,
    typer.Option("--config", "-c", help="Path to the YAML config file.", show_default=False),
]
_ConfigDirOpt = Annotated[
    Path,
    typer.Option("--config-dir", help="Directory of applied config/*.yml files."),
]
_ReposFormatOpt = Annotated[
    ReposFormat,
    typer.Option(
        "--format",
        "-f",
        help="lines: owner/repo, one per line. names: bare repo names, comma-separated "
        "(for a scoped App token's `repositories:`).",
    ),
]
_RepoOpt = Annotated[
    str | None,
    typer.Option("--repo", "-r", help="Limit to a single repo (owner/name).", show_default=False),
]
_TokenOpt = Annotated[
    str | None,
    typer.Option("--token", help="GitHub token (defaults to $GITHUB_TOKEN).", show_default=False),
]
_YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")]
_ForceSecretsOpt = Annotated[
    bool,
    typer.Option(
        "--force-secrets",
        help="Re-push existing secret values (for rotation). By default secrets already "
        "present on the repo are left untouched.",
    ),
]


def _fail(message: str) -> typer.Exit:
    err_console.print(f"[red]error:[/red] {message}")
    return typer.Exit(1)


@contextmanager
def _api_errors() -> Iterator[None]:
    """Map the expected API/config/IO failures to a clean ``error:`` exit, never a traceback."""
    try:
        yield
    except (ConfigError, ProjectNotFoundError, OSError) as exc:
        raise _fail(str(exc)) from exc
    except GithubException as exc:
        msg = f"GitHub API error: {exc.data or exc}"
        raise _fail(msg) from exc


def _print_changes(title: str, changes: list[Change]) -> None:
    """Print a plan: an in-sync line, or a header plus one line per change."""
    if not changes:
        console.print(f"[green]✓[/green] [bold]{title}[/bold]: in sync")
        return
    console.print(f"[bold]{title}[/bold] — {len(changes)} change(s):")
    for change in changes:
        console.print(f"  {change.describe()}")


def _apply_changes(changes: list[Change], *, yes: bool) -> None:
    """Confirm (unless ``yes``), apply each change, and report — or note nothing to do."""
    if not changes:
        console.print("\n[green]nothing to do[/green]")
        return
    if not yes and not typer.confirm(f"\nApply {len(changes)} change(s)?"):
        msg = "aborted"
        raise _fail(msg)
    for change in changes:
        try:
            change.apply()
        except GithubException as exc:
            msg = f"applying {change.target}: {exc.data or exc}"
            raise _fail(msg) from exc
    console.print(f"\n[green]✓ applied {len(changes)} change(s)[/green]")


def _load(config: Path) -> Config:
    try:
        return load_config(config)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc


def _select(config: Config, repo: str | None) -> Config:
    if repo is None:
        return config
    if repo not in config.repos:
        msg = f"repo {repo!r} not found in config"
        raise _fail(msg)
    # Narrow the repo list to the one requested; the shared config carries over.
    return config.model_copy(update={"repos": [repo]})


def _plans(config: Config, token: str | None, *, force_secrets: bool = False) -> list[RepoPlan]:
    with _api_errors():
        client = get_client(token)
        return plan_config(client, config, force_secrets=force_secrets)


def _print_plan(plan: RepoPlan) -> None:
    _print_changes(plan.repo_name, plan.changes)


@app.command()
def validate(config: _ConfigOpt) -> None:
    """Validate the config file without contacting GitHub."""
    loaded = _load(config)
    console.print(f"[green]✓[/green] {config} is valid ({len(loaded.repos)} repo(s))")


@app.command(name="list-repos")
def list_repos(
    config_dir: _ConfigDirOpt = Path("config"),
    output_format: _ReposFormatOpt = ReposFormat.lines,
) -> None:
    """List the managed-repo fleet: the union of every ``config/*.yml`` ``repos:`` list.

    No network access — reads the configs only. The ``names`` format prints a single
    comma-separated line of bare repo names, sized to scope the central Renovate runner's
    GitHub App token to exactly the fleet (``repositories:``), so the token itself — not a
    soft filter — is the boundary on which repos Renovate can touch.
    """
    # Plain stdout (not the rich console): keep machine output unwrapped and unstyled so a
    # long line survives a narrow CI terminal intact.
    try:
        if output_format is ReposFormat.names:
            # Bare names for a scoped App token's owner-relative `repositories:`; fleet_repo_names
            # enforces the single-owner precondition (a GitHub App token is per-owner) and is the
            # same derivation apply/plan's token mint uses.
            typer.echo(",".join(fleet_repo_names(config_dir)))
        else:
            for repo in fleet_repos(config_dir):
                typer.echo(repo)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc


@app.command()
def plan(
    config: _ConfigOpt,
    repo: _RepoOpt = None,
    token: _TokenOpt = None,
    *,
    force_secrets: _ForceSecretsOpt = False,
) -> None:
    """Show the changes needed to reconcile each repo (no writes)."""
    selected = _select(_load(config), repo)
    plans = _plans(selected, token, force_secrets=force_secrets)
    for repo_plan in plans:
        _print_plan(repo_plan)
    total = sum(len(item.changes) for item in plans)
    console.print(f"\n{total} change(s) across {len(plans)} repo(s).")


@app.command()
def apply(
    config: _ConfigOpt,
    repo: _RepoOpt = None,
    token: _TokenOpt = None,
    *,
    yes: _YesOpt = False,
    force_secrets: _ForceSecretsOpt = False,
) -> None:
    """Apply the planned changes to GitHub."""
    selected = _select(_load(config), repo)
    plans = _plans(selected, token, force_secrets=force_secrets)
    for repo_plan in plans:
        _print_plan(repo_plan)
    total = sum(len(item.changes) for item in plans)
    if total == 0:
        console.print("\n[green]nothing to do[/green]")
        return
    if not yes and not typer.confirm(f"\nApply {total} change(s)?"):
        msg = "aborted"
        raise _fail(msg)
    for repo_plan in plans:
        try:
            apply_plan(repo_plan)
        except GithubException as exc:
            msg = f"applying {repo_plan.repo_name}: {exc.data or exc}"
            raise _fail(msg) from exc
    console.print(f"\n[green]✓ applied {total} change(s)[/green]")


projects_app = typer.Typer(
    help="Manage a GitHub Projects v2 board: its field schema and roadmap automations.",
    no_args_is_help=True,
)
app.add_typer(projects_app, name="projects")

_ProjectsConfigOpt = Annotated[
    Path,
    typer.Option("--config", "-c", help="Path to the projects board config."),
]


def _load_projects(config: Path) -> ProjectsConfig:
    try:
        return load_projects_config(config)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc


def _project_changes(config: Path, token: str | None) -> tuple[ProjectsConfig, list[Change]]:
    desired = _load_projects(config)
    with _api_errors():
        manager = ProjectsManager(GraphQLClient(get_client(token)))
        return desired, manager.plan(desired)


@projects_app.command("validate")
def projects_validate(config: _ProjectsConfigOpt = Path("config/projects.yaml")) -> None:
    """Validate the projects board config without contacting GitHub."""
    loaded = _load_projects(config)
    console.print(
        f"[green]✓[/green] {config} is valid ({len(loaded.fields)} field(s) on "
        f"{loaded.owner}/#{loaded.number})"
    )


@projects_app.command("plan")
def projects_plan(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
) -> None:
    """Show the changes needed to reconcile the board's field schema (no writes)."""
    desired, changes = _project_changes(config, token)
    _print_changes(f"{desired.owner}/#{desired.number}", changes)
    console.print(f"\n{len(changes)} change(s).")


@projects_app.command("apply")
def projects_apply(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
    *,
    yes: _YesOpt = False,
) -> None:
    """Apply the board field-schema changes to GitHub."""
    desired, changes = _project_changes(config, token)
    _print_changes(f"{desired.owner}/#{desired.number}", changes)
    _apply_changes(changes, yes=yes)


# The roadmap automations (status / reconcile / insights) all read the board once, sharing
# the schema manager's GraphQL client and the same board config file.
_STATUS_DEDUPE_DAYS = 6

_DryRunOpt = Annotated[
    bool, typer.Option("--dry-run", help="Compute and print, but make no writes.")
]


def _load_board(config: Path, token: str | None) -> tuple[GraphQLClient, Board]:
    desired = _load_projects(config)
    with _api_errors():
        gql = GraphQLClient(get_client(token))
        return gql, fetch_board(gql, desired)


@projects_app.command("status")
def projects_status(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
    *,
    dry_run: _DryRunOpt = False,
    force: Annotated[
        bool, typer.Option("--force", help="Post even if a recent update exists.")
    ] = False,
) -> None:
    """Post a weekly roadmap status update (deterministic health label + narrative)."""
    today = dt.datetime.now(tz=dt.UTC).date()
    gql, board = _load_board(config, token)
    # Fail loud on an empty/misconfigured board rather than stamping a bogus "COMPLETE / 0
    # open" update on it (#135): a board with no issue/PR items — genuinely empty, freshly
    # created, all-draft, or pointed at the wrong number — is a failure, not a finished
    # roadmap. This gates even --force and --dry-run, since it's never a valid state to post.
    if not any(item.number is not None for item in board.items):
        msg = f"board {board.title} has no issues/PRs — refusing to post a status update"
        raise _fail(msg)
    days = days_since_last_update(board, today)
    if not force and not dry_run and days is not None and days < _STATUS_DEDUPE_DAYS:
        console.print(
            f"[yellow]skip[/yellow]: last update was {days}d ago (<{_STATUS_DEDUPE_DAYS})"
        )
        return
    health, body = build_status_update(board, today)
    if dry_run:
        console.print(f"[bold]{board.url}[/bold]\n[bold]{health}[/bold]\n\n{body}")
        return
    with _api_errors():
        post_status_update(gql, board, health, body)
    console.print(f"[green]✓[/green] posted [bold]{health}[/bold] status update to {board.url}")


@projects_app.command("reconcile")
def projects_reconcile(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
    *,
    yes: _YesOpt = False,
    dry_run: _DryRunOpt = False,
    archive_after_days: Annotated[
        int,
        typer.Option(
            "--archive-after-days",
            help="Archive items closed longer ago than this (negative disables archival).",
        ),
    ] = 14,
) -> None:
    """Reconcile each item's Status from its issue state + labels, and archive old closed items."""
    today = dt.datetime.now(tz=dt.UTC).date()
    gql, board = _load_board(config, token)
    # Fail loud rather than silently reporting "in sync": a board with no Status field can't
    # be reconciled at all, and a green no-op every 6h would let its Status drift unnoticed.
    if board.status_field is None:
        msg = f"board {board.title} has no 'Status' field — run `projects apply` to create it first"
        raise _fail(msg)
    archive = None if archive_after_days < 0 else archive_after_days
    changes = plan_reconcile(gql, board, today, archive_after_days=archive)

    _print_changes(board.title, changes)
    if dry_run or not changes:
        return
    _apply_changes(changes, yes=yes)


@projects_app.command("insights")
def projects_insights(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Where to write the insights SVG.")
    ] = Path("docs/roadmap/insights.svg"),
) -> None:
    """Render the board's cross-repo insights to a committed SVG."""
    _gql, board = _load_board(config, token)
    svg = render_insights_svg(board)
    with _api_errors():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(svg, encoding="utf-8")
    console.print(f"[green]✓[/green] wrote insights for {board.title} to {output}")


def main() -> None:
    """Console-script entry point."""
    app()
