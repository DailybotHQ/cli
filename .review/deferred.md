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

## PR #138 — CLI satellites through devcontainer-kit (review of `ff9067b`)

The six findings below are in `dev.sh`, which this repository keeps as a
**byte-identical copy of the Core Hub's `dev.sh`** (the hub's
`scripts/dev-stack-drift-check.sh` fails when any repository's copy drifts;
`scripts/dev-stack-sync.sh` re-syncs it). Editing it here would be erased by
the next sync, so the fix belongs in the hub's `dev.sh`; the next
`dev-stack-sync` brings it to this repository. `#5` is the reviewer's
unverified claim (`herdr-peers list --json` emits `n` as an integer today).

| Fingerprint | Severity | Location | Finding |
|---|---|---|---|
| `7006e753afe134f3` | warning | `dev.sh:1336` (`mesh_default_scope`) | Mac kept in scope only when `target == "dailybot-mac"`; `host_alias` also accepts `dck-host`, docs name the label `0 - Mac`. |
| `9c6c1bdf902178b8` | warning | `dev.sh:1558` (`cmd_herdr_peers`) | `notify` / `peers ask` exec `herdr-peers` without the `HERDR_PEERS_SCOPE` that `ask` exports. |
| `a12e4c35ad19bd29` | warning | `dev.sh:1310` (`mesh_check_self`) | `grep -q "\"${id}\""` on the raw `herdr machine list --json` is a substring match; parse the JSON and compare ids. |
| `79ff4ee83a2f2cd5` | warning (unverified) | `dev.sh:1456` (`mesh_resolve_number`) | `row.get("n") == want` breaks if `n` is ever emitted as a string. |
| `efc53666fb7104c1` | warning | `dev.sh:1339` (`mesh_default_scope`) | Empty `DAILYBOT_WORKSPACE_ID` applies the primary filter on a `… · WS <id>`-labelled satellite (`docker/local/docker.sh` `satellite_label` default). |
| `b865f480aa5b4ad5` | info | `dev.sh:1486` (`cmd_herdr_ask`) | The `ask` flag allowlist drops boolean herdr-peers flags such as `--trust-cwd`. |
