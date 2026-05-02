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

## Endpoint Split: Human vs Agent

The Dailybot API exposes two distinct endpoint families that the CLI consumes:

### Human endpoints — `/v1/cli/*`

- Authenticate exclusively with a **Bearer token** (`Authorization: Bearer <token>`).
- Issued by the email-OTP flow (`/v1/cli/auth/{request-code,verify-code}`).
- Scope: a single user within a single organization (the `organization_id` is implicit in the token).

The CLI's `_headers(authenticated=True)` builds these.

### Agent endpoints — `/v1/agent*/*`

- Authenticate with **either** an org-scoped API key (`X-API-KEY`) **or** a Bearer token.
- API keys are issued via `dailybot agent register` (standalone) or by an organization admin via the web dashboard.
- Scope: an entire organization (multiple agent identities can share one key, distinguished by `agent_name` in the request body).

The CLI's `_agent_headers()` builds these. API key takes precedence over Bearer when both are available.

### Why the split

- Human accounts are tied to chat platforms (Slack/Teams/Discord users). Bearer tokens carry the user identity for follow-up matching, mentions, etc.
- Agents are organizational identities, not human users. API keys are long-lived, can be rotated independently, and don't tie back to a chat profile.

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
