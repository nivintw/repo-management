#!/usr/bin/env bash
# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

# Refresh the pinned supply-chain value of each CI-installed release binary to match its
# current *_VERSION. Renovate bumps the version env vars (see .github/renovate.json), but the
# github-releases datasource has no asset-digest concept, so the adjacent pin must be
# recomputed. Renovate runs this as a postUpgradeTask on its bump PRs (so the refreshed value
# lands in Renovate's own commit); run it by hand after a manual version bump.
#
# Two pin classes, one refresh model:
#   *_SHA256 — asset-bearing tools (trivy/osv/hawkeye/taplo/kubeconform). Pins the SHA256 of
#     the published release asset (most publish a checksum file we read; taplo ships none, so
#     we download the asset and hash it).
#   *_COMMIT — asset-less tools (bats), installed from a git tag with NO downloadable release
#     asset to hash. There's nothing to SHA256, so we pin the git commit id that v${VERSION}'s
#     tag points at instead (resolved with `git ls-remote`, no clone). The BASE_REF tamper gate
#     covers it identically: a *_COMMIT that changes while *_VERSION is unchanged is a tampered
#     tag (a moved/re-pointed tag), same supply-chain signal as a swapped asset.
#
# Usage: scripts/refresh-binary-checksums.sh [file ...]
#   With no args it updates every .github/workflows/*.yml and .github/workflows/*.yaml that
#   carry these pins.
#
# Tamper gate (automation): the caller sets BASE_REF=<git ref> to enforce supply-chain
# safety. A pin is then only re-written when the *_VERSION actually changed vs BASE_REF; a pin
# that differs from upstream while the version is UNCHANGED is treated as a tampered/swapped
# release (asset or tag) and fails the run — never silently re-pinned. The continuity check is
# keyed on TOOL IDENTITY, not file path: the tool's *_VERSION is looked up across every
# workflow file at BASE_REF, so a pin that legitimately MOVED between files (a workflow
# restructuring, or a `copier update` renaming a generated workflow) is still recognized as the
# same continuous pin and its gate still fires — closing the bypass where a pure file rename
# made a same-version/changed-hash swap look like a brand-new pin. The postUpgradeTask command
# computes BASE_REF inline via `git merge-base` against the default branch (and fails loudly if
# that computation itself fails), so the gate is always active on the automated path. Without
# BASE_REF (a human running it locally after a deliberate bump) it just recomputes every pin.
#
# Requirements: bash 3.2+ (stays parseable/runnable on macOS's system bash 3.2.57 — no
# associative arrays, no `${var,,}`, no `inherit_errexit`), curl, sha256sum (or shasum), sed,
# grep, awk, tr, mktemp, head; git when BASE_REF set or a *_COMMIT tool is refreshed. Dropping
# `inherit_errexit` (bash 4.4+) for 3.2 portability is compensated everywhere a `$(...)` could
# otherwise swallow an inner failure: `set -o pipefail` (inherited into command substitutions,
# unlike errexit) makes the single-pipe fetches fail loudly, and every multi-statement path
# checks its own exit status explicitly (see fetch_sha's taplo branch, cached_fetch, pinned_*).
set -euo pipefail

BASE_REF="${BASE_REF:-}"
if [ -n "$BASE_REF" ] && ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  # Distinguish "ref didn't resolve" (shallow clone, typo, stale ref) from the legitimate
  # "file is new at HEAD" case pinned_value_at_base() treats as empty — a fetch-depth: 1
  # runner would otherwise silently disable the tamper gate below instead of failing loudly.
  # ^{commit} requires a commit-ish (not just any resolvable object, e.g. a blob or tree SHA
  # passed by mistake), matching what pinned_value_at_base()'s `git show "$BASE_REF:$file"`
  # actually needs.
  echo "ERROR: BASE_REF '${BASE_REF}' does not resolve to a valid commit — refusing to run with a" >&2
  echo "  broken tamper gate (fix the ref, or fetch enough history for it to resolve)." >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# The asset-bearing release binaries CI installs by hand, each pinned by a SHA256 of its
# published asset. trivy/osv-scanner/hawkeye/kubeconform/gitleaks publish a checksum file we
# read; taplo publishes none, so we download the asset and hash it ourselves.
SHA256_TOOLS=(TRIVY OSV HAWKEYE TAPLO KUBECONFORM GITLEAKS)
# Asset-less tools installed from a git tag, pinned by the commit id the tag points at (there's
# no release asset to hash). See the *_COMMIT note in the header.
COMMIT_TOOLS=(BATS)

lower() { # <hex-ish string> -> lowercased (bash 3.2 has no ${var,,})
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

sha256_of() { # <file> -> bare hex digest
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

fetch_sha() { # <TOOL> <version> -> bare hex digest on stdout
  local tool="$1" version="$2"
  # Bounded retry/backoff so a transient GitHub release-CDN blip (5xx, connection reset)
  # doesn't abort the whole refresh — mirrors the pinned-binary installs in ci.yml.
  local -a retry=(--retry 5 --retry-all-errors --retry-delay 2 --retry-max-time 60)
  case "$tool" in
  TRIVY)
    curl -fsSL "${retry[@]}" "https://github.com/aquasecurity/trivy/releases/download/v${version}/trivy_${version}_checksums.txt" |
      awk -v a="trivy_${version}_Linux-64bit.tar.gz" '$2 == a {print $1}'
    ;;
  OSV)
    curl -fsSL "${retry[@]}" "https://github.com/google/osv-scanner/releases/download/v${version}/osv-scanner_SHA256SUMS" |
      awk '$2 == "osv-scanner_linux_amd64" {print $1}'
    ;;
  HAWKEYE)
    curl -fsSL "${retry[@]}" "https://github.com/korandoru/hawkeye/releases/download/v${version}/hawkeye-x86_64-unknown-linux-gnu.tar.xz.sha256" |
      awk '{print $1}'
    ;;
  KUBECONFORM)
    curl -fsSL "${retry[@]}" "https://github.com/yannh/kubeconform/releases/download/v${version}/CHECKSUMS" |
      awk '$2 == "kubeconform-linux-amd64.tar.gz" {print $1}'
    ;;
  GITLEAKS)
    curl -fsSL "${retry[@]}" "https://github.com/gitleaks/gitleaks/releases/download/v${version}/gitleaks_${version}_checksums.txt" |
      awk -v a="gitleaks_${version}_linux_x64.tar.gz" '$2 == a {print $1}'
    ;;
  TAPLO)
    # taplo ships no checksum file, so hash the asset (no `v` prefix on taplo tags).
    # --remove-on-error so a half-written file is never left behind to be hashed. With
    # inherit_errexit gone (bash 3.2), curl's failure in this multi-statement branch would
    # otherwise fall through to sha256_of, so check it explicitly and fail loudly here.
    if ! curl -fsSL "${retry[@]}" --remove-on-error \
      "https://github.com/tamasfe/taplo/releases/download/${version}/taplo-linux-x86_64.gz" \
      -o "$WORKDIR/taplo.gz"; then
      echo "ERROR: fetch_sha: taplo ${version} asset download failed" >&2
      return 1
    fi
    sha256_of "$WORKDIR/taplo.gz"
    ;;
  *)
    echo "unknown sha256 tool: $tool" >&2
    return 1
    ;;
  esac
}

fetch_commit() { # <TOOL> <version> -> bare hex commit id on stdout
  local tool="$1" version="$2" url
  case "$tool" in
  BATS) url="https://github.com/bats-core/bats-core" ;;
  *)
    echo "unknown commit tool: $tool" >&2
    return 1
    ;;
  esac
  # Resolve the release tag to the commit it points at, no local clone. `^{}` dereferences an
  # annotated tag to its underlying commit; a lightweight tag has no `^{}` row, so fall back to
  # the plain tag row (already the commit). pipefail (inherited into this `$(...)`) makes a
  # ls-remote failure abort loudly; a nonexistent tag yields no rows → empty → the caller's
  # hex-format check rejects it.
  git ls-remote "$url" "refs/tags/v${version}^{}" "refs/tags/v${version}" |
    awk -v tag="refs/tags/v${version}" -F'\t' '
      $2 == tag "^{}" { deref = $1 }
      $2 == tag       { plain = $1 }
      END { if (deref != "") print deref; else if (plain != "") print plain }'
}

# Memoize on class|tool|version so a version that appears in several workflow files is fetched —
# or, for taplo, downloaded — at most once. bash 3.2 has no associative arrays, so the cache is
# two parallel indexed arrays scanned linearly (the tool set is tiny). Writes into the
# caller-named variable ($4) so the cache lives in THIS shell (a `$(...)` return would run in a
# subshell and lose it).
PIN_CACHE_KEYS=()
PIN_CACHE_VALS=()
cached_fetch() { # <fetch_fn> <TOOL> <version> <outvar>
  local key="$1|$2|$3" i
  for i in "${!PIN_CACHE_KEYS[@]}"; do
    if [ "${PIN_CACHE_KEYS[$i]}" = "$key" ]; then
      printf -v "$4" '%s' "${PIN_CACHE_VALS[$i]}"
      return 0
    fi
  done
  local val
  # A `$(...)` assignment: under set -e a non-zero fetch (curl/ls-remote failure surfaced via
  # pipefail or an explicit return 1) aborts here loudly instead of caching a partial value.
  val="$("$1" "$2" "$3")"
  PIN_CACHE_KEYS+=("$key")
  PIN_CACHE_VALS+=("$val")
  printf -v "$4" '%s' "$val"
}

# Shared tail for pinned_value()/pinned_value_at_base(): extract the quoted value of an
# env-var assignment (first occurrence) from content on stdin. <caller>/<location> are
# only for the error message, so the two callers keep their own distinct wording.
# Anchored to (whitespace-then-)line-start so a search for TRIVY_VERSION can't match inside
# a hypothetical OLD_TRIVY_VERSION — a bare \b wouldn't help here since `_` is a word char.
_extract_pinned_value() { # <VAR> <caller> <location> -> value or empty (reads stdin)
  local matched grep_rc
  matched="$(grep -oE "^[[:space:]]*$1: \"[^\"]+\"")" && grep_rc=0 || grep_rc=$?
  if [ "$grep_rc" -gt 1 ]; then
    echo "ERROR: $2: grep failed reading $3 (exit $grep_rc)" >&2
    exit 1
  fi
  printf '%s\n' "$matched" | head -n1 | sed -E 's/.*"([^"]+)".*/\1/'
}

pinned_value() { # <VAR> <file> -> value or empty
  # Fail loudly on a bad path instead of masking it as "no pin found": the guard below
  # catches a missing file up front; the explicit exit-status check on `cat` catches any other
  # read failure (e.g. a file that exists but isn't readable) with a labeled `pinned_value:`
  # error, rather than bash's bare `set -e` aborting the assignment with only cat's raw OS
  # message ("cat: <file>: Permission denied") and no context — matching every other failure
  # mode in this file. _extract_pinned_value() separately guards grep's own exit code against
  # the piped content (conflating "no match" — the intended empty-return case — with a real read
  # error would be the same class of bug this whole file exists to avoid).
  [ -f "$2" ] || {
    echo "ERROR: pinned_value: no such file: $2" >&2
    exit 1
  }
  # Read into a variable rather than redirecting "$2" as stdin on the same line it's also
  # passed as an argument — shellcheck's SC2094 (read-and-write-same-file) fires on that
  # syntactic shape even though nothing here is written, only read.
  local content
  if ! content="$(cat "$2")"; then
    echo "ERROR: pinned_value: read failed: $2" >&2
    exit 1
  fi
  printf '%s' "$content" | _extract_pinned_value "$1" pinned_value "$2"
}
pinned_value_at_base() { # <VAR> <file> <baseref> -> value at base or empty
  # Enforce the baseref-resolves-to-a-commit invariant HERE, not only at the top-level BASE_REF
  # gate, so the function's own "fail loudly on anything but a legitimately-absent path"
  # guarantee holds regardless of caller. Otherwise an unresolvable ref ($3 a stale/GC'd SHA,
  # a typo, a shallow clone missing the commit) makes `git cat-file -e $3:$2` emit the SAME
  # "exists on disk, but not in <ref>" text as a genuinely-absent path — collapsing an
  # unresolvable ref into a silent empty return instead of the loud failure below.
  git rev-parse --verify --quiet "$3^{commit}" >/dev/null 2>&1 || {
    echo "ERROR: pinned_value_at_base: baseref '$3' does not resolve to a commit" >&2
    exit 1
  }
  # A path absent at BASE_REF (introduced since) is the one legitimate empty case here.
  # `git cat-file -e`'s exit code alone can't distinguish it from a genuine read error
  # (corrupted object, partial-clone missing blob): a missing path exits 128 with a "does
  # not exist"/"exists on disk, but not in" message (git picks the wording based on whether
  # the path is also absent from the *working tree* — every real caller here passes a file
  # that IS on disk, per the `[ -f "$f" ]` guard above, so the "exists on disk" wording is
  # actually the common case, not the exotic one), but a missing blob exits 1 with no
  # message at all — so match cat-file's own message instead of trusting the exit code, and
  # fail loudly on anything else, the same tamper gate pinned_value()'s guard above protects
  # for the plain-file case. LC_ALL=C pins the message to English regardless of the runner's
  # locale — git's fatal messages are translated, and matching translated text would silently
  # break this exact legitimate case on a non-English runner.
  local cat_err
  if ! cat_err="$(LC_ALL=C git cat-file -e "$3:$2" 2>&1 1>/dev/null)"; then
    case "$cat_err" in
    *"does not exist in"* | *"exists on disk, but not in"*) return 0 ;;
    esac
    echo "ERROR: pinned_value_at_base: git cat-file -e $3:$2 failed: ${cat_err:-(no output)}" >&2
    exit 1
  fi
  # Real exit-status check on git show — mirroring pinned_value()'s grep-exit-code guard
  # above — so a genuine failure here isn't swallowed as "no pin found" the way a trailing
  # `|| true` on the whole pipeline would.
  local blob
  if ! blob="$(git show "$3:$2")"; then
    echo "ERROR: pinned_value_at_base: git show $3:$2 failed" >&2
    exit 1
  fi
  printf '%s\n' "$blob" | _extract_pinned_value "$1" pinned_value_at_base "$3:$2"
}

tool_versions_at_base() { # <TOOL> <baseref> -> EVERY version the tool is pinned at at base (one/line)
  # The tamper gate's continuity check, keyed on TOOL IDENTITY rather than a fixed file path:
  # find where ${tool}_VERSION lives at BASE_REF across ALL workflow files, so a pin that moved
  # between files since BASE_REF is still matched to its history. Without this, `git mv old.yml
  # new.yml` (or a copier update renaming a generated workflow) makes the pin look brand-new and
  # silently bypasses the same-version/changed-hash tamper check (issue #211).
  # Emits EVERY base version for the tool (not just the first file's), so the caller can test
  # whether the CURRENT version is AMONG them — a tool pinned at DIFFERENT versions in two files
  # at base must not let the first-listed version stand in for the file actually being checked.
  local tool="$1" baseref="$2" files rc f val
  # `git grep -l <pattern> <ref> -- <pathspec>` lists "<ref>:<path>" for each matching file at
  # the ref. Exit 1 == no matches (a legitimately never-pinned tool → empty), exit >1 == a real
  # error (mirror _extract_pinned_value's grep-exit handling and fail loudly).
  files="$(git grep -lE "^[[:space:]]*${tool}_VERSION: \"" "$baseref" -- \
    '.github/workflows/*.yml' '.github/workflows/*.yaml')" && rc=0 || rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "ERROR: tool_versions_at_base: git grep failed (exit $rc) for ${tool} at ${baseref}" >&2
    exit 1
  fi
  [ -n "$files" ] || return 0
  # Heredoc (not a pipe) so the loop runs in THIS shell and an `exit` inside pinned_value_at_base
  # propagates instead of dying in a subshell.
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    f="${f#"${baseref}":}" # strip the "<ref>:" prefix git grep -l prepends
    val="$(pinned_value_at_base "${tool}_VERSION" "$f" "$baseref")"
    [ -n "$val" ] && printf '%s\n' "$val"
  done <<EOF
$files
EOF
}

changed=0
processed=0

# Refresh one tool's pin in one file. Shared by both pin classes — only the pin var suffix, the
# fetch function, and the accepted value format differ.
refresh_pin() { # <file> <TOOL> <suffix> <fetch_fn> <valid-regex> <label>
  local file="$1" tool="$2" suffix="$3" fetch_fn="$4" valid_re="$5" label="$6"
  local version old_pin new_pin base_versions tmp
  # NOTE: reads the first *_VERSION but rewrites every *_<suffix> (sed /g). That is correct
  # because a tool pinned more than once in a file shares one version; do not pin the same
  # tool to two different versions in one file.
  version="$(pinned_value "${tool}_VERSION" "$file")"
  [ -n "$version" ] || return 0
  old_pin="$(pinned_value "${tool}_${suffix}" "$file")"
  [ -n "$old_pin" ] || return 0
  old_pin="$(lower "$old_pin")"
  processed=$((processed + 1))

  new_pin=""
  cached_fetch "$fetch_fn" "$tool" "$version" new_pin
  new_pin="$(lower "$new_pin")" # normalize: compare/store lowercase even if upstream emits uppercase hex
  if [[ ! "$new_pin" =~ $valid_re ]]; then
    echo "ERROR: ${tool} ${version}: upstream did not yield a ${label} (got '${new_pin}')" >&2
    exit 1
  fi

  if [ -n "$BASE_REF" ] && [ "$new_pin" != "$old_pin" ]; then
    # Tamper iff this EXACT version was pinned somewhere at BASE_REF (same version + changed pin
    # = a swapped asset/tag). Captured to a variable first (not piped into grep) so a git-grep
    # error inside the function still aborts loudly under set -e; membership (`grep -qxF`), not
    # equality against one arbitrarily-chosen version, so a tool pinned at different versions in
    # two files at base can't let a same-version tamper in the OTHER file slip through.
    base_versions="$(tool_versions_at_base "$tool" "$BASE_REF")"
    if printf '%s\n' "$base_versions" | grep -qxF "$version"; then
      echo "TAMPER ALERT: ${tool} ${version} in ${file}: pinned ${label} ${old_pin} != upstream" >&2
      echo "  ${new_pin}, but the version is unchanged vs ${BASE_REF}. Refusing to auto-update —" >&2
      echo "  investigate the upstream release (a fixed tag's asset/commit should never change)." >&2
      exit 1
    fi
  fi

  if [ "$new_pin" != "$old_pin" ]; then
    tmp="$(mktemp)"
    sed -E "s|(${tool}_${suffix}: \")[0-9a-fA-F]*(\")|\1${new_pin}\2|g" "$file" >"$tmp"
    if ! grep -q "${tool}_${suffix}: \"${new_pin}\"" "$tmp"; then
      rm -f "$tmp"
      echo "ERROR: failed to rewrite ${tool}_${suffix} in ${file}" >&2
      exit 1
    fi
    mv "$tmp" "$file"
    echo "updated ${file}: ${tool} ${version} -> ${new_pin}"
    changed=1
  else
    echo "ok ${file}: ${tool} ${version} (${new_pin})"
  fi
}

if [ "$#" -gt 0 ]; then
  targets=("$@")
else
  targets=()
  # Both extensions: renovate's customManager matches `\.ya?ml$` and the refresh trigger uses
  # `**`, so a binary pinned in a *.yaml workflow must be refreshed too. A non-matching glob
  # stays literal (no nullglob), so the `[ -f ]` guard drops it.
  for f in .github/workflows/*.yml .github/workflows/*.yaml; do
    [ -f "$f" ] && targets+=("$f")
  done
fi

for file in "${targets[@]}"; do
  for tool in "${SHA256_TOOLS[@]}"; do
    refresh_pin "$file" "$tool" SHA256 fetch_sha '^[0-9a-f]{64}$' SHA256
  done
  for tool in "${COMMIT_TOOLS[@]}"; do
    # git commit ids are 40-hex (sha1) or 64-hex (sha256, once a repo migrates).
    refresh_pin "$file" "$tool" COMMIT fetch_commit '^([0-9a-f]{40}|[0-9a-f]{64})$' "commit id"
  done
done

if [ "$processed" -eq 0 ]; then
  echo "ERROR: no *_SHA256 / *_COMMIT pins found in: ${targets[*]} (regex drift, or wrong working dir?)" >&2
  exit 1
fi
if [ "$changed" -eq 0 ]; then
  echo "All checksums already current."
fi
