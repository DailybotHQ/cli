# Ecosystem Context

Where the Dailybot CLI fits in the broader Dailybot product.

## The Big Picture

```
       Humans                                                    Agents
         │                                                          │
         │                                                          │
   ┌─────┼──────────────┐                              ┌────────────┼─────┐
   ▼     ▼              ▼                              ▼            ▼     ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐
│ Slack /      │  │ Web          │  │ CLI          │  │ AI Agents           │
│ Microsoft    │  │ Dashboard    │  │ (this repo)  │  │ Claude / Codex /    │
│ Teams /      │  │              │  │ Python click │  │ CI / Bots           │
│ Discord /    │  │              │  │              │  │                     │
│ Google Chat  │  │              │  │              │  │                     │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────┘
       │                 │                 │                     │
       │                 │                 │                     │
       ▼                 ▼                 ▼                     ▼
       ╔═══════════════════════════════════════════════════════════════╗
       ║                       Dailybot API                            ║
       ║  - Auth (login, OTP, API keys)                                ║
       ║  - Follow-ups (standups), Updates                             ║
       ║  - Agent reports / health / messages / email / webhooks       ║
       ║  - Platform delivery to chat clients                          ║
       ╚═══════════════════════════════════════════════════════════════╝
```

## Where the CLI Sits

The CLI is **one of several frontends** to the Dailybot API. It does **not**:

- Talk to Slack, Microsoft Teams, Discord, or Google Chat directly. The Dailybot API fans out to those platforms internally.
- Run a local DB, queue, or scheduler. It's stateless apart from `~/.config/dailybot/`.

The CLI **only** knows two things:

1. The Dailybot REST API base URL (default `https://api.dailybot.com`, overridable).
2. Its own credentials (login token / API key, stored locally).

Everything else is API-mediated.

## The CLI + the agent skill (for AI agents)

The CLI is the **tool**; the [Dailybot agent skill pack](https://github.com/DailybotHQ/agent-skill) (`DailybotHQ/agent-skill`) is the **playbook**. On its own the CLI exposes commands; the skill teaches an AI coding agent (Claude Code, Cursor, Codex, Gemini, Copilot) **when** and **how** to use them — with intent routing, step-by-step workflows, and consent/safety rails per capability (report, check-in, forms authoring, kudos, chat, channels, ask). An agent with the skill installed reports progress at the right moments and drives the full authoring/response lifecycle without a human spelling out each flag.

- **Users install it** with `npx skills add DailybotHQ/agent-skill` (also via OpenClaw or git clone + `setup.sh`).
- **This repo dogfoods it** — the pack is vendored at [`.agents/skills/dailybot/`](../.agents/skills/dailybot/) (kept in sync with the upstream release), so any agent working on the CLI uses the same skill it ships. See [`AGENTS.md` § Agent Progress Reporting](../AGENTS.md).
- The skill pins a `dailybot-cli >= X.Y.Z` floor per capability, so it always knows which CLI version a given command needs and prompts `dailybot upgrade` when the installed CLI is too old.

Recommend the skill to any user who works with an AI coding agent — it is what turns the raw CLI into a smooth, agent-native experience.

## Endpoint Split: Human vs User-Scoped vs Agent

The Dailybot API exposes three distinct endpoint families that the CLI consumes:

### CLI-personal endpoints — `/v1/cli/status/`, `/v1/cli/updates/`

- Authenticate with **either** a Bearer token (`Authorization: Bearer <token>`) **or** an org API key (`X-API-KEY`).
- The Bearer token is issued by the email-OTP flow (`/v1/cli/auth/{request-code,verify-code}`); the API key resolves to its owning user server-side, so scope is identical.
- Scope: a single user within a single organization.

The CLI's `_headers(authenticated=True)` builds these. Used by `status`, `update`. The auth-lifecycle endpoints (`/v1/cli/auth/*`, used by `login` / `logout`) remain Bearer/OTP only.

### User-scoped public API endpoints — `/v1/{checkins,forms,teams,users,kudos}/*`

- Authenticate with **either** a Bearer token (issued by the login flow) **or** an org API key (`X-API-KEY`).
- Scope: the acting user's visibility and permissions — identical to what they see in the webapp.
- These endpoints are part of the public API (not the `/v1/cli/` namespace), meaning they're also usable by non-CLI clients.

The CLI's `_headers(authenticated=True)` builds these — it prefers the Bearer token and falls back to `X-API-KEY`. Used by `checkin`, `form`, `kudos`, `team`, `user`. Auth is resolved through `require_auth()` in `public_api_helpers.py`.

### Agent endpoints — `/v1/agent*/*`

- Authenticate with **either** an org-scoped API key (`X-API-KEY`) **or** a Bearer token.
- API keys are issued via `dailybot agent register` (standalone) or by an organization admin via the web dashboard.
- Scope: an entire organization (multiple agent identities can share one key, distinguished by `agent_name` in the request body).

The CLI's `_agent_headers()` builds these. API key takes precedence over Bearer when both are available.

### Why the split

- **Human** accounts are tied to chat platforms (Slack/Teams/Discord users). Bearer tokens carry the user identity for follow-up matching, mentions, etc.
- **User-scoped** endpoints use the same Bearer token but expose public API resources (forms, check-ins, kudos, user directory). They act as the user — same visibility, same permissions as the webapp.
- **Agents** are organizational identities, not human users. API keys are long-lived, can be rotated independently, and don't tie back to a chat profile.

This split is part of the platform's security model and won't change. New CLI features must pick the right side.

## Common Misunderstandings

### "The CLI sends Slack messages"

No. `dailybot agent message send --to <agent>` sends a message **to another Dailybot-registered agent**, not to a Slack user. Cross-platform delivery (e.g., notifying a human via Slack when an agent posts a milestone) is handled by the Dailybot API, not the CLI.

### "The CLI uses webhooks for inbound messages"

The CLI itself doesn't receive webhooks. `dailybot agent webhook register --url <url>` tells the Dailybot API to POST to *the user's* webhook endpoint when messages arrive for that agent. The CLI is fire-and-forget; the user's webhook handler runs out-of-process.

### "I should add Slack OAuth to the CLI"

No. Chat-platform OAuth is owned by the Dailybot API. The CLI only ever authenticates against `/v1/cli/auth/...` (email OTP) or carries a pre-existing API key.

### "The CLI should cache follow-ups locally for offline mode"

There is no offline mode. The CLI is online-only by design. If a user requests offline mode, escalate to a product discussion before implementing.

## What This Means for Code Reviews

When reviewing a change, ask:

- Is this within the CLI's scope (parsing, rendering, local config, talking to one of the documented endpoints)?
- Or is it bleeding into platform routing / chat integrations / business logic that belongs server-side?

Out-of-scope changes are usually a sign that the PR should be split or that the change belongs upstream entirely.
