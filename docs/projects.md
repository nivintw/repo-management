<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Projects board

`repo-management` can also manage a **GitHub [Projects v2](https://docs.github.com/en/issues/planning-and-tracking-with-projects) board** — declaratively, the same way it manages repositories. A board is a single owner-level entity (not a repo), and Projects v2 is GraphQL-only, so it lives under its own `projects` command group and its own config file, separate from the per-repo [`plan`/`apply`](cli.md) path.

Two things are managed, at two different altitudes:

- **The board's field schema** — its custom fields and their single-select options — declared in a config file and reconciled with `projects plan` / `projects apply`, exactly like a repo section (create-if-absent, update-if-differs, a plan you confirm before it writes).
- **The board's behavior** — a weekly status update, keeping each item's `Status` current, and a committed insights chart — driven by the `projects status` / `reconcile` / `insights` commands, wired to schedules and events by three workflows. This is the part GitHub's UI-only **Workflows** and **Insights** tabs can't be codified into.

What is *not* managed: **board membership** (which issues are on the board) and **per-issue field values** (which item is in which phase, its priority, its dates) churn as issues open and close, so they're owned by planning/automation tooling, not this declarative schema. And **view configuration** (layout, grouping, sort, filter) is genuinely UI-only — the Projects v2 API exposes no mutation for it — so it stays a documented manual step.

## Authentication

A user-level Projects v2 board can't be read or written by the default `GITHUB_TOKEN`. Every `projects` command needs a token with Projects read/write, from `--token` or `$GITHUB_TOKEN` — a **fine-grained PAT with `Projects: Read and write`** is the least-privilege choice (a classic PAT's `project` scope also works but is broader; read alone suffices for `plan`/`status`/`insights`, write for `apply`/`reconcile`/`status`).

!!! note "Why a PAT, not the CI App"
    The fleet's CI GitHub App administers *repositories*, but org Apps don't cleanly reach *user-owned* Projects v2 boards. So the roadmap automations authenticate with a **fine-grained PAT** carrying `Projects: Read and write`, stored as the `ROADMAP_PROJECT_TOKEN` repository secret. A PAT is broader and less-rotatable than the App — the pragmatic trade-off for a user-owned board; revisit if the board moves to an org.

## Config file

The board config is a standalone file — no `repos:`, no `extends:` — loaded directly by the `projects` commands (default `config/projects.yaml`). It declares the board's coordinates and its field schema:

```yaml
owner: your-login
owner_type: user # or `organization`
number: 1 # the board number, from its URL (…/projects/<number>)

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
| `number` | The board's number, from its URL. |
| `fields` | The custom fields to manage (at least one). |

Each **field** has a `name` and a `data_type` — `single_select`, `date`, `text`, or `number`. Only a `single_select` field carries `options` (and it must have at least one); the others must omit them. A field the manager doesn't recognize on the board is created; a field already present with a *different* `data_type` is left untouched with a warning (GitHub has no field-type mutation).

Each single-select **option** has a `name`, a `color` (one of `GRAY`, `BLUE`, `GREEN`, `YELLOW`, `ORANGE`, `RED`, `PINK`, `PURPLE`; default `GRAY`), and an optional `description`. Options are **ordered** — that's their display order — and matched against the live board **by name**, so a same-named option keeps its id and the board items already assigned to it.

!!! warning "Declared options are authoritative"
    Within a single-select field you declare, the `options` list is the complete desired set: an option present on the board but absent from the list is **removed**, which drops it from every item that had it. A `plan` surfaces that as a destructive change before you apply — read it before confirming. A field you *don't* declare is left entirely alone.

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

Validates the board config without contacting GitHub. Prints `✓ {config} is valid ({n} field(s) on {owner}/#{number})`.

### plan

```console
repo-management projects plan -c CONFIG [--token TOKEN]
```

Read-only. Prints the field/option changes needed to reconcile the board's schema, in the same `+`/`~`/`-` format as the per-repo [`plan`](cli.md#plan), or `✓ {owner}/#{number}: in sync`.

### apply

```console
repo-management projects apply -c CONFIG [--token TOKEN] [--yes]
```

Applies the schema diff. Prints the plan, then (unless `--yes`) prompts before writing. Declining exits with `error: aborted`.

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
