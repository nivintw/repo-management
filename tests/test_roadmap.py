# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the roadmap board automations (status / reconcile / insights).

Scope note: these unit tests exercise the parsing/computation and assert the exact GraphQL
mutation *payloads*, but they cannot validate the hand-written query/mutation *documents*
against GitHub's live schema — a mistyped field name or wrong input shape fails only at
runtime against the API. That conformance is deliberately out of scope for the unit suite
(the queries were verified by hand against the live board); the fail-loud spine
(`GraphQLClient.query` raising on `errors`) is what surfaces such a mistake at runtime.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from repo_management.config import ProjectField, ProjectFieldOption, ProjectsConfig
from repo_management.managers.projects import ProjectNotFoundError
from repo_management.roadmap import (
    Board,
    BoardItem,
    StatusFieldInfo,
    build_status_update,
    days_since_last_update,
    desired_status,
    fetch_board,
    plan_reconcile,
    post_status_update,
    render_insights_svg,
)

TODAY = dt.date(2026, 7, 8)


def _item(
    number: int | None = 1,
    *,
    repo: str = "repo-management",
    state: str = "OPEN",
    status: str | None = None,
    phase: str | None = None,
    labels: tuple[str, ...] = (),
    closed_at: str | None = None,
    target: str | None = None,
    start: str | None = None,
    item_id: str = "I1",
) -> BoardItem:
    return BoardItem(
        id=item_id,
        repo=repo,
        number=number,
        title=f"item {number}",
        state=state,
        closed_at=closed_at,
        labels=list(labels),
        phase=phase,
        status=status,
        start=start,
        target=target,
    )


def _board(
    *items: BoardItem, last_update: str | None = None, phases: tuple[str, ...] = ()
) -> Board:
    return Board(
        id="PROJ",
        title="Fleet Roadmap",
        url="https://github.com/users/nivintw/projects/2",
        last_update=last_update,
        phase_order=list(phases),
        status_field=StatusFieldInfo(
            id="F_status",
            options={
                "Todo": "o_todo",
                "Ready": "o_ready",
                "In Progress": "o_prog",
                "Done": "o_done",
            },
        ),
        items=list(items),
    )


class FakeGQL:
    """Records mutations; replays queued board-fetch responses for `fetch_board`."""

    def __init__(self, *pages: dict[str, Any]) -> None:
        """Seed the ordered board-fetch page responses (empty for mutation-only use)."""
        self._pages = list(pages)
        self.mutations: list[Any] = []

    def query(self, document: str, /, **_variables: object) -> dict[str, Any]:
        """Record a mutation input, or pop the next queued board-fetch page."""
        if "mutation" in document:
            self.mutations.append(_variables["input"])
            return {}
        return self._pages.pop(0)


# --- status update ----------------------------------------------------------------------


def test_status_complete_when_nothing_open() -> None:
    """No open items => COMPLETE."""
    board = _board(_item(1, state="CLOSED", closed_at="2026-07-07"))
    health, _ = build_status_update(board, TODAY)
    assert health == "COMPLETE"


def test_status_off_track_on_overdue_safety_item() -> None:
    """An open P1 Safety item past its target => OFF_TRACK, outranking other signals."""
    board = _board(_item(1, phase="P1 Safety", target="2026-07-01", status="In Progress"))
    health, _ = build_status_update(board, TODAY)
    assert health == "OFF_TRACK"


def test_status_at_risk_when_blocked_heavy() -> None:
    """Three or more blocked items => AT_RISK."""
    board = _board(*(_item(n, status="Blocked", item_id=f"I{n}") for n in range(3)))
    health, _ = build_status_update(board, TODAY)
    assert health == "AT_RISK"


def test_status_at_risk_when_stalled() -> None:
    """Ready work but nothing closed in the window => AT_RISK (stalled)."""
    board = _board(_item(1, status="Ready"), last_update="2026-07-06")
    health, _ = build_status_update(board, TODAY)
    assert health == "AT_RISK"


def test_status_on_track_otherwise() -> None:
    """In-progress work with recent closes => ON_TRACK."""
    board = _board(
        _item(1, status="In Progress"),
        _item(2, state="CLOSED", closed_at="2026-07-07", item_id="I2"),
        last_update="2026-07-06",
    )
    health, body = build_status_update(board, TODAY)
    assert health == "ON_TRACK"
    assert "1 closed, 1 open" in body


def test_status_body_lists_shipped_blocked_and_up_next() -> None:
    """The body names shipped items, blocked, and the earliest-phase Ready work as up-next."""
    board = _board(
        _item(1, state="CLOSED", closed_at="2026-07-07", item_id="I1"),
        _item(2, status="Blocked", item_id="I2"),
        _item(3, status="Ready", phase="P2 MkDocs chain", item_id="I3"),
        _item(4, status="Ready", phase="P1 Safety", item_id="I4"),
        last_update="2026-07-06",
        phases=("P1 Safety", "P2 MkDocs chain"),
    )
    _, body = build_status_update(board, TODAY)
    assert "Shipped this week" in body
    assert "repo-management#2" in body  # blocked item listed
    # Up-next is only the earliest open phase's Ready work (P1), so #4 is in and P2's #3 is out.
    up_next = body.split("**Up next**", 1)[1]
    assert "#4" in up_next
    assert "#3" not in up_next


def test_status_nothing_merged_line() -> None:
    """With no closes in the window the shipped section says so."""
    board = _board(_item(1, status="In Progress"), last_update="2026-07-07")
    _, body = build_status_update(board, TODAY)
    assert "Nothing merged this week." in body


def test_status_at_risk_on_overdue_nonsafety_phase() -> None:
    """An overdue non-P1 phase alone => AT_RISK (isolating the overdue disjunct)."""
    board = _board(
        _item(1, phase="P2 MkDocs chain", target="2026-07-01", status="In Progress"),
        _item(
            2, state="CLOSED", closed_at="2026-07-07", item_id="I2"
        ),  # recent close => not stalled
        last_update="2026-07-06",
    )
    health, body = build_status_update(board, TODAY)
    assert health == "AT_RISK"
    assert "**Overdue phases:** P2 MkDocs chain" in body


def test_status_tolerates_malformed_dates() -> None:
    """A non-ISO date doesn't crash the status computation; the item just isn't counted overdue."""
    board = _board(_item(1, status="In Progress", target="not-a-date"))
    health, _ = build_status_update(board, TODAY)  # no ValueError
    assert health == "ON_TRACK"


def test_status_body_neutralizes_mentions() -> None:
    """An @mention in an item title is defused so the posted update can't ping people."""
    item = _item(1, state="CLOSED", closed_at="2026-07-07")
    item.title = "@ghost fix the thing"
    _, body = build_status_update(_board(item, last_update="2026-07-06"), TODAY)
    assert "@ghost" not in body
    assert "@\u200bghost" in body


def test_status_body_escapes_html_in_title_and_phase() -> None:
    """`< > &` in a title/phase are escaped so a posted update can't inject markup."""
    item = _item(1, state="CLOSED", closed_at="2026-07-07", phase="P1 <b>")
    item.title = "fix a<b & c"
    _, body = build_status_update(_board(item, last_update="2026-07-06"), TODAY)
    assert "fix a&lt;b &amp; c" in body
    assert "P1 &lt;b&gt;" in body
    assert "<b>" not in body


def test_status_body_dates_to_week_monday() -> None:
    """The header is dated to the week's Monday, not the (possibly mid-week) run date."""
    _, body = build_status_update(_board(_item(1, state="CLOSED", closed_at="2026-07-07")), TODAY)
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    assert f"**Week of {monday:%b %d}**" in body


# --- reconcile --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "labels", "expected"),
    [
        ("CLOSED", (), "Done"),
        ("MERGED", (), "Done"),
        ("OPEN", ("status:blocked",), "Blocked"),
        ("OPEN", ("status:in-review",), "In Review"),
        ("OPEN", ("status:in-progress",), "In Progress"),
        ("OPEN", ("status:ready",), "Ready"),
        ("OPEN", ("status:triage",), "Todo"),
        ("OPEN", (), None),
        ("OPEN", ("area:docs",), None),
    ],
)
def test_desired_status(state: str, labels: tuple[str, ...], expected: str | None) -> None:
    """State and status:* labels map to a definitive Status, or None when ambiguous."""
    assert desired_status(_item(state=state, labels=labels)) == expected


def test_desired_status_multiple_labels_is_ambiguous() -> None:
    """Two distinct status:* labels => ambiguous => leave the item unchanged (None)."""
    assert desired_status(_item(state="OPEN", labels=("status:ready", "status:blocked"))) is None


def test_reconcile_sets_status_when_it_differs() -> None:
    """A drifted item whose desired option exists gets a Status update."""
    gql = FakeGQL()
    board = _board(_item(1, state="OPEN", status="Todo", labels=("status:ready",)))
    changes = plan_reconcile(gql, board, TODAY, archive_after_days=None)
    assert len(changes) == 1
    assert changes[0].target == "status:repo-management#1"
    assert changes[0].before == "Todo"
    assert changes[0].after == "Ready"
    changes[0].apply()
    assert gql.mutations[0]["value"] == {"singleSelectOptionId": "o_ready"}


def test_reconcile_skips_when_desired_option_absent() -> None:
    """A desired option the board doesn't have is skipped, not invented."""
    gql = FakeGQL()
    board = _board(_item(1, state="OPEN", status="Todo", labels=("status:in-review",)))
    # "In Review" isn't in the fixture board's Status options.
    assert plan_reconcile(gql, board, TODAY, archive_after_days=None) == []


def test_reconcile_leaves_unlabeled_open_items_alone() -> None:
    """An open item with no status:* label is never touched."""
    gql = FakeGQL()
    board = _board(_item(1, state="OPEN", status="In Progress", labels=()))
    assert plan_reconcile(gql, board, TODAY, archive_after_days=None) == []


def test_reconcile_archives_old_closed_items() -> None:
    """A long-closed item is archived; a recently closed one is left visible."""
    gql = FakeGQL()
    board = _board(
        _item(1, state="CLOSED", status="Done", closed_at="2026-06-01", item_id="old"),
        _item(2, state="CLOSED", status="Done", closed_at="2026-07-07", item_id="new"),
    )
    changes = plan_reconcile(gql, board, TODAY, archive_after_days=14)
    assert [c.target for c in changes] == ["archive:repo-management#1"]
    changes[0].apply()
    assert gql.mutations[0] == {"projectId": "PROJ", "itemId": "old"}


def test_reconcile_no_status_field_is_noop() -> None:
    """A board without a Status field yields no reconcile changes."""
    gql = FakeGQL()
    board = _board(_item(1))
    board.status_field = None
    assert plan_reconcile(gql, board, TODAY) == []


def test_reconcile_skips_numberless_items() -> None:
    """A draft item (no issue number) is ignored by the reconcile."""
    gql = FakeGQL()
    board = _board(_item(None, state="OPEN", status="Todo", labels=("status:ready",)))
    assert plan_reconcile(gql, board, TODAY, archive_after_days=None) == []


# --- insights ---------------------------------------------------------------------------


def test_insights_svg_has_charts_and_escapes() -> None:
    """The SVG renders one heading per chart and escapes item-derived text."""
    board = _board(
        _item(1, repo="a<b", status="Todo", phase="P1 Safety"),
        _item(2, repo="a<b", status="Todo", phase="P1 Safety", item_id="I2"),
    )
    svg = render_insights_svg(board)
    assert svg.startswith("<svg")
    assert svg.count('class="h"') == 3  # by repository, phase, status
    assert "a&lt;b" in svg  # escaped, not raw '<'
    assert "<b" not in svg.replace("a&lt;b", "")  # no unescaped injection


# --- fetch + helpers --------------------------------------------------------------------


def _page(nodes: list[dict[str, Any]], *, cursor: str | None = None) -> dict[str, Any]:
    return {
        "user": {
            "projectV2": {
                "id": "PROJ",
                "title": "Fleet Roadmap",
                "url": "https://example/2",
                "statusUpdates": {"nodes": [{"createdAt": "2026-07-06T00:00:00Z"}]},
                "fields": {
                    "nodes": [
                        {},
                        {
                            "id": "F_status",
                            "name": "Status",
                            "options": [{"id": "o1", "name": "Todo"}],
                        },
                        {"id": "F_phase", "name": "Phase", "options": [{"id": "p1", "name": "P1"}]},
                    ]
                },
                "items": {
                    "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
                    "nodes": nodes,
                },
            }
        }
    }


def _node(number: int, *, item_id: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "fieldValues": {
            "nodes": [
                {"name": "Todo", "field": {"name": "Status"}},
                {"name": "P1", "field": {"name": "Phase"}},
                {"date": "2026-07-01", "field": {"name": "Target"}},
                {},  # a fieldValue union member with no field
            ]
        },
        "content": {
            "number": number,
            "title": f"t{number}",
            "state": "OPEN",
            "closedAt": None,
            "repository": {"name": "repo-management"},
            "labels": {"nodes": [{"name": "status:ready"}]},
        },
    }


def _config() -> ProjectsConfig:
    return ProjectsConfig(
        owner="nivintw",
        number=2,
        fields=[ProjectField(name="Status", options=[ProjectFieldOption(name="Todo")])],
    )


def test_fetch_board_parses_and_paginates() -> None:
    """fetch_board walks pages, parses items/fields, and skips content-less nodes."""
    gql = FakeGQL(
        _page(
            [_node(1, item_id="I1"), {"id": "x", "fieldValues": {"nodes": []}, "content": None}],
            cursor="c",
        ),
        _page([_node(2, item_id="I2")]),
    )
    board = fetch_board(gql, _config())

    assert [item.number for item in board.items] == [1, 2]  # content-less node skipped
    assert board.phase_order == ["P1"]
    assert board.status_field is not None
    assert board.status_field.options == {"Todo": "o1"}
    assert board.items[0].status == "Todo"
    assert board.items[0].target == "2026-07-01"
    assert board.items[0].labels == ["status:ready"]


def test_fetch_board_missing_project_raises() -> None:
    """A board the token can't read raises ProjectNotFoundError."""
    gql = FakeGQL({"user": {"projectV2": None}})
    with pytest.raises(ProjectNotFoundError):
        fetch_board(gql, _config())


def test_fetch_board_excludes_archived_items() -> None:
    """Archived items (still returned by the items connection) are filtered out of the snapshot."""
    archived = _node(9, item_id="arch")
    archived["isArchived"] = True
    gql = FakeGQL(_page([_node(1, item_id="I1"), archived]))
    board = fetch_board(gql, _config())
    assert [item.number for item in board.items] == [1]  # #9 archived => excluded


def test_fetch_board_handles_no_status_updates() -> None:
    """A board that has never had a status update parses to last_update=None."""
    page = _page([_node(1, item_id="I1")])
    page["user"]["projectV2"]["statusUpdates"]["nodes"] = []
    gql = FakeGQL(page)
    assert fetch_board(gql, _config()).last_update is None


def test_days_since_last_update() -> None:
    """The helper returns whole days since the last update, or None when there's none."""
    assert days_since_last_update(_board(last_update="2026-07-06T00:00:00Z"), TODAY) == 2
    assert days_since_last_update(_board(), TODAY) is None


def test_post_status_update_dates_from_item_span() -> None:
    """The posted update's start/target span the board items' earliest/latest dates."""
    gql = FakeGQL()
    board = _board(
        _item(1, start="2026-07-13", target="2026-08-01"),
        _item(2, start="2026-07-20", target="2026-09-21", item_id="I2"),
    )
    post_status_update(gql, board, "ON_TRACK", "body")
    sent = gql.mutations[0]
    assert sent["status"] == "ON_TRACK"
    assert sent["startDate"] == "2026-07-13"
    assert sent["targetDate"] == "2026-09-21"


def test_post_status_update_omits_dates_when_absent() -> None:
    """With no item dates, the update carries no start/target rather than an empty/bogus span."""
    gql = FakeGQL()
    post_status_update(gql, _board(_item(1)), "COMPLETE", "body")
    sent = gql.mutations[0]
    assert "startDate" not in sent
    assert "targetDate" not in sent
