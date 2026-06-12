# Dailybot CLI — Documentation Index

> **Start here.** This folder contains the deep documentation for AI agents and developers working on the Dailybot CLI. The high-level overview, mandatory rules, and quick navigation live in [`../AGENTS.md`](../AGENTS.md).

## Reading Order for New Contributors

1. [`../AGENTS.md`](../AGENTS.md) — agent rules, structure, mandatory rules, common mistakes
2. [`AI_AGENT_ONBOARDING.md`](AI_AGENT_ONBOARDING.md) — environment setup, first-task checklist
3. [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) — what the CLI does and who uses it
4. [`ARCHITECTURE.md`](ARCHITECTURE.md) — modules, layers, control flow
5. [`API_REFERENCE.md`](API_REFERENCE.md) — every command, every endpoint, every flag
6. [`TESTING_GUIDE.md`](TESTING_GUIDE.md) — how to write and run tests
7. [`STANDARDS.md`](STANDARDS.md) — coding standards reference

## Documentation Map

### Product & Architecture

| Document | Purpose |
|----------|---------|
| [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | What the CLI is, target users, feature set |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module breakdown, layering, data flow, file responsibilities |
| [ECOSYSTEM_CONTEXT.md](ECOSYSTEM_CONTEXT.md) | How the CLI fits into the broader Dailybot ecosystem |

### Reference

| Document | Purpose |
|----------|---------|
| [API_REFERENCE.md](API_REFERENCE.md) | Every CLI command, flag, and Dailybot API endpoint |
| [CONFIGURATION.md](CONFIGURATION.md) | `~/.config/dailybot/` files, env vars, auth resolution order |
| [DEVELOPMENT_COMMANDS.md](DEVELOPMENT_COMMANDS.md) | Cheat sheet for `pip`, `pytest`, `pyinstaller`, etc. |

### Standards & Best Practices

| Document | Purpose |
|----------|---------|
| [STANDARDS.md](STANDARDS.md) | Repository-wide standards (imports, naming, formatting) |
| [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) | Python style: type hints, error handling, idioms |
| [CLI_COMMAND_BEST_PRACTICES.md](CLI_COMMAND_BEST_PRACTICES.md) | Click conventions, layering, error handling |
| [DISPLAY_OUTPUT_BEST_PRACTICES.md](DISPLAY_OUTPUT_BEST_PRACTICES.md) | `display.py` rules: stdout vs stderr, masking, panels |
| [DESIGN.md](DESIGN.md) | Terminal-output design system (semantic colors, components, voice, degradation) — the `cli-output` profile of the DWP design-system addon |
| [PERFORMANCE.md](PERFORMANCE.md) | Cold-start, HTTP, terminal-render, and hook budgets |
| [TESTING_GUIDE.md](TESTING_GUIDE.md) | pytest conventions, mocking patterns, CliRunner usage |
| [SECURITY.md](SECURITY.md) | Credential handling, file permissions, secret masking |
| [DOCUMENTATION_GUIDE.md](DOCUMENTATION_GUIDE.md) | How to keep docs/, AGENTS.md, and README.md in sync |

### Operations

| Document | Purpose |
|----------|---------|
| [RELEASE_AND_DISTRIBUTION.md](RELEASE_AND_DISTRIBUTION.md) | PyPI, Homebrew tap, Linux binary release flow |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common install / runtime / auth errors |
| [PR_REVIEW_WORKFLOW.md](PR_REVIEW_WORKFLOW.md) | Reading bot review comments without picking up stale feedback |

### Agent Collaboration

| Document | Purpose |
|----------|---------|
| [AI_AGENT_ONBOARDING.md](AI_AGENT_ONBOARDING.md) | First-session checklist for AI agents |
| [AI_AGENT_COLLAB.md](AI_AGENT_COLLAB.md) | How multiple AI agents share state and avoid stepping on each other |

## When To Update What

| You changed… | Also update… |
|--------------|--------------|
| A user-facing CLI flag | `README.md`, `API_REFERENCE.md`, the relevant test |
| A mandatory rule for agents | `AGENTS.md` (the single source of truth) and the test that enforces it |
| A new module / file | `ARCHITECTURE.md` and `AGENTS.md` "Project Structure" section |
| A new dependency | `pyproject.toml`, `RELEASE_AND_DISTRIBUTION.md`, `.github/workflows/release.yml` (Homebrew formula) |
| A new file in `~/.config/dailybot/` | `CONFIGURATION.md`, `SECURITY.md` |
| Release process | `RELEASE_AND_DISTRIBUTION.md`, `.github/workflows/release.yml`, `install.sh` |

> **Avoid duplicating content** between `AGENTS.md`, `README.md`, and `docs/`. Each owns a specific scope: `AGENTS.md` is for agent rules and pointers; `README.md` is for end-user CLI usage; `docs/` is for deep, internal reference.
