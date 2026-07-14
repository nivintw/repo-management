# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""The :class:`Change` type — one planned modification to a repository.

Managers return ``Change`` objects from their ``plan`` method. Each change carries a
human-readable before/after for display plus an ``apply`` callable that performs the
write. ``plan`` and ``apply`` therefore share a single code path: the CLI prints changes
during ``plan`` and invokes ``change.apply()`` during ``apply``.

A change may also carry a ``preflight`` — a side-effect-free callable that resolves the
write's payload (e.g. a secret value from the environment) so ``apply`` can validate every
write *before* performing the first one, keeping a failed run from leaving a half-applied
fleet. And a *diagnostic* :class:`Change` (built via :meth:`Change.diagnostic`) represents a
desired value that couldn't be resolved at all — it is reported and blocks the run, never
applied.
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
        preflight: Optional side-effect-free callable that resolves this write's payload (e.g.
            reads a secret's value from the environment). ``apply`` runs every change's
            ``preflight`` before the first write so a missing value aborts with nothing applied.
            ``None`` when there's no payload to resolve (deletes, already-resolved variables).
        error: When set, this is a *diagnostic*, not a change to apply — a desired value that
            could not be resolved (see :attr:`unresolved` and :meth:`diagnostic`). Build one only
            via :meth:`diagnostic`, which keeps the payload inert and the ``apply`` fail-loud.
    """

    domain: str
    action: Action
    target: str
    before: object | None
    after: object | None
    apply: Callable[[], None]
    secret: bool = False
    preflight: Callable[[], None] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        """Reject an illegal half-diagnostic: an ``error`` set alongside a write payload."""
        # A diagnostic carries no write: no before/after payload and nothing to preflight. Guard
        # the invariant at construction so an illegal half-diagnostic can't be built by hand.
        if self.error is not None and (
            self.before is not None or self.after is not None or self.preflight is not None
        ):
            msg = "a diagnostic Change carries no payload — build it via Change.diagnostic()"
            raise ValueError(msg)

    @classmethod
    def diagnostic(cls, domain: str, target: str, error: str) -> Change:
        """Build a diagnostic: a desired value that couldn't be resolved, not a change to apply.

        Renders as a ``!`` line (:meth:`describe`), partitions into ``RepoPlan.problems``, and
        blocks the run — the CLI reports it and exits non-zero for ``plan``, and refuses to write
        anything for ``apply``. Its ``apply`` re-raises: it is never invoked on the happy path,
        but fails loud rather than silently writing if it ever is.
        """

        def _apply() -> None:
            msg = f"refusing to apply an unresolved value: {error}"
            raise RuntimeError(msg)

        return cls(domain, Action.UPDATE, target, None, None, _apply, error=error)

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
