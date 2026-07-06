<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Repo Management

Declarative, YAML-driven GitHub repository configuration. Describe how a repository
*should* be configured in a YAML file; `repo-management` reads the live state, shows you
the diff, and reconciles it through the GitHub API.

It is **declarative and idempotent**: re-running when nothing has changed does nothing. A
section you don't mention is left unmanaged; a section you *do* declare is authoritative —
it's the complete desired set, so anything on the repo not listed in it is removed.

## Install

--8<-- "install.md"

## Quick start

```bash
export GITHUB_TOKEN=ghp_...

cat > repos.yaml <<'EOF'
repos:
  - your-user/your-repo
settings:
  has_wiki: false
  delete_branch_on_merge: true
labels:
  - {name: bug,         color: d73a4a}
  - {name: enhancement, color: a2eeef}
EOF

repo-management validate -c repos.yaml   # check the YAML (no network)
repo-management plan     -c repos.yaml   # show the diff (read-only)
repo-management apply    -c repos.yaml   # reconcile (prompts before writing)
```

`plan` prints one line per change: `+` create, `~` update, `-` delete. Secret values are
always redacted. `repo-management list-repos` prints the managed fleet across a config
directory with no network access — see the [CLI reference](cli.md) for every command and
flag.

!!! warning "Declared sections are authoritative"
    A declared `labels:` section deletes labels not in the list; a declared
    `collaborators:` section removes unlisted direct collaborators. Start with `plan` and
    read the diff before your first `apply`.

## Reference

<div class="grid cards" markdown>

-   **[CLI](cli.md)**

    `validate`, `plan`, `apply`, `list-repos` — flags, output formats, and errors.

-   **[Config files](config.md)**

    Every section and field, authority semantics, and composing layers with `extends`.

-   **[Rulesets](rulesets.md)**

    Branch and tag rulesets: every rule type, conditions, and bypass actors.

</div>

## What it manages

Each section below is independent — declare only the ones you want managed — and each
declared section is authoritative (see the warning above). Full field-by-field detail for
every section lives in the [config reference](config.md).

<div class="grid cards" markdown>

-   **`settings`**

    Description, homepage, topics, visibility, feature toggles, merge options, default
    branch, template/archived flags.

-   **`actions`**

    Actions enablement/policy (including selected-actions patterns), default workflow
    permissions, and workflow-approval permission.

-   **`security`**

    Secret scanning + push protection, Dependabot vulnerability alerts, automated security
    fixes, private vulnerability reporting.

-   **`rulesets`**

    Repository rulesets (branch/tag) with the full rule set, bypass actors, and ref-name
    conditions.

-   **`labels`**

    Create/update/delete labels to match the listed set exactly.

-   **`collaborators`**

    Add/re-permission direct collaborators; remove those not listed.

-   **`webhooks`**

    Create/update/delete webhooks, matched by URL.

-   **`deploy_keys`**

    Create/delete deploy keys, matched by key content; delete those not listed.

-   **`autolinks`**

    Create/delete autolink references, matched by key prefix; delete those not listed.

-   **`pages`**

    GitHub Pages build type, source, custom domain, HTTPS enforcement; can also disable
    Pages.

-   **`secrets`**

    Actions secrets (write-only); delete those not listed.

-   **`variables`**

    Actions repository variables; delete those not listed.

-   **`environments`**

    Deployment environments — wait timer, reviewers, self-review prevention, branch
    policy — plus environment-scoped secrets/variables.

</div>

## Fleet automation

Beyond the CLI, the [nivintw/repo-management repository](https://github.com/nivintw/repo-management) —
the tool's home — is itself a working deployment: a control plane that manages its
author's repositories with scheduled GitHub Actions, reconciling them to `config/*.yml` on
every push and running a central [Renovate](https://docs.renovatebot.com) instance scoped
to exactly that fleet via `repo-management list-repos --format names`. It doubles as a
reference for running the tool this way.

## Development

Clone [the repository](https://github.com/nivintw/repo-management), then:

```bash
uv sync                      # create the venv + install everything
uv run pytest                # tests + coverage (gate: 90%; currently 100%)
uvx prek@0.4.8 run --all-files     # the full quality gate (ruff, format, REUSE, typos, …)
```
