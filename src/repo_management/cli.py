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
from rich.markup import escape
from rich.text import Text

from repo_management.client import api_message, get_client
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
from repo_management.managers.projects import ProjectError, ProjectsManager
from repo_management.reconciler import (
    ApplyReport,
    RepoPlan,
    apply_plan,
    plan_config,
    preflight_plan,
)
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
# emoji=False because every name this tool prints — a label, a secret, a webhook target — comes
# from user config, and targets are rendered `{kind}:{name}` followed by ": ". That makes
# `label:bug` into the shortcode `:bug:`, which Rich would substitute for 🐛 — silently replacing
# the identifier the operator needs with a pictogram, on the very line reporting a failure.
# `escape()` guards the `[markup]` half of this hazard and does nothing about shortcodes. The
# tool's own glyphs (✓, !) are literal characters, so disabling substitution costs nothing.
console = Console(emoji=False)
err_console = Console(stderr=True, emoji=False)


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
    # soft_wrap: an error can name every repo that failed, and hard-wrapping to the terminal
    # width would break a name across lines — leaving the one line that says what to re-run
    # neither greppable nor copy-pasteable out of a CI log.
    err_console.print(f"[red]error:[/red] {message}", soft_wrap=True)
    return typer.Exit(1)


@contextmanager
def _api_errors() -> Iterator[None]:
    """Map the expected API/config/IO failures to a clean ``error:`` exit, never a traceback."""
    try:
        yield
    except (ConfigError, ProjectError, OSError) as exc:
        raise _fail(str(exc)) from exc
    except GithubException as exc:
        msg = f"GitHub API error: {api_message(exc)}"
        raise _fail(msg) from exc


def _print_changes(title: str, changes: list[Change]) -> None:
    """Print a plan: an in-sync line, or a header plus one line per change (and diagnostic).

    Escapes the title and every change line: they carry names this tool doesn't control — a
    board's title, a field's, an option's — and Rich reads a `[...]` in one as console markup,
    which would silently swallow part of the name on the plan a user confirms, or abort the
    command outright on an unbalanced tag.
    """
    title = escape(title)
    if not changes:
        console.print(f"[green]✓[/green] [bold]{title}[/bold]: in sync")
        return
    # Count real changes and unresolved-value diagnostics separately — a diagnostic is a `!`
    # problem line, not a change, so folding it into the change count would mislead.
    actionable = sum(1 for change in changes if not change.unresolved)
    problems = sum(1 for change in changes if change.unresolved)
    header = f"{actionable} change(s)"
    if problems:
        header += f", {problems} unresolved"
    console.print(f"[bold]{title}[/bold] — {header}:")
    for change in changes:
        console.print(f"  {escape(change.describe())}")


def _apply_changes(changes: list[Change], *, yes: bool) -> None:
    """Confirm (unless ``yes``), apply each change, and report — or note nothing to do."""
    # Refuse a plan carrying an unresolvable value, before writing anything — the same gate
    # the per-repo `apply` holds. A diagnostic's own apply() raises RuntimeError, so without
    # this the confirm prompt would count it as a change and blow up partway through.
    problems = [change for change in changes if change.unresolved]
    if problems:
        msg = f"{len(problems)} unresolved value(s) — resolve them and re-run; nothing was applied."
        raise _fail(msg)
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
            msg = f"applying {change.target}: {api_message(exc)}"
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


def _detail(line: str, detail: str) -> None:
    """Print a reason to stderr, keeping any embedded traceback copy-pasteable.

    A diagnostic for an unanticipated failure carries a whole traceback, and Rich would hard-wrap
    it to the terminal width — breaking file paths mid-token so the stack can no longer be
    grepped or pasted. Print the first line styled, then the rest verbatim with wrapping off.
    """
    head, _, rest = detail.partition("\n")
    err_console.print(f"{line}: {escape(head)}", soft_wrap=True)
    if rest:
        err_console.print(Text(rest), soft_wrap=True)


def _partition(plans: list[RepoPlan]) -> tuple[list[RepoPlan], list[tuple[str, str]]]:
    """Split the fleet into the repos cleared to write and the ones held back, paired with why.

    A held-back repo is reduced to its name here: nothing downstream needs the rest of the plan,
    and carrying it invites a caller to act on a plan that was deliberately not applied.
    """
    ready: list[RepoPlan] = []
    held: list[tuple[str, str]] = []
    for repo_plan in plans:
        reason = preflight_plan(repo_plan)
        if reason is None:
            ready.append(repo_plan)
        else:
            held.append((repo_plan.repo_name, reason))
    return ready, held


def _report_skipped(skipped: list[tuple[str, str]]) -> None:
    """Name every repo being held back, and why — *before* the operator is asked to confirm.

    A preflight-held repo prints a perfectly ordinary diff (its payload only fails to resolve at
    write time), so without this the operator would scroll a diff, be prompted with a smaller
    count than it implies, and learn which repo was dropped only after the writes had run.
    """
    for repo_name, reason in skipped:
        _detail(f"[yellow]skipped[/yellow] {escape(repo_name)}", reason)


def _report_apply(reports: list[ApplyReport], skipped: list[tuple[str, str]]) -> None:
    """Summarize an apply run, then exit non-zero if any repo was skipped or any write failed.

    Every repository with an outcome is accounted for, applied or not — a run that reported only
    its successes would read as a clean sweep while leaving repos silently unreconciled. Repos
    already in sync have no outcome to report and are covered by the plan printed above.
    """
    applied = sum(len(report.applied) for report in reports)
    failed = sum(len(report.failed) for report in reports)
    abandoned = sum(len(report.abandoned) for report in reports)

    if not applied and not failed and not abandoned and not skipped:
        console.print("\n[green]nothing to do[/green]")
        return

    if applied:
        applied_repos = sum(1 for report in reports if report.applied)
        console.print(
            f"\n[green]✓ applied {applied} change(s) across {applied_repos} repo(s)[/green]"
        )

    for report in reports:
        for change, error in report.failed:
            _detail(
                f"[red]failed[/red] {escape(report.repo_name)} {escape(change.target)}",
                error,
            )
        for change, reason in report.abandoned:
            _detail(
                f"[yellow]not attempted[/yellow] {escape(report.repo_name)} "
                f"{escape(change.target)}",
                reason,
            )

    if not skipped and not failed and not abandoned:
        return
    # Name the repos, as `plan`'s roll-up does. A partially-applied fleet is the state an
    # operator most needs to size, and a bare count doesn't say which repos to re-run.
    parts = []
    if failed:
        broken = sorted({report.repo_name for report in reports if report.failed})
        parts.append(
            f"{failed} change(s) failed across {len(broken)} repo(s) ({', '.join(broken)})"
        )
    if abandoned:
        parts.append(f"{abandoned} change(s) not attempted")
    if skipped:
        names = ", ".join(name for name, _ in skipped)
        parts.append(f"{len(skipped)} repo(s) skipped ({names})")
    raise _fail("; ".join(parts) + ".")


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
    """Show the changes needed to reconcile each repo (no writes).

    Every repo is planned independently: one that can't be read contributes a `!` line and the
    rest still print their diff.
    """
    selected = _select(_load(config), repo)
    plans = _plans(selected, token, force_secrets=force_secrets)
    for repo_plan in plans:
        _print_plan(repo_plan)
    total = sum(len(item.actionable) for item in plans)
    console.print(f"\n{total} change(s) across {len(plans)} repo(s).")
    # A value that wouldn't resolve, or a domain that wouldn't read, is shown as a `!` line above
    # rather than aborting the run; roll it up here and exit non-zero so it's still a hard
    # failure — isolating a fault reports it differently, it doesn't forgive it.
    unhealthy = [item for item in plans if item.problems]
    if unhealthy:
        problems = sum(len(item.problems) for item in unhealthy)
        names = ", ".join(escape(item.repo_name) for item in unhealthy)
        msg = (
            f"{problems} problem(s) across {len(unhealthy)} repo(s) ({names}) "
            f"— see the ! line(s) above."
        )
        raise _fail(msg)


@app.command()
def apply(
    config: _ConfigOpt,
    repo: _RepoOpt = None,
    token: _TokenOpt = None,
    *,
    yes: _YesOpt = False,
    force_secrets: _ForceSecretsOpt = False,
) -> None:
    """Apply the planned changes to GitHub.

    Each repo stands alone. One that couldn't be fully planned, or whose payloads won't resolve,
    is skipped and reported while every healthy repo still applies; a failed write costs its own
    change rather than the rest of its repo. Anything short of a clean sweep exits non-zero.
    """
    selected = _select(_load(config), repo)
    plans = _plans(selected, token, force_secrets=force_secrets)
    for repo_plan in plans:
        _print_plan(repo_plan)

    # preflight_plan and apply_plan are total — they convert failures into reasons and reports
    # rather than raising. _api_errors is the belt-and-braces boundary for anything that slips
    # past them: an expected API/config failure still exits cleanly instead of tracebacking, and
    # a genuine bug in this tool (typer.Exit is a RuntimeError, so it passes straight through)
    # still surfaces loudly.
    with _api_errors():
        ready, skipped = _partition(plans)
        # Disclose every held-back repo before asking. The prompt's count covers only what will
        # actually be written, so an undisclosed skip would make it silently disagree with the
        # diff the operator just read.
        _report_skipped(skipped)
        total = sum(len(item.actionable) for item in ready)
        if total and not yes and not typer.confirm(f"\nApply {total} change(s)?"):
            msg = "aborted"
            raise _fail(msg)
        _report_apply([apply_plan(item) for item in ready if item.actionable], skipped)


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


def _project_changes(config: Path, token: str | None) -> tuple[str, list[Change]]:
    """Return the board's display label and the changes needed to reconcile it."""
    desired = _load_projects(config)
    with _api_errors():
        manager = ProjectsManager(GraphQLClient(get_client(token)))
        changes = manager.plan(desired)
        return _board_label(desired, manager.number), changes


def _board_label(desired: ProjectsConfig, number: int | None) -> str:
    """The board's label, naming the concrete number a ``title`` resolved to.

    A title alone doesn't say *which* board a write lands on — and an option removal drops
    that option from every item that had it — so a plan a user confirms should name the board
    it actually resolved to. A number-addressed config already reads as `owner/#N`, and a
    board that doesn't exist yet has no number to name.
    """
    if desired.number is not None or number is None:
        return desired.label
    return f"{desired.label} (#{number})"


@projects_app.command("validate")
def projects_validate(config: _ProjectsConfigOpt = Path("config/projects.yaml")) -> None:
    """Validate the projects board config without contacting GitHub."""
    loaded = _load_projects(config)
    console.print(
        f"[green]✓[/green] {escape(str(config))} is valid "
        f"({len(loaded.fields)} field(s) on {escape(loaded.label)})"
    )


@projects_app.command("plan")
def projects_plan(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
) -> None:
    """Show the changes needed to reconcile the board (no writes)."""
    label, changes = _project_changes(config, token)
    _print_changes(label, changes)
    problems = [change for change in changes if change.unresolved]
    console.print(f"\n{len(changes) - len(problems)} change(s).")
    # Exit non-zero on an unresolvable value, as the per-repo `plan` does — otherwise a board
    # that can never reach desired state still reports success.
    if problems:
        msg = f"{len(problems)} unresolved value(s) — see the ! line(s) above."
        raise _fail(msg)


@projects_app.command("apply")
def projects_apply(
    config: _ProjectsConfigOpt = Path("config/projects.yaml"),
    token: _TokenOpt = None,
    *,
    yes: _YesOpt = False,
) -> None:
    """Apply the board changes to GitHub, creating the board first if it doesn't exist."""
    label, changes = _project_changes(config, token)
    _print_changes(label, changes)
    # Inside _api_errors because a board create resolves GitHub state *during* apply — unlike
    # a field mutation, its closure can raise ProjectError, which would otherwise traceback.
    with _api_errors():
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
