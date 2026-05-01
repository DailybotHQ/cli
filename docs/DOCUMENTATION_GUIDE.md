# Documentation Guide

How to keep `AGENTS.md`, `README.md`, and `docs/` in sync.

## The Three-File Split

Each documentation surface owns a specific scope. Don't duplicate content across them — link instead.

| File | Audience | Owns |
|------|----------|------|
| [`README.md`](../README.md) | End users (humans + agent operators) | What the CLI is, how to install, how to use each command (worked examples) |
| [`AGENTS.md`](../AGENTS.md) | AI agents working on the code | Mandatory rules, project structure, common mistakes, navigation pointers |
| [`docs/`](README.md) | Anyone who needs deeper reference | Architecture, contracts, conventions, runbooks |

When you add or change something, update the file whose scope owns it. If a piece of info is genuinely needed in two places, write it once in `docs/` and link from the other two.

## When to Update Which

| Change | Update |
|--------|--------|
| New CLI command/flag | `README.md` (Commands table + worked example), `docs/API_REFERENCE.md`, the relevant test |
| New mandatory rule for agents | `AGENTS.md`, `docs/STANDARDS.md` (deeper version) |
| New module file | `docs/ARCHITECTURE.md` (Module Responsibilities section) |
| New on-disk file | `docs/CONFIGURATION.md`, `docs/SECURITY.md` (if it has secrets) |
| New dependency | `pyproject.toml`, Homebrew formula in `release.yml`, `docs/RELEASE_AND_DISTRIBUTION.md` |
| New display helper | `docs/DISPLAY_OUTPUT_BEST_PRACTICES.md` |
| New testing pattern | `docs/TESTING_GUIDE.md` |
| Public API change | `README.md`, `docs/API_REFERENCE.md`, version bump (`pyproject.toml`) |
| Internal-only refactor | Maybe `docs/ARCHITECTURE.md` if module boundaries shifted; otherwise nothing |

## Tone & Style

- **Direct.** Imperative voice for instructions ("Run `pytest`", not "You can run `pytest`").
- **Specific.** Name files, functions, line numbers when describing where something lives.
- **Code-first.** Show the canonical snippet before describing it. Readers skim.
- **No marketing.** This is internal documentation; assume the reader already chose to use the CLI.
- **No filler.** "It is important to note that…" → just write the note.

## Markdown Conventions

- Top-level title: `# Foo` (one per file).
- Section headings: `##`.
- Nested subsections: `###`. Avoid `####` and below.
- Tables for structured comparison.
- Fenced code blocks (` ```bash `, ` ```python `, etc.) — always specify language.
- Internal links: relative paths (`[CONFIGURATION.md](CONFIGURATION.md)`).
- External links: full URL.
- Inline code: `` `dailybot agent update` ``, `` `~/.config/dailybot/` ``.
- File path references in prose: backticked.
- Avoid emojis unless the file is end-user-facing (and even then, sparingly — consistency with `README.md` only when it already uses them).

## Diagrams

ASCII-art is preferred over Mermaid in this repo — every reader's terminal renders it identically, no MIME tooling required. See `docs/ARCHITECTURE.md` and `docs/ECOSYSTEM_CONTEXT.md` for examples.

If a diagram is unavoidably visual (e.g., a complex state machine), use a Mermaid block fenced with ` ```mermaid `. GitHub renders it natively.

## Cross-Linking

Every doc should link to:

1. The next layer down (a doc closer to the code).
2. The next layer up (an index that points to it).

```
README.md (user-facing)
    └─ AGENTS.md (agent rules, links to docs/)
            └─ docs/README.md (index)
                    └─ docs/SPECIFIC_TOPIC.md (deep)
```

The index file [`docs/README.md`](README.md) lists every doc with a one-line "what's in here" hook.

## Versioning the Docs

Docs aren't versioned separately from the code — they live in the same repo and travel with it. When making a behavior-changing PR:

1. Update the relevant docs in the **same** PR.
2. The reviewer should fail the PR if a user-visible behavior change has no doc update.

## When to Create a New Doc vs Add a Section

Add a section if:
- The topic fits naturally within an existing doc.
- It's < 1 page of content.

Create a new doc if:
- It's > 1 page and a self-contained topic.
- It will be linked from multiple places (e.g., `RELEASE_AND_DISTRIBUTION.md` is referenced from the README, AGENTS.md, and pre-commit checklists).

Always update [`docs/README.md`](README.md) when adding a new doc.

## Checking Yourself

Before committing doc changes:

- [ ] All internal links resolve (use `grep -r '\[\([^]]*\)\](' docs/` and inspect)
- [ ] No duplicate content (same fact in two places)
- [ ] No marketing fluff ("comprehensive solution", "powerful platform")
- [ ] Code blocks have language tags
- [ ] Tables fit reasonably wide terminals (don't wrap visibly)
- [ ] If a behavior changed, the test for it changed in the same PR
