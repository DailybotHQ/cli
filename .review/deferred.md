# Deferred review findings

Findings from the AI Diff Reviewer that were deliberately not fixed in the PR
that raised them. Each entry names the review, the reason, and where the fix
belongs.

## PR #98 — AI Diff Reviewer v3.1.1 upgrade (review of `5f69aab`)

The three findings below are in the **vendored** skill under
`.agents/skills/ai-diff-reviewer/`, which is a byte-exact copy of the upstream
`v3.1.1` tag (upstream `main` carries the same text). Patching them here would
create local drift that the next `npx skills add` silently erases, so the fix
belongs upstream in `DailybotHQ/ai-diff-reviewer`; the next vendored sync picks
it up.

| Fingerprint | Severity | Location | Finding |
|---|---|---|---|
| `3ee1550c8b90177a` | warning | `SKILL.md:72` | Flow B row says "all five capabilities"; `address-review` makes six. |
| `ae386ace291c06db` | warning | `SKILL.md:141-143` | Install example says "Latest v2.x" and pins `@v3.1.0` instead of the shipped tag. |
| `f40ca4a86d98a74f` | info | `open-pr/SKILL.md:475` | Sample "Who is affected" line mixes `@v3` with `@v2.x`. |
