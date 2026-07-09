# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Projects v2 board schema manager."""

from __future__ import annotations

from typing import Any, Literal

import pytest

from repo_management.changes import Action
from repo_management.config import ProjectField, ProjectFieldOption, ProjectsConfig
from repo_management.managers.projects import ProjectNotFoundError, ProjectsManager

PROJECT_ID = "PVT_board"


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
    """A stand-in GraphQL client: answers the board fetch and records mutations."""

    def __init__(self, fields: list[dict[str, Any]] | None, *, root: str = "user") -> None:
        """Seed the board's field nodes (``None`` => board not found) and query root."""
        self._fields = fields
        self._root = root
        self.mutations: list[Any] = []

    def query(self, document: str, /, **variables: object) -> dict[str, Any]:
        """Record a mutation's input, or answer the board-fetch query with the seeded fields."""
        if "createProjectV2Field" in document or "updateProjectV2Field" in document:
            self.mutations.append(variables["input"])
            return {}
        project = (
            None if self._fields is None else {"id": PROJECT_ID, "fields": {"nodes": self._fields}}
        )
        return {self._root: {"projectV2": project}}


def _config(
    *fields: ProjectField, owner_type: Literal["user", "organization"] = "user"
) -> ProjectsConfig:
    return ProjectsConfig(owner="nivintw", owner_type=owner_type, number=2, fields=list(fields))


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
