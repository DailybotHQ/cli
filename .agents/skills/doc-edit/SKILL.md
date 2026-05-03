---
name: doc-edit
description: Update docs (README, AGENTS.md, docs/*) without touching source code.
trigger: /doc-edit or #doc-edit
inputs: A description of what's wrong with the docs and what should change.
prereqs: None.
---

# Skill: `doc-edit`

For doc-only changes — the kind that should never accidentally touch a `.py` file.

## When to use

- A doc has stale content (a flag was renamed but the doc still references the old name).
- A doc is missing a worked example.
- A doc has a typo, broken link, or formatting issue.
- A new mandatory rule needs to be added to `AGENTS.md`.

## When NOT to use

- The doc is wrong because the **code** is wrong (e.g., the doc accurately describes a bug). Use `quick-fix` and update the doc as part of the fix.
- The doc is missing because a feature was added without docs. Re-open that PR and add the docs there.

## Procedure

### 1. Find every place the affected content lives

The Dailybot CLI has four documentation surfaces. Grep across all of them:

```bash
grep -r "<phrase>" README.md AGENTS.md CLAUDE.md docs/ .claude/
```

If the same fact appears in multiple places, decide which one **owns** it (per [docs/DOCUMENTATION_GUIDE.md](../../../docs/DOCUMENTATION_GUIDE.md)):

- End-user usage → `README.md`
- Mandatory agent rule → `AGENTS.md`
- Deep reference → `docs/`

The other surfaces should **link** to the owner, not duplicate.

### 2. Edit

Use `Edit` (preferred) or `Write` for new docs. Keep changes minimal — don't reformat the surrounding markdown if you can help it.

### 3. Verify links and code blocks

For any internal link you added or changed:

```bash
ls path/to/linked/file.md   # confirm it exists
```

For any code block:

- Confirm the language tag is correct (` ```bash `, ` ```python `).
- Confirm the snippet still runs as written. Don't paste pseudocode.

### 4. Verify cross-references

If you changed a heading in a doc that's linked from elsewhere with `#anchor`, update the anchors:

```bash
grep -r "FILE.md#" docs/ AGENTS.md README.md
```

### 5. Commit

```
docs(<scope>): <one-line description>
```

Scope: `agents` (for `AGENTS.md`), `readme`, `docs` (for everything else).

## Don'ts

- Don't reformat unrelated paragraphs while fixing a typo.
- Don't add emojis unless the doc already uses them (the README is the only one that does, sparingly).
- Don't add headings that don't fit the existing structure — match the parent doc's heading levels.
- Don't add a CHANGELOG / "what changed" section to existing docs. Release notes are auto-generated.
- Don't introduce duplicate content. If the same paragraph belongs in two docs, write it once and link.

## Example

User: "The `--profile` flag isn't documented in the AGENTS.md auth resolution order."

```
1. grep -r "Auth Resolution Order" AGENTS.md docs/
2. Confirm it's in AGENTS.md (Mandatory Rules → 14) and docs/CONFIGURATION.md (Auth Resolution Order).
3. AGENTS.md is the agent rules surface; docs/CONFIGURATION.md is the deep reference. Both already mention --profile correctly. The user may have read an older version.
4. If the docs are correct, surface that to the user with a quote. Don't make spurious "improvements."
```
