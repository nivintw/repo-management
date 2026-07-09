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

```bash
export GITHUB_TOKEN=ghp_...

repo-management validate  -c repos.yaml   # check the YAML (no network)
repo-management plan      -c repos.yaml   # show the diff (read-only)
repo-management apply     -c repos.yaml   # reconcile (prompts before writing)
```

See the [CLI reference][docs-cli] for every command and flag, the
[config reference][docs-config] for the full config-file schema and every section it
manages, the [rulesets reference][docs-rulesets] for branch/tag ruleset details, and the
[Projects board reference][docs-projects] for declaratively managing a GitHub Projects v2
roadmap board and its automations. The repository's `examples/` has a fully-worked
[`base.yaml`][example-base] + [`repos.yaml`][example-repos] pair (plus
[`projects.yaml`][example-projects] for a board).

## Fleet automation

Beyond the CLI, the [nivintw/repo-management repository][repo] — the tool's home — is
itself a working deployment: a control plane that manages its author's repositories with
scheduled GitHub Actions, reconciling them to `config/*.yml` on every push and running a
central [Renovate] instance scoped to exactly that fleet via
`repo-management list-repos --format names`. See
[Fleet automation in the docs][docs-fleet-automation] for how the pieces fit together, and
`.github/workflows/docs.yml`'s own header comment for the reusable docs-build workflow
other fleet repos call.

## Development

Clone [the repository][repo], then:

```bash
uv sync                      # create the venv + install everything
uv run pytest                # tests + coverage (gate: 90%; currently 100%)
uvx prek@0.4.8 run --all-files     # the full quality gate (ruff, format, REUSE, typos, …)
```

Quality checks run identically locally and in CI via prek hooks: git hygiene, gitleaks,
typos, rumdl, SPDX/REUSE headers, and ruff. Conventional Commits (gitmoji) are enforced at
commit-msg time. A few hooks shell out to **system tools** prek can't bootstrap — install
them locally too (most are in Homebrew): `hawkeye`, `taplo`, `osv-scanner`.

## Publishing to PyPI

Published to **[PyPI](https://pypi.org/project/repo-management/)** on each GitHub Release via
OIDC **Trusted Publishing**, dress-rehearsed through **TestPyPI** first. See
`.github/workflows/publish.yml`'s header comment for the flow and the one-time
environment/Trusted-Publisher setup.

## License

[MIT][license] — and [REUSE](https://reuse.software)-compliant.

[docs]: https://nivintw.github.io/repo-management/
[PyGithub]: https://github.com/PyGithub/PyGithub
[Renovate]: https://docs.renovatebot.com
[repo]: https://github.com/nivintw/repo-management
[example-base]: https://github.com/nivintw/repo-management/blob/main/examples/base.yaml
[example-repos]: https://github.com/nivintw/repo-management/blob/main/examples/repos.yaml
[example-projects]: https://github.com/nivintw/repo-management/blob/main/examples/projects.yaml
[license]: https://github.com/nivintw/repo-management/blob/main/LICENSE
[docs-cli]: https://nivintw.github.io/repo-management/cli/
[docs-config]: https://nivintw.github.io/repo-management/config/
[docs-rulesets]: https://nivintw.github.io/repo-management/rulesets/
[docs-projects]: https://nivintw.github.io/repo-management/projects/
[docs-fleet-automation]: https://nivintw.github.io/repo-management/#fleet-automation
