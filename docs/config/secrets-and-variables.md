<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Secrets and variables

Actions secrets and repository variables share the same config shape — a `name` plus
exactly one of `value` or `value_from_env` — and the same diff/reconciliation logic, reused
again by [environments](environments.md) for environment-scoped secrets/variables. They
differ only in how GitHub exposes their
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
alone — re-pushing it every apply would be pure churn. Values are never printed in plans.

Two things override that skip-if-exists default for an existing secret:

- **`--force-secrets`** (on both `plan` and `apply`) re-pushes *every* declared secret
  unconditionally — the blunt rotation lever.
- **Source timestamps (automatic under Actions).** GitHub does expose each secret's
  `updated_at`, even though it hides the value. When `apply` runs inside GitHub Actions, the
  tool reads the `updated_at` of its *own* repo's Actions secrets — the ones backing the
  `value_from_env` sources — and re-pushes a target secret only when its source changed more
  recently than the target's own `updated_at`. So rotating a secret at the source propagates
  to the fleet on the next apply, while an unchanged secret (or one a target already holds a
  newer copy of) is skipped — no `--force-secrets`, no fleet-wide churn.

  For a secret to be timestamp-propagated, two conditions must hold — and both **degrade
  quietly to skip-if-exists** (never a wrong overwrite):

  - The env var must be named **identically** to the source secret it reads —
    `FOO: ${{ secrets.FOO }}`, not `FOO: ${{ secrets.BAR }}`. The comparison keys off the
    source secret's *name*, so a renamed mapping just won't match. (This repo's
    `test_workflow_secrets` enforces the identity for its own workflows.)
  - The source secret must be a **repo-level** Actions secret — org-level secrets inherited
    by the repo aren't returned by the read.

    An inline `value:` secret and a local run (no `GITHUB_REPOSITORY`) likewise keep the plain
    default, and environment-scoped secrets ([environments](environments.md)) always do — the
    source-timestamp comparison is scoped to repo-level secrets.

!!! warning "Uncertainty leaves the old value in place"
    Every path the comparison can't resolve — a source it can't read (a permission error logs
    a warning but does **not** fail the run), a name mismatch, an undatable side — biases
    toward *not* re-pushing. That protects a value someone rotated by hand, but it means a
    source rotation can silently fail to propagate. When you need a rotation to reach the fleet
    for certain, use **`--force-secrets`** rather than relying on the automatic comparison.

!!! warning
    Literal `value:` is supported for convenience, but a secret's value in plain YAML is a
    secret in your git history. Prefer `value_from_env` and keep the actual value out of the
    repo entirely.

## variables

Variable values are readable on GitHub and shown in plain text in plans. Unlike secrets, an
existing variable is only pushed when its resolved value actually differs from what's on
the repo.
