---
description: Read the CI review on the current PR and walk through findings (provided by the vendored `ai-diff-reviewer` skill)
---

# /ai-diff-reviewer-apply-review — provided by the `ai-diff-reviewer` skill

> Thin alias. The flow lives in the vendored `ai-diff-reviewer` skill — this
> file only routes to it, so there is a single source of truth and no drift.

## What to do

Route this invocation to the **apply-review** sub-skill of the vendored
`ai-diff-reviewer` skill and follow it: read
`.agents/skills/ai-diff-reviewer/apply-review/SKILL.md` and execute its flow
(anchor on the latest `<!-- ai-pr-reviewer-marker -->` comment, skip minimized
comments, per-finding apply / defer / skip consent; never commits or pushes).
This is the executable counterpart of `docs/PR_REVIEW_WORKFLOW.md`.

> Other agents: invoke the sub-skill directly
> (`#ai-diff-reviewer-apply-review` in Cursor/Codex/Gemini).
