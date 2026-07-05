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

Full documentation lives at **[nivintw.github.io/repo-management][docs]**; the source code,
issue tracker, and annotated example configs live in the
[nivintw/repo-management repository][repo] on GitHub.

## Install

```bash
uv tool install repo-management    # or: pip install repo-management
```

Requires Python 3.14+. Authentication uses a GitHub token, read from `$GITHUB_TOKEN` (or
`--token`). The token needs the scopes for whatever you manage (repo administration,
Actions secrets, etc.).

## Usage

Write a config file first — the `repos.yaml` below; see [Config format](#config-format)
for the schema and the repository's annotated [`examples/`][example-base] for a working
pair. Then:

```bash
export GITHUB_TOKEN=ghp_...

repo-management validate  -c repos.yaml   # check the YAML (no network)
repo-management plan      -c repos.yaml   # show the diff (read-only)
repo-management apply     -c repos.yaml   # reconcile (prompts before writing)
repo-management list-repos                # the managed fleet across a config dir (no network)
```

Useful flags:

- `--repo owner/name` — limit the run to a single repo from the config.
- `--yes` / `-y` — skip the confirmation prompt on `apply`.
- `--token` — pass a token explicitly instead of using `$GITHUB_TOKEN`.

`plan` prints one line per change: `+` create, `~` update, `-` delete. Secret values are
always redacted.

`list-repos` prints the managed fleet — the union of the `repos:` lists across every
applied `*.yml` file in a config directory (`--config-dir`, default `config/`; `*.yaml`
files are treated as base layers, not applied configs, and are skipped). `--format names`
emits a single comma-separated line of owner-relative names, which the
[repo-management repository][repo] uses to scope its central Renovate runner's App token
(see [Fleet automation](https://nivintw.github.io/repo-management/#fleet-automation)).

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
- **list sections** (`rulesets`, `labels`, `collaborators`, `webhooks`, `secrets`,
  `variables`, `deploy_keys`, `autolinks`, `environments`) — merge by each item's natural
  key (ruleset/label/secret/variable/environment `name`, collaborator `username`, webhook
  `url`, deploy key `key`, autolink `key_prefix`): a same-key item in the override
  **replaces** the base's item, and new items are appended.

```yaml
# repos.yaml
extends: base.yaml
repos: [owner/repo]
settings:
  description: Managed by repo-management   # added on top of base.settings
```

See [`examples/base.yaml`][example-base] + [`examples/repos.yaml`][example-repos] in the
repository for a fully-annotated, working pair.

> `extends:` reads and merges local files by relative path, so only point it at config you
> trust — treat a base file the same as the config that includes it.

## What it manages

| Section | Manages |
| --- | --- |
| `settings` | description, homepage, topics, visibility, features (issues/wiki/projects/discussions), merge options (squash/merge/rebase, auto-merge, delete-branch-on-merge, squash/merge commit title & message, web commit signoff), default branch, template/archived flags |
| `actions` | Actions enablement and allowed-actions policy (`enabled`, `allowed_actions`, `selected_actions` patterns), default workflow permissions (`default_workflow_permissions`), and workflow approval permission (`can_approve_pull_request_reviews`) |
| `security` | secret scanning + push protection, Dependabot vulnerability alerts, automated security fixes, and private vulnerability reporting |
| `rulesets` | repository rulesets (branch/tag): the full rule set (pull_request, required_status_checks, required_linear_history, non_fast_forward, deletion, creation, update, required_deployments, merge_queue, required_signatures, the *_pattern rules, file_path/extension/size restrictions, workflows, code_scanning), plus `bypass_actors` and ref-name `conditions` |
| `labels` | create/update/delete labels to match the listed set exactly |
| `collaborators` | add/re-permission direct collaborators; remove those not listed |
| `webhooks` | create/update/delete webhooks, matched by URL |
| `deploy_keys` | create/delete deploy keys, matched by key content; delete those not listed |
| `autolinks` | create/delete autolink references, matched by key prefix; delete those not listed |
| `pages` | GitHub Pages build type, source branch/path, custom domain, and HTTPS enforcement; `enabled: false` disables it |
| `secrets` | Actions secrets (write-only; libsodium-encrypted by PyGithub); delete those not listed |
| `variables` | Actions repository variables (plain text; updated only when the value differs); delete those not listed |
| `environments` | deployment environments — wait timer, required reviewers, self-review prevention, branch policy — plus environment-scoped secrets/variables |

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
  a change to *only* a secret can't be diffed: an Actions secret already present on the repo
  is left untouched by default (pass `--force-secrets` to re-push values for rotation), and
  a webhook with a configured secret is always re-sent (shown as `(set)` in the plan).
  Values are sourced from the environment (`value_from_env` / `secret_from_env`) and never
  printed. A literal `value:` is supported for secrets but should never be committed.
- **Variables, by contrast, are readable.** An Actions *variable* value is returned by the
  API, so a variable is updated only when its value actually differs and the value is shown
  in plain text in the plan. Variables take a literal `value:` or `value_from_env:` (same
  shape as secrets, minus the secrecy).
- **Deploy keys and autolinks have no update endpoint.** GitHub's APIs for both only
  support create/list/delete, so changing an existing entry (e.g. a deploy key's `title` or
  an autolink's `url_template`) is planned as a delete of the old entry paired with a create
  of the new one, not a single in-place update.
- **Environments reuse the secrets/variables logic per-environment.** An environment's
  `secrets`/`variables` follow the same authoritative-set semantics as the top-level
  sections, scoped to that environment. A `Team` reviewer resolves its `slug` through the
  repo's owning org (a config error on a non-org-owned repo); a `User` reviewer resolves its
  `login` directly. Because `create_environment` is a single PUT covering wait timer,
  reviewers, self-review prevention, and branch policy together, an unset field on an
  *existing* environment is preserved at its live value rather than reset — the API has no
  partial-update form.
- **Pages has no explicit "disable" by default omission.** Leaving `pages:` out entirely
  leaves Pages unmanaged; declaring it with `enabled: false` disables it if currently on.
  Creating a new Pages site with `cname`/`https_enforced` set takes two API calls (GitHub's
  create endpoint only accepts `build_type`/`source`), planned as one change.

## Fleet automation

Beyond the CLI, the [nivintw/repo-management repository][repo] — the tool's home — is
itself a working deployment: a control plane that manages its author's repositories (its
"fleet") with scheduled GitHub Actions, authenticating as a CI GitHub App. It doubles as a
reference for running the tool this way:

- **`apply-config` / `plan-config`** — reconcile the live repos to the repository's
  `config/*.yml`: `apply` on push to `main`, `plan` as a read-only PR preview.
- **`renovate`** — a central, self-hosted [Renovate] runner that opens dependency-update
  PRs across the managed fleet on a schedule, replacing the hosted Renovate app (and
  unlocking `postUpgradeTasks`, so a bumped binary's checksum is refreshed inside
  Renovate's own commit). It scopes its App token to exactly the fleet —
  `repo-management list-repos --format names` derives that set from the same `config/*.yml`
  that drives `apply`, so one config is the single source of truth for what Renovate
  touches. Its global behaviour lives in the repository's
  [`.github/renovate-global.json`][renovate-global], separate from the repository's own
  dependency policy in [`.github/renovate.json`][renovate-json]. Dispatch it manually with
  **`dryRun`** to preview the scope and proposed changes without opening any PRs.
- **`docs.yml`** — a reusable (`workflow_call`) workflow other fleet repos call to build an
  MkDocs Material site and deploy it to GitHub Pages, so each repo's own docs workflow is a
  thin caller instead of duplicating build/deploy logic. `mkdocs` and `mkdocs-material` are
  pinned inside the workflow (one Renovate-tracked pin covers the whole fleet); callers
  supply `docs-dir` and, if their `mkdocs.yml` needs plugins beyond Material,
  `extra-packages`. Callers must grant `permissions: {contents: read, pages: write,
  id-token: write}` on the calling job — declaring any `permissions:` block there forces
  every omitted scope to `none`, so `contents: read` has to be listed explicitly too, not
  just assumed.

## Development

Clone [the repository][repo], then:

```bash
uv sync                      # create the venv + install everything
uv run pytest                # tests + coverage (gate: 90%; currently 100%)
uvx prek run --all-files     # the full quality gate (ruff, format, REUSE, typos, …)
```

Quality checks run identically locally and in CI via prek hooks: git hygiene, gitleaks,
typos, rumdl, SPDX/REUSE headers, and ruff. Conventional Commits (gitmoji) are enforced at
commit-msg time. A few hooks shell out to **system tools** prek can't bootstrap — install
them locally too (most are in Homebrew): `hawkeye`, `taplo`, `osv-scanner`.

## License

[MIT][license] — and [REUSE](https://reuse.software)-compliant.

[docs]: https://nivintw.github.io/repo-management/
[PyGithub]: https://github.com/PyGithub/PyGithub
[Renovate]: https://docs.renovatebot.com
[repo]: https://github.com/nivintw/repo-management
[example-base]: https://github.com/nivintw/repo-management/blob/main/examples/base.yaml
[example-repos]: https://github.com/nivintw/repo-management/blob/main/examples/repos.yaml
[renovate-global]: https://github.com/nivintw/repo-management/blob/main/.github/renovate-global.json
[renovate-json]: https://github.com/nivintw/repo-management/blob/main/.github/renovate.json
[license]: https://github.com/nivintw/repo-management/blob/main/LICENSE
