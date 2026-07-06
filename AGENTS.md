<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Agent instructions — Repo Management

YAML-config-driven GitHub repository manager

Baseline guidance for AI coding agents working in this repo. Keep it current as the project
grows.

## The quality gate

One command runs every lint, format, license, and security check (the same set CI runs):

```console
uvx prek@0.4.8 run --all-files
```

Run it before you consider a change done; fix what it flags rather than suppressing it. Hooks
also run automatically on commit once `uvx prek@0.4.8 install` has been run. The version is
pinned to match CI exactly (`ci.yml`'s "Run prek hooks (same as local)" step) — Renovate bumps
it here and in CI together.

## Commits

Use **Conventional Commits** (`feat:`, `fix:`, `chore:`, `docs:`…). They drive automated
versioning and the changelog via release-please — the commit type is what decides the next
version, so it's not just style. `main` is protected (no direct commits); branch and open a PR.

## Where things live

- `.config/` — tool configuration (lint/format/release config lives here, not scattered at root).
- `.github/workflows/` — CI and the release pipeline.
- `src/repo_management/` — the Python source.
- `tests/` — pytest suite.

## Python

Managed with [uv](https://docs.astral.sh/uv/). `uv sync` sets up the environment; `uv run …`
runs in it. Lint/format is **ruff**, type-checking is **ty**. Run tests with `uv run pytest`.
The interpreter is pinned in `.python-version`.

## Licensing

Files carry SPDX headers (REUSE-compliant); the gate enforces it. When you add a file, give
it a header in the project's style or the `reuse` check will fail.
