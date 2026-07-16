---
description: Regenerate `.review/extension.md` from repo evidence (provided by the vendored `ai-diff-reviewer` skill)
---

# /ai-diff-reviewer-generate-extension — provided by the `ai-diff-reviewer` skill

> Thin alias. The flow lives in the vendored `ai-diff-reviewer` skill — this
> file only routes to it, so there is a single source of truth and no drift.

## What to do

Route this invocation to the **generate-extension** sub-skill of the vendored
`ai-diff-reviewer` skill and follow it: read
`.agents/skills/ai-diff-reviewer/generate-extension/SKILL.md` and execute its
flow. The output lands in `.review/extension.md` — the same file CI's
`prompt-extension-file:` input reads, keeping local and CI reviews in parity.

> Other agents: invoke the sub-skill directly
> (`#ai-diff-reviewer-generate-extension` in Cursor/Codex/Gemini).
