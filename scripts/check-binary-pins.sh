#!/usr/bin/env bash
# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

# check-binary-pins.sh — fail when a release-binary pin moves without its version.
#
# CI downloads each pinned release binary and checks it against the adjacent *_SHA256 (or, for
# an asset-less tool like bats, installs the *_COMMIT its tag points at). Both pins only ever
# change together with their *_VERSION: Renovate bumps the version and
# scripts/refresh-binary-checksums.sh re-pins in the same commit. A pin that changes while its
# version does not is either a release asset swapped on an already-published tag, or a hand edit
# that would hide one. Either way the change must not merge, so this runs inside the required CI
# check, comparing the workflow files against the base commit.
#
# Usage: scripts/check-binary-pins.sh <base-commit>
# Needs: bash, git (the base commit must be in the local history), grep, sed, sort.

set -euo pipefail

base="${1:?usage: check-binary-pins.sh <base-commit>}"
git rev-parse --verify --quiet "${base}^{commit}" >/dev/null || {
  echo "ERROR: base commit ${base} is not in the local history (check out with fetch-depth: 0)" >&2
  exit 1
}

value() { # <VAR> <file contents on stdin> -> the quoted value of `VAR: "..."`, or empty
  sed -nE "s/^[[:space:]]+$1:[[:space:]]*\"?([^\"[:space:]]+)\"?.*/\\1/p" | head -n 1
}

failed=0
while IFS= read -r file; do
  [ -f "$file" ] || continue
  base_text="$(git show "${base}:${file}" 2>/dev/null || true)"
  [ -n "$base_text" ] || continue # a new file has no earlier pin to compare against
  while IFS= read -r pin; do
    tool="${pin%_SHA256}"
    tool="${tool%_COMMIT}"
    old_pin="$(value "$pin" <<<"$base_text")"
    new_pin="$(value "$pin" <"$file")"
    old_version="$(value "${tool}_VERSION" <<<"$base_text")"
    new_version="$(value "${tool}_VERSION" <"$file")"
    if [ -n "$old_pin" ] && [ -n "$new_pin" ] && [ "$old_pin" != "$new_pin" ] && [ "$old_version" = "$new_version" ]; then
      echo "::error file=${file}::${pin} changed but ${tool}_VERSION (${new_version}) did not: a re-pinned asset under an unchanged version"
      failed=1
    fi
  done < <(grep -oE "^[[:space:]]+[A-Z0-9_]+_(SHA256|COMMIT):" "$file" | tr -d " :" | sort -u)
done < <(git diff --name-only "$base" HEAD -- ".github/workflows/*.yml" ".github/workflows/*.yaml")

if [ "$failed" -eq 0 ]; then
  echo "Binary pins: every changed pin moved with its version."
fi
exit "$failed"
