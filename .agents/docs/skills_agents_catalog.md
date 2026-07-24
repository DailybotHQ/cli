# Skills & Agents Catalog — Dailybot CLI

The index of every skill (slash command) and agent (persona) available in this repo.

## Skills

Slash commands. Invoked as `/<name>` (Claude Code) or `#<name>` (Codex/Cursor/Gemini).

| Slug | Procedure | Use when |
|------|-----------|----------|
| `quick-fix` | [`skills/quick-fix/SKILL.md`](../skills/quick-fix/SKILL.md) | Tiny bug fix or typo — minimal ceremony, single-file scope |
| `cli-command-add` | [`skills/cli-command-add/SKILL.md`](../skills/cli-command-add/SKILL.md) | Adding a new top-level or subgroup CLI command end-to-end |
| `endpoint-add` | [`skills/endpoint-add/SKILL.md`](../skills/endpoint-add/SKILL.md) | Wiring a new Dailybot API endpoint into `api_client.py` and a command |
| `release-prep` | [`skills/release-prep/SKILL.md`](../skills/release-prep/SKILL.md) | Pre-tag checklist + version bump for cutting a release |
| `dependency-add` | [`skills/dependency-add/SKILL.md`](../skills/dependency-add/SKILL.md) | Adding a Python dep (pyproject + Homebrew formula sync) |
| `doc-edit` | [`skills/doc-edit/SKILL.md`](../skills/doc-edit/SKILL.md) | Updating docs without touching code |


### Dailybot agent skill pack (vendored from [`DailybotHQ/agent-skill`](https://github.com/DailybotHQ/agent-skill))

The full pack lives under [`.agents/skills/dailybot/`](../skills/dailybot/) (router + fourteen sub-skills; vendored at **v3.11.0**). Every sub-skill requires `dailybot-cli >= 3.8.0` — the pack baseline. The router auto-routes by intent — read [`skills/dailybot/SKILL.md`](../skills/dailybot/SKILL.md) and let it pick the right sub-skill. Direct sub-skill entry points:

| Slug | Procedure | Use when |
|------|-----------|----------|
| `dailybot-report` | [`skills/dailybot/report/SKILL.md`](../skills/dailybot/report/SKILL.md) | Reporting agent progress through the CLI itself (replaces the legacy `dailybot-progress-report` skill) |
| `dailybot-messages` | [`skills/dailybot/messages/SKILL.md`](../skills/dailybot/messages/SKILL.md) | Polling for instructions sent to this agent by teammates |
| `dailybot-health` | [`skills/dailybot/health/SKILL.md`](../skills/dailybot/health/SKILL.md) | Announcing online/offline status on long sessions |
| `dailybot-email` | [`skills/dailybot/email/SKILL.md`](../skills/dailybot/email/SKILL.md) | Sending email on the agent's behalf (with mandatory pre-send safety checks) |
| `dailybot-checkin` | [`skills/dailybot/checkin/SKILL.md`](../skills/dailybot/checkin/SKILL.md) | Listing/completing check-ins + authoring (create/config/archive + questions) |
| `dailybot-kudos` | [`skills/dailybot/kudos/SKILL.md`](../skills/dailybot/kudos/SKILL.md) | Giving kudos to a teammate or a whole team |
| `dailybot-teams` | [`skills/dailybot/teams/SKILL.md`](../skills/dailybot/teams/SKILL.md) | Listing / resolving teams (the resolver `dailybot-kudos` and `dailybot-chat` delegate to) |
| `dailybot-forms` | [`skills/dailybot/forms/SKILL.md`](../skills/dailybot/forms/SKILL.md) | Listing/submitting/updating/transitioning responses + authoring (create/config/archive + questions) |
| `dailybot-channels` | [`skills/dailybot/channels/SKILL.md`](../skills/dailybot/channels/SKILL.md) | Discovering report-channel UUIDs for `--report-channel` |
| `dailybot-chat` | [`skills/dailybot/chat/SKILL.md`](../skills/dailybot/chat/SKILL.md) | Sending / editing Dailybot bot messages on Slack / Teams / Discord / Google Chat (DMs, channels, teams; report-style threads; in-place edits; `--send-as-user`/`--send-as-me` identity; interactive buttons with approval flows, workflow triggers, modals, callbacks) |
| `dailybot-conversation` | [`skills/dailybot/conversation/SKILL.md`](../skills/dailybot/conversation/SKILL.md) | Opening (or idempotently reusing) a Slack group DM with the bot + named teammates, then optionally posting a report (`conversation open -u … -m …`; Slack only, org-admin only) |
| `dailybot-ask` | [`skills/dailybot/ask/SKILL.md`](../skills/dailybot/ask/SKILL.md) | Asking the Dailybot AI a one-shot, headless question |
| `dailybot-workflow` | [`skills/dailybot/workflow/SKILL.md`](../skills/dailybot/workflow/SKILL.md) | Listing / reading / triggering org workflows — `workflow list` (incl. `--filter api_trigger`) / `workflow get` / `workflow trigger` (plan-gated) |
| `dailybot-env` | [`skills/dailybot/env/SKILL.md`](../skills/dailybot/env/SKILL.md) | Managing per-repo API keys in the opt-in, gitignored `.dailybot/env.json` (`env add/use/show/list/remove/off/on`) — be "logged into different orgs in different repos" |

### Deep Work Plan skill pack (vendored from [`DailybotHQ/deepworkplan-skill`](https://github.com/DailybotHQ/deepworkplan-skill))

The full pack lives under [`.agents/skills/deepworkplan/`](../skills/deepworkplan/) (router + 8 sub-skills + addons). Vendored at **v2.17.0**. The router auto-routes by intent — read [`skills/deepworkplan/SKILL.md`](../skills/deepworkplan/SKILL.md) and let it pick the right sub-skill. Each sub-skill is independently invocable, and each has a short `dwp-*` alias in [`.agents/commands/`](../commands/) for ergonomic typing.

| Slug | Procedure | Use when |
|------|-----------|----------|
| `deepworkplan-create` (`/dwp-create`) | [`skills/deepworkplan/create/SKILL.md`](../skills/deepworkplan/create/SKILL.md) | Decomposing a goal into a structured plan with per-task validation gates |
| `deepworkplan-execute` (`/dwp-execute`) | [`skills/deepworkplan/execute/SKILL.md`](../skills/deepworkplan/execute/SKILL.md) | Executing the current plan task-by-task |
| `deepworkplan-refine` (`/dwp-refine`) | [`skills/deepworkplan/refine/SKILL.md`](../skills/deepworkplan/refine/SKILL.md) | Adding / removing / reordering tasks without losing completed work |
| `deepworkplan-resume` (`/dwp-resume`) | [`skills/deepworkplan/resume/SKILL.md`](../skills/deepworkplan/resume/SKILL.md) | Picking up an interrupted plan from `.dwp/` state |
| `deepworkplan-status` (`/dwp-status`) | [`skills/deepworkplan/status/SKILL.md`](../skills/deepworkplan/status/SKILL.md) | Reporting plan progress at any time without making changes |
| `deepworkplan-verify` (`/dwp-verify`) | [`skills/deepworkplan/verify/SKILL.md`](../skills/deepworkplan/verify/SKILL.md) | Objective CONFORMANT / NOT CONFORMANT check against the [DWP spec](https://deepworkplan.com/spec) |
| `deepworkplan-onboard` | [`skills/deepworkplan/onboard/SKILL.md`](../skills/deepworkplan/onboard/SKILL.md) | Re-running the onboard flow as a reconciliation pass (non-destructive) |
| `skill-create` | [`skills/deepworkplan/author/SKILL.md`](../skills/deepworkplan/author/SKILL.md) | Creating a new skill in `.agents/skills/<slug>/` |
| `agent-create` | [`skills/deepworkplan/author/SKILL.md`](../skills/deepworkplan/author/SKILL.md) | Creating a new agent persona in `.agents/agents/<slug>.md` |
| `design-system` | [`skills/deepworkplan/addons/design-system/SKILL.md`](../skills/deepworkplan/addons/design-system/SKILL.md) | Refreshing [`docs/DESIGN.md`](../../docs/DESIGN.md) from the real design source (`display.py` + `DISPLAY_OUTPUT_BEST_PRACTICES.md`) — the `cli-output` profile of the DWP design-system addon |
| `ai-diff-reviewer` (addon) | [`skills/deepworkplan/addons/ai-diff-reviewer/SKILL.md`](../skills/deepworkplan/addons/ai-diff-reviewer/SKILL.md) | Opt-in DWP addon — wires Security Review to the vendored AI Diff Reviewer (Flow B: local + CI). See also the installed skill below. |

### AI Diff Reviewer (vendored from [`DailybotHQ/ai-diff-reviewer`](https://github.com/DailybotHQ/ai-diff-reviewer))

Vendored at **v2.0.0** under [`.agents/skills/ai-diff-reviewer/`](../skills/ai-diff-reviewer/). Flow B is enabled: local Security Review augmentation + CI gate via [`.github/workflows/pr-review.yml`](../../.github/workflows/pr-review.yml) (trigger label **`Ready`**; secret `CURSOR_API_KEY`; extension [`.review/extension.md`](../../.review/extension.md)).

| Slug | Procedure | Use when |
|------|-----------|----------|
| `ai-diff-reviewer` | [`skills/ai-diff-reviewer/SKILL.md`](../skills/ai-diff-reviewer/SKILL.md) | Running a local review on the current branch ("Review my current branch") |
| `ai-diff-reviewer-generate-extension` | [`skills/ai-diff-reviewer/generate-extension/SKILL.md`](../skills/ai-diff-reviewer/generate-extension/SKILL.md) | Regenerating [`.review/extension.md`](../../.review/extension.md) from repo evidence |
| `ai-diff-reviewer-setup` | [`skills/ai-diff-reviewer/setup/SKILL.md`](../skills/ai-diff-reviewer/setup/SKILL.md) | Re-running the CI workflow wizard |
| `ai-diff-reviewer-open-pr` | [`skills/ai-diff-reviewer/open-pr/SKILL.md`](../skills/ai-diff-reviewer/open-pr/SKILL.md) | Drafting a PR title/body from the branch diff |
| `ai-diff-reviewer-apply-review` | [`skills/ai-diff-reviewer/apply-review/SKILL.md`](../skills/ai-diff-reviewer/apply-review/SKILL.md) | Walking CI-posted findings per-finding (apply / defer / skip) |

Plans and drafts persist under [`.dwp/`](../../.dwp/) which is gitignored — only the `plans/.gitkeep` and `drafts/.gitkeep` placeholders are tracked. Full command catalog in [`COMMANDS_REFERENCE.md`](COMMANDS_REFERENCE.md), and the rationale in [`../../AGENTS.md`](../../AGENTS.md) "Working with Deep Work Plans".

## Agents

Persona definitions. Use these as the system prompt / role when spawning a sub-agent or asking the user to "act as".

| Slug | Persona | When to use |
|------|---------|-------------|
| `cli-developer` | [`agents/cli-developer.md`](../agents/cli-developer.md) | Default persona for feature work in this repo |
| `release-manager` | [`agents/release-manager.md`](../agents/release-manager.md) | Cutting a release; the only persona that should bump the version + push tags |
| `test-engineer` | [`agents/test-engineer.md`](../agents/test-engineer.md) | Pure test work — adding coverage, fixing flakes |
| `docs-writer` | [`agents/docs-writer.md`](../agents/docs-writer.md) | Doc-only changes; will not touch source code |

## Quick-Reference Decision Table

| You want to… | Skill | Agent |
|--------------|-------|-------|
| Fix a typo or one-line bug | `quick-fix` | `cli-developer` |
| Add a new `dailybot foo` command | `cli-command-add` | `cli-developer` |
| Add `client.do_thing` for a new endpoint | `endpoint-add` | `cli-developer` |
| Add a missing test | (none — just do it) | `test-engineer` |
| Update README / docs only | `doc-edit` | `docs-writer` |
| Add `httpx-retries` to deps | `dependency-add` | `cli-developer` |
| Cut v0.4.13 | `release-prep` | `release-manager` |
| Plan a non-trivial multi-step change | `/dwp-create` then `/dwp-execute` | `cli-developer` |
| Pick up a plan after an interrupted session | `/dwp-resume` | `cli-developer` |
| Check repo conformance against the DWP spec | `/dwp-verify` | (any) |
| Create a new repo-specific skill or persona | `/skill-create` or `/agent-create` | (any) |
| Report what you just shipped | `dailybot-report` | (any) |
| Send a Slack/Teams/Discord/Google Chat message (DM, channel, team; report-style threads) | `dailybot-chat` | (any) |
| Open (or reuse) a Slack group DM with the bot + teammates and post a report | `dailybot-conversation` | (any) |
| Recognize a teammate or a whole team | `dailybot-kudos` | (any) |
| Complete a pending check-in / standup | `dailybot-checkin` | (any) |
| Create / configure a check-in or form (author) | `dailybot-checkin` / `dailybot-forms` | (any) |
| Submit / transition / update a form response | `dailybot-forms` | (any) |
| Find a report-channel UUID for authoring | `dailybot-channels` | (any) |

## Conventions

- Skills are **procedural** — they describe steps to take. They never modify files themselves; they tell an agent what to modify.
- Agents are **dispositional** — they describe how to think about the work. They're combined with skills for actual execution.
- An agent without a skill is fine for free-form work. A skill without a matching agent is fine — pick the closest persona.

## When in Doubt

- Don't see a skill that matches? Don't invent one. Do the work directly and tell the user what you did.
- Don't see a persona that matches? Default to `cli-developer`.
