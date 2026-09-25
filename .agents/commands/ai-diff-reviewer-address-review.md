---
description: Resolve the CI review findings, commit, push and re-arm the reviewer in one invocation (provided by the vendored `ai-diff-reviewer` skill)
---

# /ai-diff-reviewer-address-review — provided by the `ai-diff-reviewer` skill

> Thin alias. The flow lives in the vendored `ai-diff-reviewer` skill — this
> file only routes to it, so there is a single source of truth and no drift.

## What to do

Route this invocation to the **address-review** sub-skill of the vendored
`ai-diff-reviewer` skill and follow it: read
`.agents/skills/ai-diff-reviewer/address-review/SKILL.md` and execute its flow
(wait for a review fresh for the current head, present the findings with an
apply / defer / skip plan, then — on one explicit yes — apply, commit, push
and re-arm the reviewer). In this repo the CI review is label-gated, so
re-arming means removing and re-applying the **`Ready`** label. Unlike
`/ai-diff-reviewer-apply-review`, this flow commits and pushes: it never
pushes to `main` (feature branches only — AGENTS.md "Common Mistakes" #22).

> Other agents: invoke the sub-skill directly
> (`#ai-diff-reviewer-address-review` in Cursor/Codex/Gemini).
