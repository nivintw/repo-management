# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""The :class:`Change` type — one planned modification to a repository.

Managers return ``Change`` objects from their ``plan`` method. Each change carries a
human-readable before/after for display plus an ``apply`` callable that performs the
write. ``plan`` and ``apply`` therefore share a single code path: the CLI prints changes
during ``plan`` and invokes ``change.apply()`` during ``apply``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REDACTED = "***"


class Action(StrEnum):
    """The kind of modification a change represents."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class Change:
    """A single planned modification produced by a manager.

    Attributes:
        domain: The manager that produced the change, e.g. ``"settings"``.
        action: Whether this creates, updates, or deletes.
        target: A short identifier for the thing changing, e.g. ``"label:bug"``.
        before: The current value (``None`` for a creation).
        after: The desired value (``None`` for a deletion).
        apply: Callable performing the write against the GitHub API.
        secret: When true, ``before``/``after`` are redacted in :meth:`describe`.
        error: When set, this is not a change to apply but a *diagnostic* — a desired value
            that could not be resolved (see :attr:`unresolved`). ``describe`` renders it as a
            ``!`` line, the CLI reports it and exits non-zero, and it is never applied. Only the
            variables path emits these; a variable's value is shown in the plan and compared to
            decide update-vs-no-op, so an unresolvable one can't be diffed and is surfaced rather
            than crashing the whole plan. ``action`` is nominal on a diagnostic and unused.
    """

    domain: str
    action: Action
    target: str
    before: object | None
    after: object | None
    apply: Callable[[], None]
    secret: bool = False
    error: str | None = None

    @property
    def unresolved(self) -> bool:
        """Whether this is a diagnostic for an unresolvable value, not a change to apply."""
        return self.error is not None

    def describe(self) -> str:
        """Return a one-line, human-readable summary of the change (or diagnostic)."""
        if self.unresolved:
            return f"! [{self.domain}] {self.target}: {self.error}"
        before = self._render(self.before)
        after = self._render(self.after)
        if self.action is Action.CREATE:
            return f"+ [{self.domain}] {self.target} = {after}"
        if self.action is Action.DELETE:
            return f"- [{self.domain}] {self.target} (was {before})"
        return f"~ [{self.domain}] {self.target}: {before} -> {after}"

    def _render(self, value: object | None) -> str:
        if self.secret:
            return REDACTED
        return repr(value)
