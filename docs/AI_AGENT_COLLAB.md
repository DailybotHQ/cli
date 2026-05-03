# AI Agent Collaboration

How multiple AI assistants share state in this repo without stepping on each other.

## Configurations

| Agent | Config file | Behavior |
|-------|-------------|----------|
| Claude Code | `CLAUDE.md` (symlink to `AGENTS.md`) | Reads automatically on session start |
| Cursor AI | `.cursorrules` (if present) → falls back to `AGENTS.md` | Reads on session start |
| OpenAI Codex | `AGENTS.md` (universal) | Per-message context injection |
| Google Gemini | `AGENTS.md` (universal) | Per-message context injection |
| GitHub Copilot | `.github/copilot-instructions.md` (if present) → falls back to `AGENTS.md` | Auto-loaded |

`AGENTS.md` is the canonical source. The other config files (when added) should be **symlinks** to `AGENTS.md` or short pointers — not duplicate content.

## When Updating Shared Patterns

If you change a mandatory rule, idiom, or pattern, update **`AGENTS.md`** — that propagates to every agent. Do **not**:

- Add a rule to `.cursorrules` that isn't in `AGENTS.md`
- Add a rule to `CLAUDE.md` (it's a symlink — your edit goes to `AGENTS.md` anyway)
- Maintain parallel rule lists in `docs/`

## Skills & Personas

The `.agents/` folder hosts:

- `.agents/skills/` — slash-command procedures (e.g., `/quick-fix`, `/release-prep`)
- `.agents/agents/` — persona definitions (e.g., `cli-developer`, `release-manager`)
- `.agents/docs/skills_agents_catalog.md` — index of all of the above

These are Claude-Code-native but **most are agent-agnostic** — Codex/Cursor/Gemini users invoke them by typing `#<name>` or by referring to them in plain English.

When you're an agent invoked with `/<skill-name>` or `#<skill-name>`:

1. Look up the procedure file in `.agents/docs/skills_agents_catalog.md`.
2. **READ** the file completely.
3. **FOLLOW** its steps — do not improvise.

When in doubt, ask the user instead of inventing a procedure.

## Avoiding Conflicts

### Read git status before starting

```bash
git status -s
git log --oneline -5
```

Uncommitted changes mean another agent (or the user) is mid-flight. Ask before continuing.

### Use feature branches for non-trivial work

```bash
git checkout -b feat/<short-description>
```

Don't push directly to `main` unless the user explicitly asks. Multiple agents pushing to `main` simultaneously creates merge headaches.

### Don't auto-commit

Default to **proposing** the commit message and **showing** the diff. Only commit when the user explicitly asks. This keeps human review in the loop and prevents two agents from creating overlapping commits.

### Don't auto-tag releases

A release tag fans out into PyPI publishes, GitHub Releases, and a Homebrew tap update — all permanent. Always require an explicit user instruction before running `git tag v...` or `git push --tags`.

## Reporting Agent Activity

Every agent working in this repo MUST report progress through the CLI itself:

```bash
dailybot agent update --name "<your model>" \
  "<one-sentence description of what was accomplished>" \
  --metadata '{"model":"<your-model-id>","repo":"cli"}'
```

The metadata `model` field disambiguates which agent did what. If you're collaborating with another agent in the same session, you can credit it via `--co-authors`:

```bash
dailybot agent update --name "Claude Code" \
  "Refactored agent.py with Codex pairing." \
  --co-authors "openai-codex@dailybot.com" \
  --metadata '{"model":"claude-opus-4-7","repo":"cli"}'
```

See [`.agents/skills/dailybot-progress-report/SKILL.md`](../.agents/skills/dailybot-progress-report/SKILL.md) for the full reporting philosophy and what to skip.

## Handing Off Mid-Task

If you're an agent stopping work that another agent will pick up:

1. Make sure your local changes are committed (or staged with a clear note).
2. Update any plan / TodoList artifacts that the next agent will read.
3. Leave a one-paragraph "where I left off" comment in the relevant PR or issue.
4. Don't expect the next agent to know what you tried — record what failed.

## What Each Agent is Good At

(Heuristic, not gospel — pick whatever your user is paying for.)

| Need | Reasonable choice |
|------|-------------------|
| Heavy refactor across multiple files | Claude Opus, Codex GPT-5 |
| Quick targeted bug fix | Claude Sonnet, Codex GPT-4o |
| Documentation polish | Any frontier model |
| Tricky CI / build / packaging issue | Claude Opus (long context for logs) |
| Very fast inline edits in IDE | Cursor with whichever model the user has selected |

The repo doesn't enforce a model choice. Pick the cheapest tier that can plausibly do the job, and escalate only when you actually hit a wall.
