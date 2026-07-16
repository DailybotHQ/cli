# Commands Reference

> Slash commands available in this repository. Invoked as `/<name>` in Claude Code, or `#<name>` in Codex / Cursor / Gemini. The catalog of skills and agent personas these commands route to lives in [`skills_agents_catalog.md`](skills_agents_catalog.md).

All commands in `.agents/commands/` are **thin delegators** — they route the invocation to a sub-skill that owns the actual flow. Editing the command file changes only the routing label; the procedural content lives in the corresponding `.agents/skills/<slug>/SKILL.md`. This is the standard the [Deep Work Plan kit](https://deepworkplan.com/kit) prescribes: a single source of truth in the skill, with thin per-command aliases for discoverability.

---

## Deep Work Plan commands

The full plan-execute-verify loop, delegating to the vendored `deepworkplan` skill pack at [`../skills/deepworkplan/`](../skills/deepworkplan/). When invoked, each command routes to its matching sub-skill's `SKILL.md`.

| Slash command | Routes to | What it does | Typical trigger |
|---|---|---|---|
| `/dwp-create` | `../skills/deepworkplan/create/SKILL.md` | Decompose a goal into a structured plan (numbered tasks, validation gates, success criteria) and persist it under `.dwp/plans/` (or as a draft under `.dwp/drafts/`). | "Plan the migration to httpx-retries" |
| `/dwp-execute` | `../skills/deepworkplan/execute/SKILL.md` | Execute the current plan task-by-task, updating state in `.dwp/`, validating each task's gate before advancing. | "Execute the plan" |
| `/dwp-refine` | `../skills/deepworkplan/refine/SKILL.md` | Add, remove, or reorder tasks while preserving completed work and existing validation gates. | "Add a task to also update the Homebrew formula" |
| `/dwp-resume` | `../skills/deepworkplan/resume/SKILL.md` | Reconstruct state from `.dwp/` after an interrupted session and continue execution. | "Pick up where we left off" |
| `/dwp-status` | `../skills/deepworkplan/status/SKILL.md` | Report plan progress without making any changes. | "Where are we in the plan?" |
| `/dwp-verify` | `../skills/deepworkplan/verify/SKILL.md` | Run an objective DWP conformance check on the repository against the [DWP specification](https://deepworkplan.com/spec). Emits a binary CONFORMANT / NOT CONFORMANT verdict. | "Is this repo DWP-conformant?" |
| `/deepworkplan-onboard` | `../skills/deepworkplan/onboard/SKILL.md` | Re-run the 9-phase onboard flow as a reconciliation pass — non-destructive by design. | "Re-onboard against the latest DWP spec" |
| `/skill-create` | `../skills/deepworkplan/author/SKILL.md` | Create a new skill in `.agents/skills/<slug>/`. | "Create a skill for the cherry-pick release workflow" |
| `/agent-create` | `../skills/deepworkplan/author/SKILL.md` | Create a new agent persona in `.agents/agents/<slug>.md`. | "Create an agent persona for the CI investigator role" |
| `/design-system` | `../skills/deepworkplan/addons/design-system/SKILL.md` | Refresh `docs/DESIGN.md` from the real design source (`display.py` + `DISPLAY_OUTPUT_BEST_PRACTICES.md`) via the DWP design-system addon. | "Re-sync DESIGN.md after refactoring `display.py`" |

## AI Diff Reviewer (Flow B)

Vendored skill at [`../skills/ai-diff-reviewer/`](../skills/ai-diff-reviewer/) (**v2.0.0**). CI gate: apply the **`Ready`** label on a PR to `main` (see [`.github/workflows/pr-review.yml`](../../.github/workflows/pr-review.yml); requires `CURSOR_API_KEY`). Extension: [`.review/extension.md`](../../.review/extension.md).

| Command / phrase | Routes to | What it does | Example trigger |
|------------------|-----------|--------------|-----------------|
| `/ai-diff-reviewer` | `../skills/ai-diff-reviewer/SKILL.md` | Local review of the current branch (verdict + findings); used by DWP Security Review when skill + extension are present | "Review my current branch" |
| `/ai-diff-reviewer-generate-extension` | `../skills/ai-diff-reviewer/generate-extension/SKILL.md` | Regenerate `.review/extension.md` from repo evidence | "Customize the review for this repo" |
| `/ai-diff-reviewer-setup` | `../skills/ai-diff-reviewer/setup/SKILL.md` | Re-run the CI workflow wizard | "Set up AI Diff Reviewer for this repo" |
| `/ai-diff-reviewer-open-pr` | `../skills/ai-diff-reviewer/open-pr/SKILL.md` | Draft PR title/body from the branch diff | "Open a PR for this branch" |
| `/ai-diff-reviewer-apply-review` | `../skills/ai-diff-reviewer/apply-review/SKILL.md` | Walk CI findings per-finding (apply / defer / skip); never commits | "Apply the CI review findings" |

Every plan ends with three mandatory final tasks (per the DWP spec): a **Security Review** of the plan's own changes (a critical finding blocks completion), a **Skills & Agents Discovery** pass, and an **Executive Report**.

State persists in [`.dwp/`](../../.dwp/) which is gitignored — only the placeholders `.dwp/plans/.gitkeep` and `.dwp/drafts/.gitkeep` are tracked.

---

## Repository-specific skills (CLI dev workflow)

Project-scoped slash commands curated for `dailybot-cli` work. Each routes to a procedure under [`../skills/`](../skills/).

| Slash command | Routes to | What it does | Typical trigger |
|---|---|---|---|
| `/quick-fix` | [`../skills/quick-fix/SKILL.md`](../skills/quick-fix/SKILL.md) | Tiny, single-file bug fix or typo correction with minimal ceremony. | "Fix the typo in the help string for `dailybot login`" |
| `/cli-command-add` | [`../skills/cli-command-add/SKILL.md`](../skills/cli-command-add/SKILL.md) | End-to-end procedure for adding a new top-level CLI command or subgroup. | "Add `dailybot survey list` as a new top-level command" |
| `/endpoint-add` | [`../skills/endpoint-add/SKILL.md`](../skills/endpoint-add/SKILL.md) | Wire a new Dailybot API endpoint into `api_client.py` with tests — no command-side changes. | "Add `client.list_surveys()` for the new `/v1/surveys/` endpoint" |
| `/dependency-add` | [`../skills/dependency-add/SKILL.md`](../skills/dependency-add/SKILL.md) | Add a Python dependency to `pyproject.toml` AND update the Homebrew formula in `release.yml`. | "Add `httpx-retries` to dependencies" |
| `/doc-edit` | [`../skills/doc-edit/SKILL.md`](../skills/doc-edit/SKILL.md) | Documentation-only change (README, AGENTS.md, docs/*) without touching source code. | "Update the `release` doc to reflect the new `[skip release]` marker" |
| `/release-prep` | [`../skills/release-prep/SKILL.md`](../skills/release-prep/SKILL.md) | Pre-tag checklist + version bump for an emergency manual release (the automated path is `auto-release.yml`). | "Prep a release for v1.13.2" |

---

## Dailybot agent skill pack (vendored)

The full pack lives under [`../skills/dailybot/`](../skills/dailybot/) (router + 9 sub-skills). The router auto-routes by intent — read [`../skills/dailybot/SKILL.md`](../skills/dailybot/SKILL.md) and let it pick the right sub-skill. Each sub-skill is independently invocable; the full list lives in [`skills_agents_catalog.md`](skills_agents_catalog.md).

---

## Conventions

- **Every `dwp-*` command is a thin delegator** — never copy the flow from the skill into the command file. The skill owns the procedural content; duplicating it causes drift. Updating the command file should only ever change the routing label.
- **Stack-specific skills** in this repo (the second table above) are full procedures, not delegators — they have no "host skill" to route to; the procedure lives in the file itself.
- **Slash command discoverability** depends on `.agents/commands/<name>.md` existing with a `description:` frontmatter field. Both this catalog and the harness's discovery loop (Claude Code's `/<name>` autocomplete, Cursor's `#<name>` autocomplete) read that field.

## Adding a new command

Use `/skill-create` (or `/agent-create`) — both delegate to the DWP `author` sub-skill, which knows how to create a new skill or agent **and** how to update this catalog plus `skills_agents_catalog.md` so reality and docs stay aligned. Do not hand-roll a new command file without running the author sub-skill — it enforces the catalog-in-sync invariant Phase 8 of `/deepworkplan-onboard` validates.
