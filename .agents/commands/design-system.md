---
name: design-system
description: Create or refresh this repo's DESIGN.md (semantic colors, components, voice, degradation rules — for AI agents; at docs/DESIGN.md, indexed from AGENTS.md) via the DeepWorkPlan design-system addon.
---

# /design-system

Create or refresh this repository's `DESIGN.md` (at [`docs/DESIGN.md`](../../docs/DESIGN.md), indexed from [`AGENTS.md`](../../AGENTS.md)) so coding agents generate terminal output consistent with this repo's **own** conventions. This command is a **thin delegator** to the DeepWorkPlan `deepworkplan-addon-design-system` addon — it does not contain the logic itself.

## Steps

1. Invoke the `deepworkplan-addon-design-system` addon (via `/deepworkplan-addon-design-system` or by reading the addon's `SKILL.md` at [`../skills/deepworkplan/addons/design-system/SKILL.md`](../skills/deepworkplan/addons/design-system/SKILL.md)).
2. Follow the addon's flow: locate this repo's real design source for the `cli-output` profile (the central display module at [`dailybot_cli/display.py`](../../dailybot_cli/display.py) — its `rich` semantic styles, the four `print_success` / `print_error` / `print_warning` / `print_info` primitives, the panel/table/spinner helpers, the `_mask` and `_format_sender` utilities — plus the operational rules already documented in [`docs/DISPLAY_OUTPUT_BEST_PRACTICES.md`](../../docs/DISPLAY_OUTPUT_BEST_PRACTICES.md)), reason out each canonical section of `DESIGN.md` from that source, and **reconcile** `DESIGN.md` at `docs/DESIGN.md` (append-only when adding a new profile; never clobber the existing `cli-output` content without asking).
3. Run the addon's validation step (SPEC §11): sections present for each accepted profile, every value traces to the real source (`display.py` / `DISPLAY_OUTPUT_BEST_PRACTICES.md`), per-profile integrity holds (degradation rules documented, `NO_COLOR` / TTY behavior captured, color never the sole carrier of meaning), `AGENTS.md` documentation index still references `DESIGN.md`, no sibling per-surface files were created.

## Notes

- **Profile present today:** `cli-output` only — the styled terminal interface owned by `dailybot_cli/display.py`.
- **`conversational` profile:** not adopted today. The product's outbound chat/email messaging conventions live in the vendored Dailybot agent skill pack ([`.agents/skills/dailybot/report/`](../skills/dailybot/report/), [`chat/`](../skills/dailybot/chat/), [`email/`](../skills/dailybot/email/)) plus `AGENTS.md` Rule 13 (brand-name spelling) and the "Agent Progress Reporting" section. If you decide to consolidate those into a `conversational` profile of `DESIGN.md` later, this addon supports it — the new profile would append as a new section to the existing file per the addon's `§4.1 Profile composition` rule (single `DESIGN.md`, never sibling per-surface files).
- **Integrity rules to enforce for `cli-output`:**
  - Errors must go to **stderr** (`print_error` does this — never bypass).
  - Color is never the only carrier of meaning — every semantic role pairs color with a textual prefix (`OK`, `Error:`, `Warning:`) or a structural cue.
  - `NO_COLOR` / non-TTY degradation is honored automatically by `rich`; do not work around it.
  - Secrets are always masked via `_mask` (4 chars + `****`) — never print a raw credential.
  - User-supplied content embedded in `rich` markup is always escaped (`\\[` — see `_format_sender`).
- **Reason about the real values** — read `display.py` for the actual `rich` markup strings, `border_style` choices, panel-vs-table decisions, and `console.status(...)` spinner-text catalogue. **Never paste a third-party CLI's `DESIGN.md`** (gh, ruff, uv, etc.) — reference catalogs are inspiration for structure only.
- **Reconcile, don't clobber.** When refreshing, preserve any working `DESIGN.md` content; only add missing canonical sections or update tokens that have drifted from the real source.
