<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Projects board

`repo-management` can also manage a **GitHub [Projects v2](https://docs.github.com/en/issues/planning-and-tracking-with-projects) board** — declaratively, the same way it manages repositories. A board is a single owner-level entity (not a repo), and Projects v2 is GraphQL-only, so it lives under its own `projects` command group and its own config file, separate from the per-repo [`plan`/`apply`](cli.md) path.

Two things are managed, at two different altitudes:

- **The board itself and its field schema** — the board's custom fields and their single-select options — declared in a config file and reconciled with `projects plan` / `projects apply`, exactly like a repo section (create-if-absent, update-if-differs, a plan you confirm before it writes). A board you address by [`title`](#addressing-the-board) is created if it doesn't exist yet.
- **The board's behavior** — a weekly status update, keeping each item's `Status` current, and a committed insights chart — driven by the `projects status` / `reconcile` / `insights` commands, wired to schedules and events by three workflows. This is the part GitHub's UI-only **Workflows** and **Insights** tabs can't be codified into.

What is *not* managed: **board membership** (which issues are on the board) and **per-issue field values** (which item is in which phase, its priority, its dates) churn as issues open and close, so they're owned by planning/automation tooling, not this declarative schema. And **view configuration** (layout, grouping, sort, filter) is genuinely UI-only — the Projects v2 API exposes no mutation for it — so it stays a documented manual step.

## Authentication

A user-level Projects v2 board can't be read or written by the default `GITHUB_TOKEN`. Every `projects` command needs a token with Projects access, from `--token` or `$GITHUB_TOKEN`.

For a **user-owned** board (the common case), that means a **classic PAT with the `project` scope** — `read:project` alone suffices for the read-only commands (`plan`, `insights`, `status --dry-run`), and full `project` for the writes (`apply`, `reconcile`, `status`). Fine-grained PATs expose a Projects permission only for **org-owned** boards — [there is no user-account Projects permission](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) — so a fine-grained PAT with `Projects: Read and write` is an option **only if this board is org-owned**. (A classic `project` PAT can't be scoped to a single project; that breadth is the trade-off for a user-owned board until GitHub adds a fine-grained equivalent.)

`project` is the only scope needed to manage the board's schema and post status updates. The **one** case that needs more: `status`/`reconcile`/`insights` read each item's linked issue/PR (title, state, `status:*` labels), and reading that content for an item in a **private** repo requires the `repo` scope too — without it, private-repo items are invisible to the token and silently drop out of the board snapshot. A board that only tracks public-repo issues (like the Fleet Roadmap today) needs `project` alone; add `repo` if you put private-repo issues on it.

!!! note "Why a classic PAT, not the CI App or a fine-grained token"
    The fleet's CI GitHub App administers *repositories*, but org Apps don't cleanly reach *user-owned* Projects v2 boards — and fine-grained PATs offer no Projects permission for user-owned boards at all. So for the Fleet Roadmap (a user-owned board), the automations authenticate with a **classic PAT carrying the `project` scope**, stored as the `ROADMAP_PROJECT_TOKEN` repository secret. A classic PAT is broader and less-rotatable than the App or a fine-grained token — the pragmatic trade-off GitHub currently forces for a user-owned board; revisit (switch to a fine-grained `Projects: Read and write` PAT) if the board ever moves to an org.

## Config file

The board config is a standalone file — no `repos:`, no `extends:` — loaded directly by the `projects` commands (default `config/projects.yaml`). It declares how to reach the board and its field schema:

```yaml
owner: your-login
owner_type: user # or `organization`
number: 1 # or `title:` — see "Addressing the board" below

fields:
  - name: Status
    data_type: single_select
    options:
      - name: Todo
        color: GRAY
        description: Not started
      - name: In Progress
        color: YELLOW
        description: Being worked on
      - name: Done
        color: GREEN
        description: Completed

  - name: Target
    data_type: date
```

| Key | Meaning |
| --- | --- |
| `owner` | The board owner's login. |
| `owner_type` | `user` (default) or `organization` — selects the GraphQL query root. |
| `number` | The board's number, from its URL. Adopts an existing board. Mutually exclusive with `title`. |
| `title` | The board's exact title. Adopts a matching board, or **creates** it. Mutually exclusive with `number`. |
| `fields` | The custom fields to manage (at least one). |

Each **field** has a `name` and a `data_type` — `single_select`, `date`, `text`, or `number`. Only a `single_select` field carries `options` (and it must have at least one); the others must omit them. A field the manager doesn't recognize on the board is created.

A field already present with a *different* `data_type` **can't be reconciled at all** — GitHub exposes no field-type mutation — so it's reported as an unresolved value (a `!` line) and **blocks the run**: `plan` exits non-zero and `apply` writes nothing. Rename or recreate the field by hand, or drop it from config. This is deliberately loud rather than a skipped field, because the alternative is `plan` reporting `✓ in sync` forever over a board that can never reach its declared state.

!!! warning "GitHub's built-in fields have types you can't declare"
    A board comes with built-ins — `Title`, `Assignees`, `Labels`, `Milestone`, `Repository` — whose types have no `data_type` counterpart here. Declaring one of those names hits the mismatch above. `Status` is the exception: it's an ordinary `single_select`, which is exactly why it's reconcilable (see [One status field](#one-status-field)). On a **newly created** board these built-ins only become visible once the board exists, so that mismatch surfaces during `apply` rather than in the plan — the board is created, then the run fails with the `!` reason.

Each single-select **option** has a `name`, a `color` (one of `GRAY`, `BLUE`, `GREEN`, `YELLOW`, `ORANGE`, `RED`, `PINK`, `PURPLE`; default `GRAY`), and an optional `description`. Options are **ordered** — that's their display order — and matched against the live board **by name**, so a same-named option keeps its id and the board items already assigned to it.

!!! warning "Declared options are authoritative"
    Within a single-select field you declare, the `options` list is the complete desired set: an option present on the board but absent from the list is **removed**, which drops it from every item that had it. A `plan` surfaces that as a destructive change before you apply — read it before confirming. A field you *don't* declare is left entirely alone.

### Addressing the board

A board is addressed by **exactly one** of `number` or `title` — declaring both, or neither, is a config error. The choice isn't cosmetic: it selects what an `apply` is allowed to do.

=== "`number` — adopt"

    ```yaml
    owner: your-login
    number: 1 # from the board's URL: …/projects/1
    ```

    GitHub assigns a board's number **when the board is created**, so a number always names a board that already exists. A number that doesn't resolve is an error — never an invitation to create something. Reach for this when you want the config pinned to one specific board and nothing else.

=== "`title` — converge"

    ```yaml
    owner: your-login
    title: Fleet Roadmap
    ```

    Finds the board with this exact title among the owner's **open** boards and adopts it — or **creates it** if there isn't one. This is the only way to declare a board that doesn't exist yet, precisely because you can't know its number in advance. Running `apply` twice is safe: the second run finds the board it made rather than making another.

    **Closed boards are invisible here.** A closed board is never adopted by title (reconciling fields onto a board nobody uses isn't what you meant), and an abandoned same-titled board can't make the title ambiguous. Address a closed board by `number` if you really want to manage it.

`title` is an **address, not a managed attribute**. Renaming the board in GitHub's UI doesn't rename it in config — it means the declared board is *gone*, and the next `apply` creates a new one alongside it. Pin with `number` when that matters. Renaming an existing board isn't something this tool does.

If two of the owner's **open** boards share the declared title, `plan` and `apply` both fail naming the numbers they found, rather than picking one — silently managing the wrong board is worse than refusing to guess.

A `title`-addressed `plan` names the board it resolved to — `nivintw/'Fleet Roadmap' (#2)` — so you can check *which* board an apply is about to write to before confirming it.

!!! note "What creating a board applies"
    Creating a board is a **single change** in the plan, because the field mutations need a board id that doesn't exist until the board does. Its plan line therefore spells out every field it will write — the whole preview lives in that one line. GitHub seeds every new board with its own `Status` single-select, so a declared `Status` **reconciles** that built-in field rather than adding a second one.

### One status field

The manager treats GitHub's built-in **`Status`** field as an ordinary single-select, so declaring a `Status` field reconciles its options like any other. That's deliberate: only the built-in `Status` drives GitHub's closed→Done workflow, the board columns, and the default grouping, so the roadmap carries **one** status field (its options extended to the full lifecycle — `Todo` / `Ready` / `In Progress` / `In Review` / `Blocked` / `Done`) rather than a built-in field plus a drift-prone custom one.

## Commands

All six live under `repo-management projects`:

| Command | What it does |
| --- | --- |
| [`validate`](#validate) | Check the board config offline (no network). |
| [`plan`](#plan) | Show the field-schema diff (read-only). |
| [`apply`](#apply) | Reconcile the board's fields and options. |
| [`status`](#status) | Post a weekly status update. |
| [`reconcile`](#reconcile) | Sync each item's `Status` from its issue; archive old closed items. |
| [`insights`](#insights) | Render the board's cross-repo charts to a committed SVG. |

### validate

```console
repo-management projects validate -c CONFIG
```

Validates the board config without contacting GitHub — including that the board is addressed by exactly one of `number` or `title`. Prints `✓ {config} is valid ({n} field(s) on {board})`, where `{board}` is `{owner}/#{number}` or `{owner}/'{title}'` depending on how you addressed it.

### plan

```console
repo-management projects plan -c CONFIG [--token TOKEN]
```

Read-only. Prints the changes needed to reconcile the board, in the same `+`/`~`/`-` format as the per-repo [`plan`](cli.md#plan), or `✓ {board}: in sync`. For a `title`-addressed board that doesn't exist yet, that's a single `+ [projects] board:{title}` line listing every field the apply would create.

### apply

```console
repo-management projects apply -c CONFIG [--token TOKEN] [--yes]
```

Applies the plan. Prints it, then (unless `--yes`) prompts before writing. Declining exits with `error: aborted`. This is the only command that creates a board — every other one reads a board that already exists, and fails if a `title`-addressed board is missing.

### status

```console
repo-management projects status -c CONFIG [--token TOKEN] [--dry-run] [--force]
```

Posts a **status update** to the board: a deterministic health label — `COMPLETE`, `OFF_TRACK`, `AT_RISK`, or `ON_TRACK` — plus a markdown narrative of what shipped this week, what's blocked, and what's up next. The label ladder is auditable (no model in the loop):

| Label | When |
| --- | --- |
| `COMPLETE` | Nothing open. |
| `OFF_TRACK` | A `P1`/Safety-phase item is open past its target. |
| `AT_RISK` | Any phase overdue, three or more blocked items, or stalled (Ready work but nothing closed this window). |
| `ON_TRACK` | Otherwise. |

It **dedupes** within a 6-day window (a cron can double-fire), so a second run the same week is a no-op unless `--force`. `--dry-run` prints the computed update without posting.

### reconcile

```console
repo-management projects reconcile -c CONFIG [--token TOKEN] [--dry-run] [--yes] [--archive-after-days N]
```

Brings the board's `Status` current from the source of truth — **issue state and `status:*` labels** — and archives long-closed items. This is what lets the built-in Workflows tab be turned off. The mapping:

| Item | Desired `Status` |
| --- | --- |
| Closed / merged | `Done` |
| Open + `status:blocked` | `Blocked` |
| Open + `status:in-review` | `In Review` |
| Open + `status:in-progress` | `In Progress` |
| Open + `status:ready` | `Ready` |
| Open + `status:triage` | `Todo` |
| Open, no `status:*` label | *left untouched* |

A change is emitted only when an item's desired `Status` differs from its current value **and** that option exists on the board. Items closed longer ago than `--archive-after-days` (default 14; negative disables) are archived, keeping recently shipped work visible. Like `apply`, it prints the plan and prompts unless `--yes`; `--dry-run` skips the write.

!!! note "Labels own `Status`"
    Because the reconcile derives `Status` from state and labels, a manual `Status` edit in the Projects UI is reverted on the next run — but only on a *definitive* signal (an item with no `status:*` label is left alone, so a hand-set value survives where labels can't override it).

### insights

```console
repo-management projects insights -c CONFIG [--token TOKEN] [-o OUTPUT]
```

Renders the board's cross-repo tallies — items by repository, by phase, and by status — to a self-contained bar-chart **SVG** (default `docs/roadmap/insights.svg`). The Insights *chart config* is UI-only, but the data isn't: this reproduces the same metrics as a versioned, shareable file.

## Automations

Three workflows wire the commands to schedules and events. Each is gated behind a preflight that **skips cleanly** (green, no writes) until `ROADMAP_PROJECT_TOKEN` exists, so merging them is always safe:

| Workflow | Trigger | Runs |
| --- | --- | --- |
| `project-status.yml` | Mondays 14:00 UTC + dispatch | `projects status` |
| `project-reconcile.yml` | every 6 h + this repo's issue events + dispatch | `projects reconcile` |
| `project-insights.yml` | daily 06:00 UTC + dispatch | `projects insights`, then commits the SVG |

The reconcile has **two triggers, one operation**. A workflow only sees its own repo's issue events, but the PAT can read every fleet repo, so the **6-hourly sweep is the fleet-wide net** that actually retires the built-in Workflows tab. The issue-event triggers add low-latency updates for this repo's own items — and there's deliberately *no* `pull_request` trigger, because a merged PR that closes an issue via `Closes #N` fires an `issues: closed` event, covering "PR merged → Done" without running any PR-head code against the PAT.

!!! note "Fleet-wide events are a follow-up"
    Low-latency events for *every* fleet repo would mean templating these workflows into each repo via `copier-everything` — a separate rollout, not part of this feature. Until then, the scheduled sweep is the net.
