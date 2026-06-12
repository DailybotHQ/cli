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

The full pack lives under [`.agents/skills/dailybot/`](../skills/dailybot/) (router + nine sub-skills). The router auto-routes by intent — read [`skills/dailybot/SKILL.md`](../skills/dailybot/SKILL.md) and let it pick the right sub-skill. Direct sub-skill entry points:

| Slug | Procedure | Use when |
|------|-----------|----------|
| `dailybot-report` | [`skills/dailybot/report/SKILL.md`](../skills/dailybot/report/SKILL.md) | Reporting agent progress through the CLI itself (replaces the legacy `dailybot-progress-report` skill) |
| `dailybot-messages` | [`skills/dailybot/messages/SKILL.md`](../skills/dailybot/messages/SKILL.md) | Polling for instructions sent to this agent by teammates |
| `dailybot-health` | [`skills/dailybot/health/SKILL.md`](../skills/dailybot/health/SKILL.md) | Announcing online/offline status on long sessions |
| `dailybot-email` | [`skills/dailybot/email/SKILL.md`](../skills/dailybot/email/SKILL.md) | Sending email on the agent's behalf (with mandatory pre-send safety checks) |
| `dailybot-checkin` | [`skills/dailybot/checkin/SKILL.md`](../skills/dailybot/checkin/SKILL.md) | Listing and completing pending check-ins (user-scoped) |
| `dailybot-kudos` | [`skills/dailybot/kudos/SKILL.md`](../skills/dailybot/kudos/SKILL.md) | Giving kudos to a teammate or a whole team |
| `dailybot-teams` | [`skills/dailybot/teams/SKILL.md`](../skills/dailybot/teams/SKILL.md) | Listing / resolving teams (the resolver `dailybot-kudos` and `dailybot-chat` delegate to) |
| `dailybot-forms` | [`skills/dailybot/forms/SKILL.md`](../skills/dailybot/forms/SKILL.md) | Listing, submitting, updating, or transitioning form responses |
| `dailybot-chat` | [`skills/dailybot/chat/SKILL.md`](../skills/dailybot/chat/SKILL.md) | Sending / editing Dailybot bot messages on Slack / Teams / Discord / Google Chat (DMs, channels, teams; report-style threads; in-place edits). Requires `dailybot-cli >= 1.13.0` |

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
| Report what you just shipped | `dailybot-report` | (any) |
| Send a Slack/Teams/Discord/Google Chat message (DM, channel, team; report-style threads) | `dailybot-chat` | (any) |
| Recognize a teammate or a whole team | `dailybot-kudos` | (any) |
| Complete a pending check-in / standup | `dailybot-checkin` | (any) |
| Submit / transition / update a form response | `dailybot-forms` | (any) |

## Conventions

- Skills are **procedural** — they describe steps to take. They never modify files themselves; they tell an agent what to modify.
- Agents are **dispositional** — they describe how to think about the work. They're combined with skills for actual execution.
- An agent without a skill is fine for free-form work. A skill without a matching agent is fine — pick the closest persona.

## When in Doubt

- Don't see a skill that matches? Don't invent one. Do the work directly and tell the user what you did.
- Don't see a persona that matches? Default to `cli-developer`.
