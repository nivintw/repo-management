<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Contributing to Repo Management

Thanks for contributing!

## Workflow

1. Branch off `main` and land changes via a PR (enable branch protection to enforce it).
2. Run `uv sync` to set up the dev environment, then install the hooks: `uvx prek install`.
3. Make your change. The pre-commit hooks run the full quality gate — the same checks run in CI.
4. Commit with [Conventional Commits](https://www.conventionalcommits.org), enforced by
   commitizen at commit-msg time. release-please cuts releases from these commits (a
   Release PR → `vX.Y.Z` tag + GitHub Release on merge), so keep the type prefix accurate.
5. Open a PR and make sure CI is green before requesting review.

## Running the quality gate

```bash
uvx prek run --all-files
```
