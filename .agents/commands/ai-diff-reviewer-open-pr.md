---
description: Draft the PR title + body from the current branch's diff (provided by the vendored `ai-diff-reviewer` skill)
---

# /ai-diff-reviewer-open-pr — provided by the `ai-diff-reviewer` skill

> Thin alias. The flow lives in the vendored `ai-diff-reviewer` skill — this
> file only routes to it, so there is a single source of truth and no drift.

## What to do

Route this invocation to the **open-pr** sub-skill of the vendored
`ai-diff-reviewer` skill and follow it: read
`.agents/skills/ai-diff-reviewer/open-pr/SKILL.md` and execute its flow
(Conventional-Commits title inference, structured body, `gh pr create`/`edit`).
Remember this repo's rule: every change ships through a branch + PR — never a
direct push to `main`.

> Other agents: invoke the sub-skill directly (`#ai-diff-reviewer-open-pr` in
> Cursor/Codex/Gemini).
