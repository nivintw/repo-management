# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Roadmap board automations: the read-and-operate layer behind the `projects` commands.

Where :class:`~repo_management.managers.projects.ProjectsManager` reconciles the board's
*schema*, this module operates on its *contents* — the behaviours GitHub's UI-only Workflows
and Insights tabs can't be codified into, moved into versioned code (nivintw/repo-management
#135):

- :func:`build_status_update` — a deterministic weekly health label + narrative
  (``projects status``).
- :func:`plan_reconcile` — derive each item's ``Status`` from its issue state and
  ``status:*`` labels, and archive long-closed items (``projects reconcile``). This is the
  fleet-wide net that lets the built-in Workflows tab be turned off: issue state and labels
  own board ``Status``, so a manual ``Status`` edit in the UI is reverted on the next sweep —
  and only on a *definitive* signal (an item with no ``status:*`` label is left alone).
- :func:`render_insights_svg` — the cross-repo "items by …" charts as a committed SVG
  (``projects insights``).

All three read the board once through :func:`fetch_board`, sharing the same
:class:`~repo_management.graphql.GraphQL` client and auth as the schema manager (no duplicate
GraphQL layer, per #135's acceptance criteria).
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from repo_management.changes import Action, Change
from repo_management.managers.projects import query_project

if TYPE_CHECKING:
    from collections.abc import Callable

    from repo_management.config import ProjectsConfig
    from repo_management.graphql import GraphQL

# handle-task-tracking status label -> board Status option name. Closed issues map to "Done"
# by state (below), not by label. An open item carrying none of these is left untouched.
_LABEL_STATUS = {
    "status:triage": "Todo",
    "status:ready": "Ready",
    "status:in-progress": "In Progress",
    "status:in-review": "In Review",
    "status:blocked": "Blocked",
}
_DONE = "Done"

# Open blocked-item count at which the board reads as AT_RISK.
_BLOCKED_HEAVY = 3

# The board's health label — the ProjectV2StatusUpdateStatus values (verified against the
# live schema), as a Literal so a typo'd label is a type error rather than an apply-time 422.
Health = Literal["INACTIVE", "ON_TRACK", "AT_RISK", "OFF_TRACK", "COMPLETE"]

_BOARD_QUERY = """
query($owner:String!, $number:Int!, $cursor:String){
  %(root)s(login:$owner){
    projectV2(number:$number){
      id title url
      statusUpdates(last:1){ nodes{ createdAt } }
      fields(first:50){
        nodes{
          ... on ProjectV2SingleSelectField { id name options{ id name } }
        }
      }
      items(first:100, after:$cursor){
        pageInfo{ hasNextPage endCursor }
        nodes{
          id
          isArchived
          fieldValues(first:20){
            nodes{
              ... on ProjectV2ItemFieldSingleSelectValue {
                name field{ ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldDateValue {
                date field{ ... on ProjectV2FieldCommon { name } }
              }
            }
          }
          content{
            ... on Issue {
              number title state closedAt
              repository{ name } labels(first:20){ nodes{ name } }
            }
            ... on PullRequest {
              number title state closedAt
              repository{ name } labels(first:20){ nodes{ name } }
            }
          }
        }
      }
    }
  }
}
"""

_SET_FIELD = """
mutation($input: UpdateProjectV2ItemFieldValueInput!){
  updateProjectV2ItemFieldValue(input:$input){ projectV2Item{ id } }
}
"""

_ARCHIVE = """
mutation($input: ArchiveProjectV2ItemInput!){
  archiveProjectV2Item(input:$input){ item{ id } }
}
"""

_POST_STATUS = """
mutation($input: CreateProjectV2StatusUpdateInput!){
  createProjectV2StatusUpdate(input:$input){ statusUpdate{ id status } }
}
"""


@dataclass
class BoardItem:
    """One item on the board, flattened from its issue/PR content and field values."""

    id: str
    repo: str | None
    number: int | None
    title: str | None
    state: str | None  # OPEN / CLOSED / MERGED
    closed_at: str | None
    labels: list[str] = field(default_factory=list)
    phase: str | None = None
    status: str | None = None
    start: str | None = None
    target: str | None = None

    @property
    def ref(self) -> str:
        """A short ``repo#number`` reference for display."""
        return f"{self.repo}#{self.number}"


@dataclass
class StatusFieldInfo:
    """The board's ``Status`` single-select field: its id and its option-name -> id map."""

    id: str
    options: dict[str, str]


@dataclass
class Board:
    """A snapshot of the roadmap board: metadata, its Status field, and its items."""

    id: str
    title: str
    url: str
    last_update: str | None
    phase_order: list[str]
    status_field: StatusFieldInfo | None
    items: list[BoardItem]


def _date(iso: str | None) -> dt.date | None:
    # Defensive against a non-ISO date from the API: these dates feed the unattended status
    # and reconcile runs, so a malformed value degrades to "unknown" rather than crashing them.
    if not iso:
        return None
    try:
        return dt.date.fromisoformat(iso[:10])
    except ValueError:
        return None


def fetch_board(gql: GraphQL, config: ProjectsConfig) -> Board:
    """Read the whole board — metadata, Status field, and every item — via GraphQL.

    Raises:
        ProjectNotFoundError: If the board can't be read (bad owner/number, or the token
            lacks the ``project`` scope).
    """
    meta: dict[str, Any] = {}
    phase_order: list[str] = []
    status_field: StatusFieldInfo | None = None
    items: list[BoardItem] = []
    cursor: str | None = None
    while True:
        project = query_project(gql, config, _BOARD_QUERY, cursor=cursor)
        if not meta:
            meta = project
            phase_order, status_field = _parse_fields(project["fields"]["nodes"])
        # Skip content-less draft nodes and ARCHIVED items: the Projects v2 items connection
        # returns archived items too (archiving only flips isArchived), so an archived item
        # left in the snapshot would be re-archived on every reconcile run — never reaching
        # "in sync" — and would keep skewing the status tallies and insights. Exclude them so
        # all three automations operate on the board's active items only.
        items.extend(
            _parse_item(node)
            for node in project["items"]["nodes"]
            if node and node.get("content") and not node.get("isArchived")
        )
        page = project["items"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    last_update = ((meta["statusUpdates"]["nodes"] or [{}])[0] or {}).get("createdAt")
    return Board(
        id=meta["id"],
        title=meta["title"],
        url=meta["url"],
        last_update=last_update,
        phase_order=phase_order,
        status_field=status_field,
        items=items,
    )


def _parse_fields(nodes: list[dict[str, Any]]) -> tuple[list[str], StatusFieldInfo | None]:
    phase_order: list[str] = []
    status_field: StatusFieldInfo | None = None
    for node in nodes:
        if not node:
            continue
        if node.get("name") == "Phase":
            phase_order = [option["name"] for option in node["options"]]
        elif node.get("name") == "Status":
            status_field = StatusFieldInfo(
                id=node["id"], options={o["name"]: o["id"] for o in node["options"]}
            )
    return phase_order, status_field


def _parse_item(node: dict[str, Any]) -> BoardItem:
    content = node["content"]
    values: dict[str, str] = {}
    for value in node["fieldValues"]["nodes"]:
        name = (value.get("field") or {}).get("name")
        resolved = value.get("name") or value.get("date")
        if name and resolved:
            values[name] = resolved
    labels = [label["name"] for label in (content.get("labels") or {}).get("nodes", [])]
    return BoardItem(
        id=node["id"],
        repo=(content.get("repository") or {}).get("name"),
        number=content.get("number"),
        title=content.get("title"),
        state=content.get("state"),
        closed_at=content.get("closedAt"),
        labels=labels,
        phase=values.get("Phase"),
        status=values.get("Status"),
        start=values.get("Start"),
        target=values.get("Target"),
    )


# --- Part 1: weekly status update -------------------------------------------------------


@dataclass
class _StatusFacts:
    """The tallies a status update is built from, computed once from the board."""

    closed: list[BoardItem]
    open_items: list[BoardItem]
    in_flight: list[BoardItem]
    blocked: list[BoardItem]
    ready: list[BoardItem]
    overdue_phases: list[str]


def build_status_update(board: Board, today: dt.date) -> tuple[Health, str]:
    """Compute a deterministic health label and a markdown body for a status update.

    The ladder is auditable — no model in the loop:
    COMPLETE (nothing open) > OFF_TRACK (a P1/Safety item overdue) > AT_RISK (any phase
    overdue, blocked-heavy, or stalled) > ON_TRACK.
    """
    items = [item for item in board.items if item.number is not None]
    window_start = _date(board.last_update) or (today - dt.timedelta(days=7))

    closed = [
        item
        for item in items
        if item.state in ("CLOSED", "MERGED")
        and (closed := _date(item.closed_at)) is not None
        and closed >= window_start
    ]
    open_items = [item for item in items if item.state == "OPEN"]
    blocked = [item for item in open_items if item.status == "Blocked"]
    ready = [item for item in open_items if item.status == "Ready"]
    overdue = [
        item for item in open_items if (target := _date(item.target)) is not None and target < today
    ]
    overdue_phases = sorted({item.phase for item in overdue if item.phase})
    safety_overdue = any(item.phase and item.phase.startswith("P1") for item in overdue)
    stalled = not closed and bool(ready)

    if not open_items:
        health: Health = "COMPLETE"
    elif safety_overdue:
        health = "OFF_TRACK"
    elif overdue_phases or stalled or len(blocked) >= _BLOCKED_HEAVY:
        health = "AT_RISK"
    else:
        health = "ON_TRACK"

    facts = _StatusFacts(
        closed=closed,
        open_items=open_items,
        in_flight=[item for item in open_items if item.status in ("In Progress", "In Review")],
        blocked=blocked,
        ready=ready,
        overdue_phases=overdue_phases,
    )
    return health, _status_body(today, facts, board)


def _status_body(today: dt.date, facts: _StatusFacts, board: Board) -> str:
    def line(item: BoardItem) -> str:
        phase = f" ({item.phase})" if item.phase else ""
        return f"- {item.ref}  {item.title}{phase}"

    parts = [
        f"**Week of {today:%b %d}** — {len(facts.closed)} closed, {len(facts.open_items)} open"
    ]
    parts.append("\n**Shipped this week**")
    parts += [line(item) for item in facts.closed[:8]] or ["- Nothing merged this week."]
    if facts.in_flight:
        refs = ", ".join(item.ref for item in facts.in_flight[:6])
        parts.append(f"\n**In flight:** {len(facts.in_flight)} — {refs}")
    blocked_refs = ", ".join(item.ref for item in facts.blocked) if facts.blocked else "none"
    parts.append(f"**Blocked:** {blocked_refs}")
    if facts.overdue_phases:
        parts.append(f"**Overdue phases:** {', '.join(facts.overdue_phases)}")

    upnext = _up_next(facts.ready, board.phase_order)
    if upnext:
        parts.append("\n**Up next**")
        parts += [line(item) for item in upnext]
    return "\n".join(parts)


def _up_next(ready: list[BoardItem], phase_order: list[str]) -> list[BoardItem]:
    """The Ready items in the earliest open phase — the natural next batch to pick up."""
    for phase in phase_order:
        candidates = [item for item in ready if item.phase == phase]
        if candidates:
            return candidates[:5]
    return ready[:5]


def days_since_last_update(board: Board, today: dt.date) -> int | None:
    """Days since the board's last status update, or ``None`` if there's never been one."""
    last = _date(board.last_update)
    if last is None:
        return None
    return (today - last).days


def post_status_update(gql: GraphQL, board: Board, health: Health, body: str) -> None:
    """Post a status update to the board, dating it to the board's item span when known."""
    starts = [d for item in board.items if (d := _date(item.start))]
    targets = [d for item in board.items if (d := _date(item.target))]
    field_input: dict[str, Any] = {"projectId": board.id, "status": health, "body": body}
    if starts:
        field_input["startDate"] = min(starts).isoformat()
    if targets:
        field_input["targetDate"] = max(targets).isoformat()
    gql.query(_POST_STATUS, input=field_input)


# --- Part 2: field reconcile + archive --------------------------------------------------


def desired_status(item: BoardItem) -> str | None:
    """The board ``Status`` an item should carry, or ``None`` when there's no definitive signal.

    Closed/merged issues are Done; an open issue's ``status:*`` label maps to the matching
    option. An open issue with no ``status:*`` label yields ``None`` — the reconcile leaves it
    untouched rather than guessing, so a manual value survives when labels can't override it.
    """
    if item.state in ("CLOSED", "MERGED"):
        return _DONE
    for label in item.labels:
        if label in _LABEL_STATUS:
            return _LABEL_STATUS[label]
    return None


def plan_reconcile(
    gql: GraphQL, board: Board, today: dt.date, *, archive_after_days: int | None = 14
) -> list[Change]:
    """Plan the Status corrections and archival needed to bring the board current.

    A ``Status`` change is emitted only when an item's desired status (from state/labels)
    differs from its current value *and* that option exists on the board. When
    ``archive_after_days`` is set, closed items whose ``closedAt`` is older than that are
    archived (kept visible while recently shipped); ``None`` disables archival.
    """
    status_field = board.status_field
    if status_field is None:
        return []
    changes: list[Change] = []

    for item in board.items:
        if item.number is None:
            continue
        wanted = desired_status(item)
        if wanted is not None and wanted != item.status and wanted in status_field.options:
            changes.append(_set_status_change(gql, board.id, status_field, item, wanted))

    if archive_after_days is not None:
        cutoff = today - dt.timedelta(days=archive_after_days)
        for item in board.items:
            closed = _date(item.closed_at)
            if item.state in ("CLOSED", "MERGED") and closed is not None and closed < cutoff:
                changes.append(_archive_change(gql, board.id, item))
    return changes


def _set_status_change(
    gql: GraphQL, project_id: str, status_field: StatusFieldInfo, item: BoardItem, wanted: str
) -> Change:
    def apply() -> None:
        gql.query(
            _SET_FIELD,
            input={
                "projectId": project_id,
                "itemId": item.id,
                "fieldId": status_field.id,
                "value": {"singleSelectOptionId": status_field.options[wanted]},
            },
        )

    return Change(
        domain="roadmap",
        action=Action.UPDATE,
        target=f"status:{item.ref}",
        before=item.status,
        after=wanted,
        apply=apply,
    )


def _archive_change(gql: GraphQL, project_id: str, item: BoardItem) -> Change:
    def apply() -> None:
        gql.query(_ARCHIVE, input={"projectId": project_id, "itemId": item.id})

    return Change(
        domain="roadmap",
        action=Action.DELETE,
        target=f"archive:{item.ref}",
        before=item.status,
        after=None,
        apply=apply,
    )


# --- Part 3: committed insights ---------------------------------------------------------


def _tally(items: list[BoardItem], key: Callable[[BoardItem], str | None]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        value = key(item)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def render_insights_svg(board: Board) -> str:
    """Render the board's cross-repo tallies as a self-contained bar-chart SVG.

    Charts items by Repository, by Phase, and by Status — the views the UI-only Insights tab
    can't export — as an SVG committed to the repo, so the numbers are versioned and shareable.
    """
    items = [item for item in board.items if item.number is not None]
    charts = [
        ("Items by repository", _tally(items, lambda i: i.repo)),
        ("Items by phase", _tally(items, lambda i: i.phase)),
        ("Items by status", _tally(items, lambda i: i.status)),
    ]
    row_h, bar_h, label_w, chart_gap, top = 22, 14, 170, 34, 30
    max_bar = 260
    width = label_w + max_bar + 60

    body: list[str] = []
    y = top
    overall_max = max((count for _, rows in charts for _, count in rows), default=1)
    for heading, rows in charts:
        body.append(f'<text x="12" y="{y}" class="h">{html.escape(heading)}</text>')
        y += 12
        for name, count in rows:
            bar = int(max_bar * count / overall_max)  # overall_max >= 1 (max default)
            body.append(f'<text x="12" y="{y + bar_h - 3}" class="l">{html.escape(name)}</text>')
            body.append(
                f'<rect x="{label_w}" y="{y}" width="{bar}" height="{bar_h}" class="b" rx="2"/>'
            )
            body.append(
                f'<text x="{label_w + bar + 6}" y="{y + bar_h - 3}" class="v">{count}</text>'
            )
            y += row_h
        y += chart_gap
    height = y

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, sans-serif" role="img" '
        f'aria-label="{html.escape(board.title)} insights">'
        "<style>"
        ".h{font-size:14px;font-weight:700;fill:#1f2328}"
        ".l{font-size:11px;fill:#57606a}.v{font-size:11px;fill:#1f2328}"
        ".b{fill:#218bff}"
        "</style>"
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>' + "".join(body) + "</svg>"
    )
