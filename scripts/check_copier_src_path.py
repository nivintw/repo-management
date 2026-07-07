# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT


"""Assert that .copier-answers.yml records a REMOTE `_src_path`, not a local path.

Copier writes the template location it was run from into `_src_path`. If a project is
scaffolded (or updated) from a LOCAL filesystem checkout of the template, that local path
gets recorded — and then `copier update` silently breaks for every OTHER clone and in CI,
because the path doesn't exist there. This gate fails the commit when `_src_path` is a
local path so the mistake is caught at the source instead of surfacing as a broken update
somewhere else.

Stdlib only, on purpose: a generated project's pre-commit hook env is not guaranteed to
have PyYAML, so we don't import it. We only need a single scalar line, which we pull out
with a regex — this is NOT a general YAML parser.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# `_src_path:` at the start of a line, capturing the rest of the line (trailing space trimmed).
_SRC_PATH_RE = re.compile(r"^_src_path:\s*(.*?)\s*$", re.MULTILINE)

# Remote forms that `copier update` can reach from any clone / from CI:
#   scheme URLs .......... ssh:// https:// http:// git://
#   copier shorthand ..... gh:owner/repo, gl:owner/repo
#   scp-like git URL ..... git@host:owner/repo
_REMOTE_SCHEME_RE = re.compile(r"^(?:ssh|https?|git)://", re.IGNORECASE)
_SHORTHAND_RE = re.compile(r"^(?:gh|gl):.+", re.IGNORECASE)
_SCP_RE = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9._-]+:.+")

_DEFAULT_ANSWERS = ".copier-answers.yml"
_REMEDY = (
    "Set `_src_path` to the remote template URL (e.g. gh:nivintw/copier-everything) "
    "and re-run `copier update`."
)


def _strip_quotes(value: str) -> str:
    """Drop a single matching pair of surrounding single/double quotes, if present."""
    value = value.strip()
    # `value != value[:1]` means "at least two chars" without a magic length literal — so a lone
    # quote isn't mistaken for an empty quoted string.
    if value[:1] in ("'", '"') and value[-1:] == value[:1] and value != value[:1]:
        return value[1:-1]
    return value


def is_remote(value: str) -> bool:
    """True when `value` is a remote template location `copier update` can resolve anywhere."""
    return bool(
        _REMOTE_SCHEME_RE.match(value) or _SHORTHAND_RE.match(value) or _SCP_RE.match(value)
    )


def check_file(path: str) -> bool:
    """True if `path`'s `_src_path` is remote; else print the reason and return False."""
    file = Path(path)
    if not file.exists():
        print(
            f"ERROR: {path}: file not found. A generated project must have a "
            f"{_DEFAULT_ANSWERS} recording its template source.",
            file=sys.stderr,
        )
        return False

    text = file.read_text(encoding="utf-8")
    if not text.strip():
        print(
            f"ERROR: {path}: file is empty. Expected a Copier answers file with `_src_path`.",
            file=sys.stderr,
        )
        return False

    match = _SRC_PATH_RE.search(text)
    if match is None:
        print(
            f"ERROR: {path}: no `_src_path:` key found. Every Copier-generated project "
            f"records `_src_path`; this file looks wrong.",
            file=sys.stderr,
        )
        return False

    value = _strip_quotes(match.group(1))
    if not value:
        print(
            f"ERROR: {path}: `_src_path:` is empty. {_REMEDY}",
            file=sys.stderr,
        )
        return False

    if is_remote(value):
        return True

    print(
        f"ERROR: {path}: `_src_path` is a LOCAL path: {value!r}\n"
        f"  A local `_src_path` silently breaks `copier update` for every other clone and in CI\n"
        f"  (the path does not exist there). {_REMEDY}",
        file=sys.stderr,
    )
    return False


def main(argv: list[str]) -> int:
    """Check each path given (pre-commit passes them), or the default answers file."""
    paths = argv[1:] or [_DEFAULT_ANSWERS]
    # A list (not a generator) so every path is checked and its error printed — no short-circuit.
    results = [check_file(path) for path in paths]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
