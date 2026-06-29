#!/usr/bin/env bash
# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

# Refresh the pinned SHA256 of each CI-installed release binary to match its current
# *_VERSION. Renovate bumps the version env vars (see .github/renovate.json), but the
# github-releases datasource has no asset-digest concept, so the adjacent *_SHA256 must be
# recomputed from the published asset. The refresh-binary-checksums workflow runs this on
# Renovate PRs; run it by hand after a manual version bump.
#
# Usage: scripts/refresh-binary-checksums.sh [file ...]
#   With no args it updates every .github/workflows/*.yml that carries these pins.
#
# Tamper gate (CI): set BASE_REF=<git ref> to enforce supply-chain safety. A SHA is then
# only re-pinned when the *_VERSION actually changed vs BASE_REF. A SHA that differs from
# upstream while the version is UNCHANGED is treated as a tampered/swapped release asset and
# fails the run — never silently re-pinned. Without BASE_REF (a human running it locally
# after a deliberate bump) it just recomputes every pin.
#
# Requirements: bash 4.4+, curl, sha256sum (or shasum), sed, grep, awk; git when BASE_REF set.
set -euo pipefail
# Make `set -e` apply INSIDE $(...) too — without this a curl/awk failure inside fetch_sha is
# swallowed and a partial download could be hashed and pinned.
shopt -s inherit_errexit

BASE_REF="${BASE_REF:-}"

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

# Extract the quoted value of an env-var assignment (first occurrence). Empty (exit 0) when absent.
pinned_value() { # <VAR> <file> -> value or empty
  grep -oE "$1: \"[^\"]+\"" "$2" 2>/dev/null | head -n1 | sed -E 's/.*"([^"]+)".*/\1/' || true
}
pinned_value_at_base() { # <VAR> <file> <baseref> -> value at base or empty
  git show "$3:$2" 2>/dev/null | grep -oE "$1: \"[^\"]+\"" | head -n1 | sed -E 's/.*"([^"]+)".*/\1/' || true
}

if [ "$#" -gt 0 ]; then
  targets=("$@")
else
  targets=()
  for f in .github/workflows/*.yml; do
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
