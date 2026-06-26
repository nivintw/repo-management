# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Change type and its rendering."""

from __future__ import annotations

from repo_management.changes import REDACTED, Action, Change


def _noop() -> None:
    pass


def test_describe_create() -> None:
    """A create renders with a leading plus and the new value."""
    change = Change("labels", Action.CREATE, "label:bug", None, {"color": "red"}, _noop)
    text = change.describe()
    assert text.startswith("+ [labels] label:bug = ")
    assert "color" in text


def test_describe_update() -> None:
    """An update renders before and after values."""
    change = Change("settings", Action.UPDATE, "description", "old", "new", _noop)
    assert change.describe() == "~ [settings] description: 'old' -> 'new'"


def test_describe_delete() -> None:
    """A delete renders with a leading minus and the old value."""
    change = Change("labels", Action.DELETE, "label:old", {"color": "x"}, None, _noop)
    assert change.describe().startswith("- [labels] label:old (was ")


def test_secret_values_redacted() -> None:
    """A secret change never renders its before/after values."""
    change = Change("secrets", Action.UPDATE, "secret:TOK", "real", "value", _noop, secret=True)
    text = change.describe()
    assert REDACTED in text
    assert "real" not in text
    assert "value" not in text


def test_apply_is_invoked() -> None:
    """The apply callable runs the stored side effect."""
    calls: list[int] = []
    change = Change("x", Action.CREATE, "t", None, None, lambda: calls.append(1))
    change.apply()
    assert calls == [1]
