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
| `dailybot-progress-report` | [`skills/dailybot-progress-report/SKILL.md`](../skills/dailybot-progress-report/SKILL.md) | Reporting agent progress through the CLI itself |

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
| Report what you just shipped | `dailybot-progress-report` | (any) |

## Conventions

- Skills are **procedural** — they describe steps to take. They never modify files themselves; they tell an agent what to modify.
- Agents are **dispositional** — they describe how to think about the work. They're combined with skills for actual execution.
- An agent without a skill is fine for free-form work. A skill without a matching agent is fine — pick the closest persona.

## When in Doubt

- Don't see a skill that matches? Don't invent one. Do the work directly and tell the user what you did.
- Don't see a persona that matches? Default to `cli-developer`.
