---
description: Run a local AI review of the current branch's diff (provided by the vendored `ai-diff-reviewer` skill)
---

# /ai-diff-reviewer — provided by the `ai-diff-reviewer` skill

> Thin alias. The flow lives in the vendored `ai-diff-reviewer` skill — this
> file only routes to it, so there is a single source of truth and no drift.

## What to do

Route this invocation to the vendored `ai-diff-reviewer` skill's default
local-review flow: read `.agents/skills/ai-diff-reviewer/SKILL.md` and execute
it (diff vs `main`, base prompt + `.review/extension.md`, findings table in the
CI-parity format). This is the same methodology CI runs on `Ready`-labeled PRs
via `.github/workflows/pr-review.yml`.

> Other agents: invoke the skill directly (`#ai-diff-reviewer` in
> Cursor/Codex/Gemini).
