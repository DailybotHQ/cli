---
name: dailybot-progress-report
description: Report agent progress through the Dailybot CLI itself — Daily-Standup style, in English.
trigger: /dailybot-progress-report or #dailybot-progress-report (or simply "send a progress report")
inputs: Optional: a description of what was just accomplished. If omitted, infer from the recent git log.
prereqs: Significant work was just completed (see "When to Report" below).
---

# Skill: `dailybot-progress-report`

The recursive case: this CLI **is** the reporting tool. Use it to report progress on changes you just made — to this repo or any other.

## Philosophy

Reports reflect **what the human accomplished**, not "what an agent did." A person managing multiple agents is doing multiplied work. The standup-style update should sound like a human teammate giving an update — even if an agent typed it.

Apply the **Standup Test**: *"Would I say this in a real standup?"* If no, skip it.

## When to Report

Send a report when one of these happened:

- **Feature implemented** — new command, new flag, user-facing functionality.
- **Bug fixed** — user-visible issue resolved.
- **Major refactor completed** — changes a public surface (auth flow, output shape, config schema).
- **Multi-task plan completed** — a full DWP plan executed. **MANDATORY**: use `--milestone` + `--json-data` + `--metadata`.
- **Deployment / release** — a new version was tagged and published. **Use `--milestone`.**
- **3+ related commits** building one feature.

## When NOT to Report

- Single trivial commit (typo, rename, comment).
- Reading/exploring without making changes.
- Failed attempts that were rolled back.
- Lockfile / dependency / formatting updates with no behavior change.
- Uncommitted WIP (work isn't done until it's committed).
- Already reported in the last 30 minutes.
- Generic / vague reports — "Made changes", "Did some work" — silence > noise.

## Key Rules

- **1–3 sentences**, ALWAYS in English (regardless of conversation language).
- Focus on **WHAT was accomplished** and **WHY it matters**.
- Never say "Agent completed…" — describe the outcome directly.
- Never include file paths, git stats, branch names, or raw commit messages.
- Always pass `--metadata '{"model":"<your-model>","repo":"cli"}'` — you know your model from your system prompt.
- Send **after committing, before finishing your response** — it's part of completing the work, not an afterthought.

## How to Send

### Feature or bug fix (plain text)

```bash
dailybot agent update --name "Claude Code" \
  "Added --co-authors to dailybot agent update — agents can now credit collaborators on a single report." \
  --metadata '{"model":"claude-opus-4-7","repo":"cli"}'
```

### Multi-task plan completion (MANDATORY structured)

```bash
dailybot agent update --name "Claude Code" --milestone \
  "Built the agent profiles system — named profiles persist auth and default to a slugified agent name across all commands." \
  --json-data '{
    "completed": ["agents.json schema", "configure subcommand", "profile resolution order", "18 test cases"],
    "in_progress": [],
    "blockers": []
  }' \
  --metadata '{"model":"claude-opus-4-7","plan":"PLAN_agent_profiles","repo":"cli"}'
```

### Deployment / release (use `--milestone`)

```bash
dailybot agent update --name "Claude Code" --milestone \
  "Cut v0.4.13 — Linux binary now skips download on aarch64 and falls back to pip cleanly." \
  --metadata '{"model":"claude-opus-4-7","repo":"cli","version":"0.4.13"}'
```

### Pair work (credit collaborators)

```bash
dailybot agent update --name "Claude Code" \
  "Refactored the auth resolution order with Codex pairing." \
  --co-authors "openai-codex@dailybot.com" \
  --metadata '{"model":"claude-opus-4-7","repo":"cli"}'
```

## Anti-patterns

| Anti-pattern | Why |
|--------------|-----|
| `"Completed deep work plan PLAN_xyz"` | Process-focused. Describe the OUTCOME. |
| `"Updated commands/agent.py and tests/commands_test.py"` | File paths. Describe the BEHAVIOR. |
| `"Agent completed the work"` | Phrase the human did the work. |
| `"feat(agent): add --co-authors flag"` | That's a commit message, not a report. |
| 10 reports in 5 minutes | One rich report per significant chunk of work. |

## What If Reporting Fails?

Reporting must NEVER block your work. If the CLI isn't authenticated:

1. **Don't block.** Tell the user once: "Dailybot CLI isn't authenticated; skipping the progress report. To enable: `dailybot login` or set `DAILYBOT_API_KEY`."
2. **Continue with the actual work.**

If the CLI is authenticated but the call fails (network, 5xx), log it briefly and move on.

## Bootstrap (first session)

If this is the first time you're reporting in a session:

```bash
dailybot status --auth
```

If that succeeds, you're good. If not, the user needs to run `dailybot login` (interactively) or set `DAILYBOT_API_KEY` (in CI). Surface that and continue.
