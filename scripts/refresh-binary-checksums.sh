#!/usr/bin/env bash
# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

# Refresh the pinned SHA256 of each CI-installed release binary to match its current
# *_VERSION. Renovate bumps the version env vars (see .github/renovate.json), but the
# github-releases datasource has no asset-digest concept, so the adjacent *_SHA256 must be
# recomputed from the published asset. Renovate runs this as a postUpgradeTask on its bump
# PRs (so the refreshed hash lands in Renovate's own commit); run it by hand after a manual
# version bump.
#
# Usage: scripts/refresh-binary-checksums.sh [file ...]
#   With no args it updates every .github/workflows/*.yml and .github/workflows/*.yaml that
#   carry these pins.
#
# Tamper gate (automation): the caller sets BASE_REF=<git ref> to enforce supply-chain
# safety. A SHA is then only re-pinned when the *_VERSION actually changed vs BASE_REF; a SHA
# that differs from upstream while the version is UNCHANGED is treated as a tampered/swapped
# release asset and fails the run — never silently re-pinned. The postUpgradeTask command
# computes BASE_REF inline via `git merge-base` against the default branch (and fails loudly
# if that computation itself fails), so the gate is always active on the automated path.
# Without BASE_REF (a human running it locally after a deliberate bump) it just recomputes
# every pin.
#
# Requirements: bash 4.4+, curl, sha256sum (or shasum), sed, grep, awk, mktemp, head; git when BASE_REF set.
set -euo pipefail
# Make `set -e` apply INSIDE $(...) too — without this a curl/awk failure inside fetch_sha is
# swallowed and a partial download could be hashed and pinned.
shopt -s inherit_errexit

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

# The release binaries CI installs by hand. Each pins a SHA256 of its published asset:
# trivy/osv-scanner/hawkeye/kubeconform publish a checksum file we read; taplo publishes no
# checksum, so we download the asset and hash it ourselves.
TOOLS=(TRIVY OSV HAWKEYE TAPLO KUBECONFORM)

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
  TAPLO)
    # taplo ships no checksum file, so hash the asset (no `v` prefix on taplo tags).
    # --remove-on-error so a half-written file is never left behind to be hashed.
    curl -fsSL "${retry[@]}" --remove-on-error \
      "https://github.com/tamasfe/taplo/releases/download/${version}/taplo-linux-x86_64.gz" \
      -o "$WORKDIR/taplo.gz"
    sha256_of "$WORKDIR/taplo.gz"
    ;;
  *)
    echo "unknown tool: $tool" >&2
    return 1
    ;;
  esac
}

# Memoize on tool|version so a version that appears in several workflow files is fetched —
# or, for taplo, downloaded — at most once. Writes into the caller-named variable ($3) so
# the cache lives in THIS shell (a `$(...)` return would run in a subshell and lose it).
declare -A SHA_CACHE=()
cached_sha() { # <TOOL> <version> <outvar>
  local key="$1|$2"
  if [ -z "${SHA_CACHE[$key]+set}" ]; then
    SHA_CACHE[$key]="$(fetch_sha "$1" "$2")"
  fi
  printf -v "$3" '%s' "${SHA_CACHE[$key]}"
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
  # catches a missing file up front; the `cat` exit-status check below catches any other
  # read failure (e.g. a file that exists but isn't readable) with this function's own
  # labeled message, rather than relying on `set -e` to abort via `cat`'s bare OS-level
  # error text with no "pinned_value:" context to attribute it during CI triage.
  # _extract_pinned_value() separately guards grep's own exit code against the piped
  # content (conflating "no match" — the intended empty-return case — with a real read
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
  # break this exact legitimate case on a non-English runner. Verified against git 2.55; if a
  # future git release ever rewords this message, the case falls through to the loud ERROR
  # below rather than silently mistreating a real error as "no pin found" — a wrong CI
  # failure on an ordinary new-file case, never a silently-broken tamper gate.
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

changed=0
processed=0
for file in "${targets[@]}"; do
  for tool in "${TOOLS[@]}"; do
    # NOTE: reads the first *_VERSION but rewrites every *_SHA256 (sed /g). That is correct
    # because a tool pinned more than once in a file shares one version; do not pin the same
    # tool to two different versions in one file.
    version="$(pinned_value "${tool}_VERSION" "$file")"
    [ -n "$version" ] || continue
    old_sha="$(pinned_value "${tool}_SHA256" "$file")"
    [ -n "$old_sha" ] || continue
    old_sha="${old_sha,,}"
    processed=$((processed + 1))

    new_sha=""
    cached_sha "$tool" "$version" new_sha
    new_sha="${new_sha,,}" # normalize: compare/store lowercase even if an upstream emits uppercase hex
    if [[ ! "$new_sha" =~ ^[0-9a-f]{64}$ ]]; then
      echo "ERROR: ${tool} ${version}: upstream did not yield a SHA256 (got '${new_sha}')" >&2
      exit 1
    fi

    if [ -n "$BASE_REF" ] && [ "$new_sha" != "$old_sha" ]; then
      base_version="$(pinned_value_at_base "${tool}_VERSION" "$file" "$BASE_REF")"
      if [ -n "$base_version" ] && [ "$base_version" = "$version" ]; then
        echo "TAMPER ALERT: ${tool} ${version} in ${file}: pinned SHA ${old_sha} != upstream" >&2
        echo "  ${new_sha}, but the version is unchanged vs ${BASE_REF}. Refusing to auto-update —" >&2
        echo "  investigate the upstream release (a fixed tag's asset should never change)." >&2
        exit 1
      fi
    fi

    if [ "$new_sha" != "$old_sha" ]; then
      tmp="$(mktemp)"
      sed -E "s|(${tool}_SHA256: \")[0-9a-fA-F]*(\")|\1${new_sha}\2|g" "$file" >"$tmp"
      if ! grep -q "${tool}_SHA256: \"${new_sha}\"" "$tmp"; then
        rm -f "$tmp"
        echo "ERROR: failed to rewrite ${tool}_SHA256 in ${file}" >&2
        exit 1
      fi
      mv "$tmp" "$file"
      echo "updated ${file}: ${tool} ${version} -> ${new_sha}"
      changed=1
    else
      echo "ok ${file}: ${tool} ${version} (${new_sha})"
    fi
  done
done

if [ "$processed" -eq 0 ]; then
  echo "ERROR: no *_SHA256 pins found in: ${targets[*]} (regex drift, or wrong working dir?)" >&2
  exit 1
fi
if [ "$changed" -eq 0 ]; then
  echo "All checksums already current."
fi
