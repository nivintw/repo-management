<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# CLI reference

The `repo-management` command drives a [YAML config](config.md) against GitHub: validate it offline, preview the diff, or apply it. There are four repo subcommands — `validate`, `plan`, `apply`, and `list-repos` — plus a [`projects`](projects.md) command group for managing a GitHub Projects v2 roadmap board (documented separately, since a board is owner-level rather than per-repo).

## validate

```console
repo-management validate -c CONFIG
```

Validates the config file without contacting GitHub — no network access. Use it to catch schema errors before you need a token.

| Flag | Description |
| --- | --- |
| `--config` / `-c` | Path to the YAML config file. Required. |

On success:

```text
✓ {config} is valid ({n} repo(s))
```

## plan

```console
repo-management plan -c CONFIG [--repo owner/name] [--token TOKEN] [--force-secrets]
```

Read-only. Computes the diff between the config and each repo's current state on GitHub, and prints it without writing anything.

| Flag | Description |
| --- | --- |
| `--config` / `-c` | Path to the YAML config file. Required. |
| `--repo` / `-r` | Limit the run to a single `owner/name` repo from the config. Errors if the repo isn't in the config. |
| `--token` | GitHub token to authenticate with. Default: `$GITHUB_TOKEN`. |
| `--force-secrets` | Re-push existing secret values, as if rotating them. By default, secrets already present on the repo are left untouched. |

### Output

For each repo, either it's already in sync:

```text
✓ {repo}: in sync
```

or it lists the pending changes, one indented line per change:

```text
{repo} — {n} change(s):
  + [domain] target = value
  ~ [domain] target: before -> after
  - [domain] target (was value)
```

`+` marks a create, `~` an update, `-` a delete. The run ends with a summary line:

```text
{total} change(s) across {n} repo(s).
```

Because secret values are write-only payload — resolved only when `apply` writes them, never
to build the diff — `plan` is a true read-only preview that needs **no secret values present**;
it still shows every would-set / update / delete line for secrets. A **variable** value *is*
needed to compute its diff, so one whose `value_from_env` source is unset prints as a `!` line
and makes `plan` exit non-zero — without hiding the rest of the diff:

```text
  ! [domain] target: {reason the value couldn't be resolved}
```

### Every repo is independent

A `!` line is also how a *read* failure surfaces. Managers query GitHub while planning, and
those queries fail for reasons specific to one repository — a plan tier that doesn't carry
rulesets, an Actions endpoint that only exists for one visibility, a token without admin, a
repo renamed out from under the config. None of that aborts the run:

- A **manager** that fails contributes a `!` line for its own domain; the other domains for
  that repo still plan.
- A **repo** that can't be fetched at all contributes a single `! [repo]` line; every other
  repo still plans.

So a failure on the twelfth repo of sixteen costs you that repo's diff and nothing else. The
run still exits non-zero, naming which repos had problems — isolating a fault changes how it's
reported, not whether it counts:

```text
error: {n} problem(s) across {n} repo(s) (owner/beta) — see the ! line(s) above.
```

!!! note
    A failure whose type this tool anticipates — a GitHub API rejection, a config problem — is
    reported as a single line, because its message already says everything useful. Any other
    type is a bug in this tool rather than a fact about your repo, so it keeps its full
    traceback in the `!` line instead of being flattened into one sentence.

!!! note
    Secret values are always redacted in output as `<redacted>`, regardless of `--force-secrets` — the redaction is unconditional on the change itself, not a function of the flag. `--force-secrets` only controls whether an already-present secret is re-planned for rotation in the first place; it never controls whether a secret's value is printed. Variable values, by contrast, are shown in plaintext, so don't put anything sensitive in a `variables:` entry — use a secret instead.

## apply

```console
repo-management apply -c CONFIG [--repo owner/name] [--token TOKEN] [--force-secrets] [--yes]
```

Applies the same diff [`plan`](#plan) would show. Prints the plan first, then writes the changes to GitHub.

| Flag | Description |
| --- | --- |
| `--config` / `-c` | Path to the YAML config file. Required. |
| `--repo` / `-r` | Limit the run to a single `owner/name` repo from the config. Errors if the repo isn't in the config. |
| `--token` | GitHub token to authenticate with. Default: `$GITHUB_TOKEN`. |
| `--force-secrets` | Re-push existing secret values, as if rotating them. By default, secrets already present on the repo are left untouched. |
| `--yes` / `-y` | Skip the confirmation prompt. |

If every repo is already in sync, it prints `nothing to do` and exits without prompting. Otherwise, unless `--yes` is given, it asks:

```text
Apply {total} change(s)?
```

!!! warning
    Declining the prompt exits with `error: aborted` and applies nothing.

On success:

```text
✓ applied {n} change(s) across {n} repo(s)
```

### A failure costs one repo, not the fleet

`apply` holds the same independence `plan` does, and reports every repo it touched or didn't:

- A repo whose plan carries **any** `!` line is **skipped** — its diff was computed from
  incomplete state, so writing it would apply a partial picture. Every healthy repo still
  applies.
- A repo whose secret payloads won't resolve is likewise skipped, before any of its writes run.
  A repo's own writes stay all-or-nothing.
- A **single failed write** costs its own change, not the rest of its repo. A 403 on webhooks
  says nothing about whether labels can be written, so the remaining changes still apply.

Skips and failures print to stderr, each naming the repo (and, for a write, the target):

```text
skipped owner/beta: {n} problem(s) in its plan — see the ! line(s) above
failed owner/alpha webhook:x: {reason the write was rejected}
error: {n} change(s) failed; {n} repo(s) skipped.
```

!!! warning
    Anything short of a clean sweep exits non-zero. A partially-applied fleet is a **failed**
    run even though some repos were reconciled — re-run once the reported problems are fixed.
    `apply` is idempotent, so the repos that already succeeded are no-ops on the next pass.

## list-repos

```console
repo-management list-repos [--config-dir DIR] [--format lines|names]
```

Lists the managed-repo fleet: the union of the `repos:` lists across every applied `*.yml` file in the config directory. `*.yaml` files are treated as extends-only base layers and skipped — they're only reachable through another config's `extends:`. No network access.

| Flag | Description |
| --- | --- |
| `--config-dir` | Directory of applied config files to scan. Default: `config`. |
| `--format` / `-f` | Output shape: `lines` or `names`. Default: `lines`. |

### Formats

| Format | Output |
| --- | --- |
| `lines` | One `owner/repo` per line. |
| `names` | A single comma-separated line of bare repo names, with the owner stripped. Requires the fleet to have a single owner — errors otherwise. |

`names` output is sized for scoping a GitHub App token's `repositories:` list to exactly the fleet. Output is plain stdout — no styling or line wrapping — so it's safe to pipe or capture in a narrow terminal.

## projects

```console
repo-management projects {validate|plan|apply|status|reconcile|insights} -c CONFIG
```

Manages a GitHub Projects v2 board — its field schema (`plan`/`apply`), a weekly status update (`status`), each item's `Status` (`reconcile`), and a committed insights chart (`insights`). A board is a single owner-level entity, not a repo, so these commands take their own config file and a token with Projects access — a classic PAT with the `project` scope for a user-owned board (fine-grained tokens only cover org-owned boards). See **[Projects board](projects.md)** for the full reference and auth details.

## Global behavior

### Authentication

Commands that talk to GitHub ([`plan`](#plan), [`apply`](#apply)) need a token, from `--token` or the `$GITHUB_TOKEN` environment variable. The token needs scopes covering whatever the config manages on the target repos. [`validate`](#validate) and [`list-repos`](#list-repos) never contact GitHub and don't need a token.

### Errors

All errors print to stderr as `error: {message}` and exit with status 1. Errors returned by the GitHub API surface as:

```text
error: GitHub API error: {detail}
```
