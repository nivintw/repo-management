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

  This is best-effort and never fails the run: a secret sourced from an inline `value:`, a
  `value_from_env` with no matching source secret, or a local run (no `GITHUB_REPOSITORY`)
  simply keeps the plain skip-if-exists default. Environment-scoped secrets
  ([environments](environments.md)) also keep the plain default — the source-timestamp
  comparison applies to repo-level secrets only.

!!! warning
    Literal `value:` is supported for convenience, but a secret's value in plain YAML is a
    secret in your git history. Prefer `value_from_env` and keep the actual value out of the
    repo entirely.

## variables

Variable values are readable on GitHub and shown in plain text in plans. Unlike secrets, an
existing variable is only pushed when its resolved value actually differs from what's on
the repo.
