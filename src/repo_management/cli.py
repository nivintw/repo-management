# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Command-line interface: ``validate``, ``plan``, and ``apply``."""

from __future__ import annotations

import enum
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

if TYPE_CHECKING:
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
    try:
        client = get_client(token)
        return plan_config(client, config, force_secrets=force_secrets)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc
    except GithubException as exc:
        msg = f"GitHub API error: {exc.data or exc}"
        raise _fail(msg) from exc


def _print_plan(plan: RepoPlan) -> None:
    if plan.in_sync:
        console.print(f"[green]✓[/green] [bold]{plan.repo_name}[/bold]: in sync")
        return
    console.print(f"[bold]{plan.repo_name}[/bold] — {len(plan.changes)} change(s):")
    for change in plan.changes:
        console.print(f"  {change.describe()}")


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
    manager = ProjectsManager(GraphQLClient(get_client(token)))
    try:
        return desired, manager.plan(desired)
    except ProjectNotFoundError as exc:
        raise _fail(str(exc)) from exc
    except GithubException as exc:
        msg = f"GitHub API error: {exc.data or exc}"
        raise _fail(msg) from exc


def _print_project_plan(desired: ProjectsConfig, changes: list[Change]) -> None:
    board = f"{desired.owner}/#{desired.number}"
    if not changes:
        console.print(f"[green]✓[/green] [bold]{board}[/bold]: in sync")
        return
    console.print(f"[bold]{board}[/bold] — {len(changes)} change(s):")
    for change in changes:
        console.print(f"  {change.describe()}")


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
    _print_project_plan(desired, changes)
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
    _print_project_plan(desired, changes)
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


def main() -> None:
    """Console-script entry point."""
    app()
