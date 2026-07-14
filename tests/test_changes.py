# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Change type and its rendering."""

from __future__ import annotations

import pytest

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


def test_describe_diagnostic() -> None:
    """A change carrying an error renders as a `!` diagnostic line, not create/update/delete."""
    change = Change(
        "variables", Action.UPDATE, "variable:REGION", None, None, _noop, error="env FOO not set"
    )
    assert change.unresolved is True
    assert change.describe() == "! [variables] variable:REGION: env FOO not set"


def test_ordinary_change_is_not_unresolved() -> None:
    """A change with no error is not a diagnostic."""
    change = Change("settings", Action.UPDATE, "description", "old", "new", _noop)
    assert change.unresolved is False


def test_diagnostic_constructor() -> None:
    """Change.diagnostic builds an inert, unresolved diagnostic that renders as a `!` line."""
    diagnostic = Change.diagnostic("variables", "variable:REGION", "env FOO not set")
    assert diagnostic.unresolved
    assert (diagnostic.before, diagnostic.after, diagnostic.preflight) == (None, None, None)
    assert diagnostic.describe() == "! [variables] variable:REGION: env FOO not set"
    # Never applied on the happy path; fails loud if it ever is.
    with pytest.raises(RuntimeError):
        diagnostic.apply()


def test_diagnostic_invariant_rejects_a_payload() -> None:
    """A hand-built Change with an error must not also carry a before/after/preflight payload."""
    with pytest.raises(ValueError, match="diagnostic"):
        Change("variables", Action.UPDATE, "variable:X", "old", None, _noop, error="unset")


def test_apply_is_invoked() -> None:
    """The apply callable runs the stored side effect."""
    calls: list[int] = []
    change = Change("x", Action.CREATE, "t", None, None, lambda: calls.append(1))
    change.apply()
    assert calls == [1]
