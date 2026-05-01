# `.claude/` — Skills, Agents, and Procedures for the Dailybot CLI

This directory hosts AI-agent-specific assets for working on the Dailybot CLI:

- [`skills/`](skills/) — slash-command procedures (`/quick-fix`, `/release-prep`, etc.)
- [`agents/`](agents/) — agent persona definitions (`cli-developer`, `release-manager`, etc.)
- [`docs/skills_agents_catalog.md`](docs/skills_agents_catalog.md) — the index of everything below

> Although the folder is named `.claude/`, the procedures here apply to **any AI agent** (Cursor, Codex, Gemini, Copilot). Claude Code reads `/<skill-name>` natively; other agents invoke the same procedure via `#<skill-name>` or by referring to the skill in plain English.

## How to Invoke

| Agent | Prefix | Example |
|-------|--------|---------|
| Claude Code | `/` (native) | `/quick-fix` |
| OpenAI Codex / Cursor / Gemini | `#` | `#quick-fix` |

When invoked:

1. Look up the procedure file in [`docs/skills_agents_catalog.md`](docs/skills_agents_catalog.md).
2. **READ** the file completely.
3. **FOLLOW** its steps verbatim — do not improvise.
4. If a step is ambiguous or contradicts the current repo state, ask the user before proceeding.

## Conventions

- **Skill files** live in `skills/<slug>/SKILL.md` (one folder per skill, matching slug used at invocation time).
- **Agent files** live in `agents/<slug>.md` (one file per persona).
- **Skill front matter** declares the trigger phrase, expected inputs, and any prerequisites.
- **Agent front matter** declares the persona's scope, defaults, and model tier.

## Adding a New Skill or Agent

1. Add the file under `skills/` or `agents/`.
2. Update [`docs/skills_agents_catalog.md`](docs/skills_agents_catalog.md) with a one-line entry.
3. Cross-reference from `AGENTS.md` if the skill is mandatory or commonly used.
4. Test it: invoke `/<name>` (or `#<name>`) in a session and walk through the procedure end to end.
