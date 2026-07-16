---
description: Re-run the AI Diff Reviewer CI workflow wizard (provided by the vendored `ai-diff-reviewer` skill)
---

# /ai-diff-reviewer-setup — provided by the `ai-diff-reviewer` skill

> Thin alias. The flow lives in the vendored `ai-diff-reviewer` skill — this
> file only routes to it, so there is a single source of truth and no drift.

## What to do

Route this invocation to the **setup** sub-skill of the vendored
`ai-diff-reviewer` skill and follow it: read
`.agents/skills/ai-diff-reviewer/setup/SKILL.md` and execute its flow. In this
repo the workflow already exists at `.github/workflows/pr-review.yml` (Flow B,
label-gated on `Ready`) — setup runs are reconfiguration passes, and
`.agents/skills/ai-diff-reviewer/setup/reference.md` doubles as the reference
manual for every `action.yml` input.

> Other agents: invoke the sub-skill directly (`#ai-diff-reviewer-setup` in
> Cursor/Codex/Gemini).
