# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Projects v2 board schema manager."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast

import pytest

from repo_management.changes import Action
from repo_management.config import ProjectField, ProjectFieldOption, ProjectsConfig
from repo_management.managers.projects import (
    AmbiguousProjectError,
    ProjectNotFoundError,
    ProjectsManager,
)

PROJECT_ID = "PVT_board"
OWNER_ID = "U_owner"
# The number GitHub assigns to a board the fake creates — deliberately not the 2 the
# number-addressed fixtures use, so a create path can't accidentally pass by reusing it.
NEW_NUMBER = 7


def _option(name: str, color: str = "GRAY", description: str = "") -> dict[str, Any]:
    return {"id": f"opt_{name}", "name": name, "color": color, "description": description}


def _single_select(name: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "__typename": "ProjectV2SingleSelectField",
        "id": f"fld_{name}",
        "name": name,
        "dataType": "SINGLE_SELECT",
        "options": options,
    }


def _plain_field(name: str, data_type: str) -> dict[str, Any]:
    # A non-single-select field's node has no `options` selection (mirrors the real query).
    return {
        "__typename": "ProjectV2FieldCommon",
        "id": f"fld_{name}",
        "name": name,
        "dataType": data_type,
    }


class FakeGQL:
    """A stand-in GraphQL client: answers the board fetch/list and records mutations.

    Models enough of a world for the create path to be exercised end to end — creating a
    board makes it findable by title *and* readable, so the closure's re-resolve and re-fetch
    hit real state rather than a canned answer.
    """

    def __init__(
        self,
        fields: list[dict[str, Any]] | None,
        *,
        root: str = "user",
        boards: Sequence[dict[str, Any]] | None = (),
        owner_id: str | None = OWNER_ID,
        page_size: int = 100,
    ) -> None:
        """Seed the world the fake answers from.

        ``fields`` are the board's field nodes — ``None`` => board not found, and for a
        title-create they are what the *new* board comes with (GitHub seeds its own Status);
        ``boards`` the owner's boards for a title lookup (``None`` => can't list them);
        ``owner_id`` the owner's node id (``None`` => owner not resolvable);
        ``page_size`` forces the title lookup to paginate.
        """
        self._fields = fields
        self._root = root
        self._boards = None if boards is None else list(boards)
        self._owner_id = owner_id
        self._page_size = page_size
        self.mutations: list[Any] = []
        self.created: list[Any] = []
        # Every document in call order, so a test can assert what was *not* re-fetched.
        self.documents: list[str] = []

    def query(self, document: str, /, **variables: object) -> dict[str, Any]:
        """Answer whichever document this is, recording it and any mutation's input."""
        # Order matters: "createProjectV2Field" contains "createProjectV2" as a substring, so
        # the field mutations have to be matched before the board create.
        payload = cast("dict[str, Any]", variables.get("input"))
        if "createProjectV2Field" in document:
            self.documents.append("create-field")
            return self._create_field(payload)
        if "updateProjectV2Field" in document:
            self.documents.append("update-field")
            return self._update_field(payload)
        if "createProjectV2(" in document:
            self.documents.append("create-board")
            return self._create_board(payload)
        if "projectsV2(first:" in document:
            self.documents.append("list-boards")
            return self._list(variables.get("cursor"))
        if "projectV2(number:" in document:
            self.documents.append("fetch-board")
            project = (
                None
                if self._fields is None
                else {"id": PROJECT_ID, "fields": {"nodes": self._fields}}
            )
            return {self._root: {"projectV2": project}}
        self.documents.append("owner-id")
        return {self._root: None if self._owner_id is None else {"id": self._owner_id}}

    def _create_board(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created.append(payload)
        # The board is findable by title from here on; its fields are whatever the fake
        # was seeded with, standing in for what GitHub seeds a new board with.
        if self._boards is not None:
            self._boards.append({"number": NEW_NUMBER, "title": payload["title"]})
        board = {"id": PROJECT_ID, "number": NEW_NUMBER, "title": payload["title"]}
        return {"createProjectV2": {"projectV2": board}}

    # The field mutations write back into the seeded world, not just the mutation log, so a
    # re-plan after an apply sees what the apply did — that's what makes idempotency testable.
    def _create_field(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.mutations.append(payload)
        options = payload.get("singleSelectOptions")
        node = (
            _plain_field(payload["name"], payload["dataType"])
            if options is None
            else _single_select(
                payload["name"], [_option(o["name"], o["color"], o["description"]) for o in options]
            )
        )
        if self._fields is not None:
            self._fields.append(node)
        return {}

    def _update_field(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.mutations.append(payload)
        for node in self._fields or []:
            if node["id"] == payload["fieldId"]:
                node["options"] = [
                    _option(o["name"], o["color"], o["description"])
                    for o in payload["singleSelectOptions"]
                ]
        return {}

    def _list(self, cursor: object) -> dict[str, Any]:
        if self._boards is None:
            return {self._root: {"projectsV2": None}}
        start = 0 if cursor is None else int(str(cursor))
        chunk = self._boards[start : start + self._page_size]
        end = start + len(chunk)
        page = {"hasNextPage": end < len(self._boards), "endCursor": str(end)}
        return {self._root: {"projectsV2": {"nodes": chunk, "pageInfo": page}}}


def _config(
    *fields: ProjectField, owner_type: Literal["user", "organization"] = "user"
) -> ProjectsConfig:
    return ProjectsConfig(owner="nivintw", owner_type=owner_type, number=2, fields=list(fields))


def _titled(
    *fields: ProjectField,
    title: str = "Fleet Roadmap",
    owner_type: Literal["user", "organization"] = "user",
) -> ProjectsConfig:
    return ProjectsConfig(owner="nivintw", owner_type=owner_type, title=title, fields=list(fields))


def _status(*names: str) -> ProjectField:
    return ProjectField(
        name="Status",
        data_type="single_select",
        options=[ProjectFieldOption(name=name) for name in names],
    )


def test_in_sync_yields_no_changes() -> None:
    """A single-select whose live options match the config exactly produces no change."""
    gql = FakeGQL([_single_select("Status", [_option("Todo"), _option("Done")])])
    assert ProjectsManager(gql).plan(_config(_status("Todo", "Done"))) == []


def test_missing_single_select_is_created() -> None:
    """A declared field absent from the board is created with its options."""
    gql = FakeGQL([])
    changes = ProjectsManager(gql).plan(_config(_status("Todo", "Done")))

    assert len(changes) == 1
    assert changes[0].action is Action.CREATE
    assert changes[0].target == "field:Status"
    assert changes[0].after == {"data_type": "single_select", "options": ["Todo", "Done"]}

    changes[0].apply()
    assert gql.mutations == [
        {
            "projectId": PROJECT_ID,
            "dataType": "SINGLE_SELECT",
            "name": "Status",
            "singleSelectOptions": [
                {"name": "Todo", "color": "GRAY", "description": ""},
                {"name": "Done", "color": "GRAY", "description": ""},
            ],
        }
    ]


def test_missing_date_field_is_created_without_options() -> None:
    """A date field is created with dataType DATE and carries no options."""
    gql = FakeGQL([])
    field = ProjectField(name="Target", data_type="date")
    changes = ProjectsManager(gql).plan(_config(field))

    assert len(changes) == 1
    assert changes[0].action is Action.CREATE
    assert changes[0].after == {"data_type": "date"}
    changes[0].apply()
    assert gql.mutations == [{"projectId": PROJECT_ID, "dataType": "DATE", "name": "Target"}]


def test_added_option_preserves_existing_ids() -> None:
    """Adding an option keeps kept options' ids (by name) and gives the new one none."""
    gql = FakeGQL([_single_select("Status", [_option("Todo"), _option("Done")])])
    changes = ProjectsManager(gql).plan(_config(_status("Todo", "Ready", "Done")))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE
    assert changes[0].before == ["Todo", "Done"]
    assert changes[0].after == ["Todo", "Ready", "Done"]

    changes[0].apply()
    payload = gql.mutations[0]
    assert payload["fieldId"] == "fld_Status"
    assert payload["singleSelectOptions"] == [
        {"name": "Todo", "color": "GRAY", "description": "", "id": "opt_Todo"},
        {"name": "Ready", "color": "GRAY", "description": ""},  # new -> no id
        {"name": "Done", "color": "GRAY", "description": "", "id": "opt_Done"},
    ]


def test_removed_option_is_surfaced_loudly() -> None:
    """Dropping an option is a destructive UPDATE whose target names what's removed."""
    gql = FakeGQL(
        [_single_select("Status", [_option("Todo"), _option("Done"), _option("Wontfix")])]
    )
    changes = ProjectsManager(gql).plan(_config(_status("Todo", "Done")))

    assert len(changes) == 1
    assert changes[0].target == "field:Status:options (removes Wontfix)"
    assert changes[0].after == ["Todo", "Done"]


def test_reordered_options_trigger_update() -> None:
    """Same option names in a different order is a change (order is display order)."""
    gql = FakeGQL([_single_select("Status", [_option("Todo"), _option("Done")])])
    changes = ProjectsManager(gql).plan(_config(_status("Done", "Todo")))
    assert len(changes) == 1
    assert changes[0].after == ["Done", "Todo"]


def test_option_null_description_matches_default() -> None:
    """A live option with description=null is in sync with a config option that omits it.

    GitHub returns null for a description-less option, so the `or ""` normalization is
    load-bearing: without it every plan/apply would emit a phantom UPDATE and never read
    in-sync.
    """
    live = {"id": "opt_Todo", "name": "Todo", "color": "GRAY", "description": None}
    gql = FakeGQL([_single_select("Status", [live])])
    assert ProjectsManager(gql).plan(_config(_status("Todo"))) == []


def test_recolored_option_triggers_update_and_keeps_id() -> None:
    """A color change on an existing option updates it in place (id preserved)."""
    gql = FakeGQL([_single_select("Status", [_option("Todo", color="GRAY")])])
    field = ProjectField(
        name="Status",
        data_type="single_select",
        options=[ProjectFieldOption(name="Todo", color="RED")],
    )
    changes = ProjectsManager(gql).plan(_config(field))
    assert len(changes) == 1
    changes[0].apply()
    assert gql.mutations[0]["singleSelectOptions"] == [
        {"name": "Todo", "color": "RED", "description": "", "id": "opt_Todo"}
    ]


def test_field_type_mismatch_warns_and_skips() -> None:
    """A field present with a different data type is left unmanaged with a warning."""
    gql = FakeGQL([_plain_field("Status", "TEXT")])
    with pytest.warns(UserWarning, match="field-type mutation"):
        changes = ProjectsManager(gql).plan(_config(_status("Todo", "Done")))
    assert changes == []
    assert gql.mutations == []


def test_missing_project_raises() -> None:
    """A board the token can't read raises ProjectNotFoundError."""
    gql = FakeGQL(None)
    with pytest.raises(ProjectNotFoundError, match="not found"):
        ProjectsManager(gql).plan(_config(_status("Todo")))


def test_organization_owner_uses_organization_root() -> None:
    """An organization-owned board is fetched under the `organization` query root."""
    gql = FakeGQL([_single_select("Status", [_option("Todo")])], root="organization")
    assert ProjectsManager(gql).plan(_config(_status("Todo"), owner_type="organization")) == []


def test_empty_field_nodes_are_skipped() -> None:
    """Non-field union members (serialized as {}) in the fields list are ignored."""
    gql = FakeGQL([{}, _single_select("Status", [_option("Todo")])])
    assert ProjectsManager(gql).plan(_config(_status("Todo"))) == []


# --- board addressing: adopt by number, converge by title --------------------------------


def test_title_addressed_existing_board_reconciles() -> None:
    """A board found by title reconciles its fields — it is adopted, not re-created."""
    gql = FakeGQL(
        [_single_select("Status", [_option("Todo")])],
        boards=[{"number": 2, "title": "Fleet Roadmap"}],
    )
    changes = ProjectsManager(gql).plan(_titled(_status("Todo", "Done")))

    assert [change.action for change in changes] == [Action.UPDATE]
    assert gql.created == []


def test_title_addressed_missing_board_is_created() -> None:
    """A declared board absent from the owner's boards plans as a single create."""
    gql = FakeGQL([], boards=[{"number": 2, "title": "Something Else"}])
    changes = ProjectsManager(gql).plan(_titled(_status("Todo", "Done")))

    assert len(changes) == 1
    assert changes[0].action is Action.CREATE
    assert changes[0].target == "board:Fleet Roadmap"
    assert changes[0].after == {
        "owner": "nivintw",
        "title": "Fleet Roadmap",
        "fields": {"Status": {"data_type": "single_select", "options": ["Todo", "Done"]}},
    }

    changes[0].apply()
    assert gql.created == [{"ownerId": OWNER_ID, "title": "Fleet Roadmap"}]


def test_create_then_populates_declared_fields() -> None:
    """Creating a board also creates the fields it declares, against the new board's id."""
    gql = FakeGQL([], boards=[])
    changes = ProjectsManager(gql).plan(
        _titled(_status("Todo"), ProjectField(name="Target", data_type="date"))
    )

    changes[0].apply()
    assert len(gql.created) == 1
    assert [mutation["name"] for mutation in gql.mutations] == ["Status", "Target"]
    assert all(mutation["projectId"] == PROJECT_ID for mutation in gql.mutations)


def test_created_board_reconciles_the_builtin_status() -> None:
    """A new board's auto-created Status is *updated*, not created a second time.

    GitHub seeds every new board with its own Status single-select, so a declared Status has
    to reconcile that field — blind-creating it would collide.
    """
    gql = FakeGQL([_single_select("Status", [_option("Todo"), _option("In Progress")])], boards=[])
    changes = ProjectsManager(gql).plan(_titled(_status("Todo", "Done")))
    changes[0].apply()

    assert len(gql.mutations) == 1
    # An update carries the live field's id; a create would carry a projectId + dataType.
    assert gql.mutations[0]["fieldId"] == "fld_Status"
    assert [option["name"] for option in gql.mutations[0]["singleSelectOptions"]] == [
        "Todo",
        "Done",
    ]


def test_create_is_idempotent() -> None:
    """Re-planning after a create finds the board by title instead of creating a duplicate."""
    gql = FakeGQL([], boards=[])
    manager = ProjectsManager(gql)
    manager.plan(_titled(_status("Todo")))[0].apply()

    assert manager.plan(_titled(_status("Todo"))) == []
    assert len(gql.created) == 1


def test_ambiguous_title_raises() -> None:
    """A title matching several boards raises rather than silently managing one of them."""
    gql = FakeGQL(
        [],
        boards=[
            {"number": 2, "title": "Fleet Roadmap"},
            {"number": 9, "title": "Fleet Roadmap"},
        ],
    )
    with pytest.raises(AmbiguousProjectError, match=r"2 Projects v2 boards titled .*#2, #9"):
        ProjectsManager(gql).plan(_titled(_status("Todo")))


def test_title_lookup_paginates() -> None:
    """A title on a later page of the owner's boards is still found."""
    gql = FakeGQL(
        [_single_select("Status", [_option("Todo")])],
        boards=[
            {"number": 1, "title": "One"},
            {"number": 2, "title": "Two"},
            {"number": 3, "title": "Fleet Roadmap"},
        ],
        page_size=1,
    )
    assert ProjectsManager(gql).plan(_titled(_status("Todo"))) == []


def test_unlistable_owner_raises() -> None:
    """A token that can't list the owner's boards raises rather than creating a duplicate."""
    gql = FakeGQL([], boards=None)
    with pytest.raises(ProjectNotFoundError, match="can't list Projects v2 boards"):
        ProjectsManager(gql).plan(_titled(_status("Todo")))


def test_number_addressed_missing_board_is_never_created() -> None:
    """A number names a board that must already exist — absence is an error, not a create."""
    gql = FakeGQL(None)
    with pytest.raises(ProjectNotFoundError, match="not found"):
        ProjectsManager(gql).plan(_config(_status("Todo")))
    assert gql.created == []


def test_create_on_unresolvable_owner_raises() -> None:
    """An owner that stops resolving between plan and apply raises instead of creating."""
    gql = FakeGQL([], boards=[], owner_id=None)
    changes = ProjectsManager(gql).plan(_titled(_status("Todo")))

    with pytest.raises(ProjectNotFoundError, match="can't resolve user 'nivintw'"):
        changes[0].apply()
    assert gql.created == []


def test_create_addresses_the_new_board_by_the_returned_number() -> None:
    """The create's own response supplies the number — no second title lookup after it."""
    gql = FakeGQL([], boards=[])
    ProjectsManager(gql).plan(_titled(_status("Todo")))[0].apply()

    # One listing at plan time; the apply must not re-list to rediscover what it was told.
    assert gql.documents.count("list-boards") == 1
    assert gql.documents == [
        "list-boards",
        "owner-id",
        "create-board",
        "fetch-board",
        "create-field",
    ]
