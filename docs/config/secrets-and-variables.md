<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Secrets and variables

Actions secrets and repository variables share the same config shape — a `name` plus
exactly one of `value` or `value_from_env` — and the same diff/reconciliation code
(`repo_management.managers._secret_variable`), reused again by [environments](environments.md)
for environment-scoped secrets/variables. They differ only in how GitHub exposes their
values, which changes how each is diffed.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | **required** | Match key |
| `value` | string | unset | Literal value; exactly one of `value`/`value_from_env` |
| `value_from_env` | string | unset | Env var to read the value from |

Providing both `value` and `value_from_env`, or neither, is a validation error.

```yaml
secrets:
  - name: DEPLOY_TOKEN
    value_from_env: DEPLOY_TOKEN

variables:
  - name: ENVIRONMENT
    value: production
```

Both sections are authoritative: a `secrets`/`variables` entry absent from the config is
deleted from the repo.

## secrets

Secret values are write-only: GitHub never returns them, so apply never diffs the current
value against the declared one. By default a secret already present on the repo is left
alone; pass `--force-secrets` (on both `plan` and `apply`) to re-push every declared secret,
e.g. to rotate one. Values are never printed in plans.

!!! warning
    Literal `value:` is supported for convenience, but a secret's value in plain YAML is a
    secret in your git history. Prefer `value_from_env` and keep the actual value out of the
    repo entirely.

## variables

Variable values are readable on GitHub and shown in plain text in plans. Unlike secrets, an
existing variable is only pushed when its resolved value actually differs from what's on
the repo.
