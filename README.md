<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Repo Management

Declarative, YAML-driven management of GitHub repository configuration. Describe how a
repo *should* be configured in a YAML file; `repo-management` reads the live state, shows
you the diff, and reconciles it through the GitHub API (via [PyGithub]).

It is **declarative and idempotent**: re-running when nothing has changed does nothing.
A section you don't mention is left unmanaged; a section you *do* declare is authoritative —
it's the complete desired set, so anything on the repo not listed in it is removed.

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

## Config format

A config file lists the repositories to manage and one shared block of config sections
applied to every one of them:

```yaml
repos:
  - owner/repo
  - owner/other
settings: { ... }
rulesets: [ ... ]
labels: [ ... ]
```

### Composing configs with `extends`

A file may `extends:` one or more base files (a string or a list, relative paths, resolved
recursively). The bases are merged underneath, then this file is merged on top:

- **scalars** — the override wins;
- **list sections** (`rulesets`, `labels.items`, `collaborators`, `webhooks`, `secrets`) —
  merge by each item's natural key (ruleset/label/secret `name`, collaborator `username`,
  webhook `url`): a same-key item in the override **replaces** the base's item, and new
  items are appended.

```yaml
# repos.yaml
extends: base.yaml
repos: [owner/repo]
settings:
  description: Managed by repo-management   # added on top of base.settings
```

See [`examples/base.yaml`](examples/base.yaml) + [`examples/repos.yaml`](examples/repos.yaml)
for a fully-annotated, working pair.

> `extends:` reads and merges local files by relative path, so only point it at config you
> trust — treat a base file the same as the config that includes it.

## What it manages

| Section | Manages |
| --- | --- |
| `settings` | description, homepage, topics, visibility, features (issues/wiki/projects/discussions), merge options (squash/merge/rebase, auto-merge, delete-branch-on-merge), default branch |
| `rulesets` | repository rulesets (branch/tag): the full rule set (pull_request, required_status_checks, required_linear_history, non_fast_forward, deletion, creation, update, required_deployments, merge_queue, required_signatures, the *_pattern rules, file_path/extension/size restrictions, workflows, code_scanning), plus `bypass_actors` and ref-name `conditions` |
| `labels` | create/update/delete labels to match the listed set exactly |
| `collaborators` | add/re-permission direct collaborators; remove those not listed |
| `webhooks` | create/update/delete webhooks, matched by URL |
| `secrets` | Actions secrets (write-only; libsodium-encrypted by PyGithub); delete those not listed |
| `variables` | Actions repository variables (plain text; updated only when the value differs); delete those not listed |

### Design notes / limitations

- **A declared section is authoritative.** Each section you include is the *complete*
  desired set: items present on the repo but absent from the section are removed (labels,
  webhooks, secrets, variables deleted; direct collaborators removed; repo rulesets
  deleted). A section you omit is left entirely unmanaged. This means a declared section
  can revoke access or delete a secret by omission — declare deliberately.
- **Only directly-granted collaborator access is managed.** Pruning uses
  `affiliation="direct"`, so access inherited from org or team membership is never listed
  and never touched (the repo API can't revoke it anyway).
- **Rulesets are matched by name and updated to the full declared spec.** PyGithub has no
  ruleset support, so this is driven through its authenticated requester against the REST
  rulesets API. On update, a ruleset's rules/conditions/bypass actors are PUT to exactly
  what the config declares. A declared ruleset's *lists* (rules, bypass actors, ref-name
  patterns) must match the live ones exactly — a manually-added rule is drift that triggers
  an update — while server-supplied metadata the config never sets (item `integration_id`,
  bypass `actor_id`, timestamps) is ignored, so it can't cause churn. Listing passes
  `includes_parents=false`, so inherited org/enterprise rulesets are never matched or
  deleted through the repo.
- **Secrets and webhook secrets are write-only.** The API never returns a secret value, so
  a change to *only* a secret can't be diffed: an Actions secret is re-sent on every apply,
  and a webhook with a configured secret is always re-sent (shown as `(set)` in the plan).
  Values are sourced from the environment (`value_from_env` / `secret_from_env`) and never
  printed. A literal `value:` is supported for secrets but should never be committed.
- **Variables, by contrast, are readable.** An Actions *variable* value is returned by the
  API, so a variable is updated only when its value actually differs and the value is shown
  in plain text in the plan. Variables take a literal `value:` or `value_from_env:` (same
  shape as secrets, minus the secrecy).

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
