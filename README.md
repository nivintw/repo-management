<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Repo Management

Declarative, YAML-driven management of GitHub repository configuration. Describe how a
repo *should* be configured in a YAML file; `repo-management` reads the live state, shows
you the diff, and reconciles it through the GitHub API (via [PyGithub]).

It is **declarative and idempotent**: re-running when nothing has changed does nothing.
A field you don't mention is left unmanaged — the tool only touches what you declare.

## Install

```bash
uv sync                      # create the venv + install everything
```

Authentication uses a GitHub token, read from `$GITHUB_TOKEN` (or `--token`). The token
needs the scopes for whatever you manage (repo administration, Actions secrets, etc.).

## Usage

```bash
export GITHUB_TOKEN=ghp_...

repo-management validate -c examples/repos.yaml   # check the YAML (no network)
repo-management plan     -c examples/repos.yaml   # show the diff (read-only)
repo-management apply    -c examples/repos.yaml   # reconcile (prompts before writing)
```

Useful flags:

- `--repo owner/name` — limit the run to a single repo from the config.
- `--yes` / `-y` — skip the confirmation prompt on `apply`.
- `--token` — pass a token explicitly instead of using `$GITHUB_TOKEN`.

`plan` prints one line per change: `+` create, `~` update, `-` delete. Secret values are
always redacted.

## What it manages

| Section | Manages |
| --- | --- |
| `settings` | description, homepage, topics, visibility, features (issues/wiki/projects/discussions), merge options (squash/merge/rebase, auto-merge, delete-branch-on-merge), default branch |
| `branch_protection` | per-branch: required reviews, status checks, enforce-admins, linear history, conversation resolution, force-push/deletion rules |
| `labels` | create/update labels; delete extras only when `prune: true` |
| `collaborators` | add collaborators and update their permission (additive — never removes) |
| `webhooks` | create/update webhooks, matched by URL (additive — never deletes) |
| `secrets` | Actions secrets (write-only; libsodium-encrypted by PyGithub) |

See [`examples/repos.yaml`](examples/repos.yaml) for a fully-annotated config.

### Design notes / limitations

- **Additive by default.** `collaborators` and `webhooks` are never removed by omission;
  removing access is destructive and left as a deliberate manual action. Only `labels`
  prunes, and only when you opt in with `prune: true`.
- **Secrets and webhook secrets are write-only.** The API never returns a secret value, so
  a change to *only* a secret can't be diffed: an Actions secret is re-sent on every apply,
  and a webhook with a configured secret is always re-sent (shown as `(set)` in the plan).
  Values are sourced from the environment (`value_from_env` / `secret_from_env`) and never
  printed. A literal `value:` is supported for secrets but should never be committed.
- **Branch protection covers the modeled fields only.** GitHub's protection endpoint is a
  full replace, so on apply the tool reads the live protection and re-sends it with your
  configured fields overlaid — this preserves every field it models. Features it does *not*
  model (push restrictions, bypass-allowance lists, required signatures) would be reset, so
  manage protection for a branch entirely through this tool, or not at all.

## Development

```bash
uv run pytest                # tests + coverage (gate: 90%; currently 100%)
uvx prek run --all-files     # the full quality gate (ruff, format, REUSE, typos, …)
```

The project carries the shared quality spine: prek hooks (git hygiene, gitleaks, typos,
rumdl, SPDX/REUSE headers, ruff) that run identically locally and in CI. Conventional
Commits (gitmoji) are enforced at commit-msg time. A few hooks shell out to **system
tools** prek can't bootstrap — install them locally too (most are in Homebrew):
`hawkeye`, `taplo`, `osv-scanner`.

## License

[MIT](LICENSE) — and [REUSE](https://reuse.software)-compliant.

[PyGithub]: https://github.com/PyGithub/PyGithub
