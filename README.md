<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Repo Management

YAML-config-driven GitHub repository manager

## Getting started

```bash
uv sync                 # create the venv + install dev tooling
uvx prek install        # wire up the pre-commit hooks
uv run pytest           # run the Python tests
```

## Quality gate

This project carries the shared quality spine: prek hooks (git hygiene, gitleaks,
typos, rumdl, SPDX/REUSE headers, ruff, ty) that run
identically locally and in CI. Conventional Commits (gitmoji) are enforced at
commit-msg time (`.cz.toml`); releases on `main` are cut automatically by commitizen.

```bash
uvx prek run --all-files   # run every hook on demand
```

A few hooks shell out to **system tools** prek can't bootstrap — CI installs them for
you, but install them locally too (most are in Homebrew): `hawkeye`, `taplo`, `osv-scanner`.

## License

[MIT](LICENSE) — and [REUSE](https://reuse.software)-compliant.
