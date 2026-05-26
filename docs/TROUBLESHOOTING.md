# Troubleshooting

Common issues and how to fix them. If you hit something that isn't here, add it after you resolve it.

## Installation

### `dailybot: command not found` after `pip install -e .`

- Your virtualenv isn't activated. `which python3` should point inside `.venv/`. Run `source .venv/bin/activate`.
- You did `pip install --user -e .` and `~/.local/bin` isn't on PATH. Add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` / `~/.zshrc`.
- You used `pipx install -e .` and the pipx bin dir isn't on PATH. Run `pipx ensurepath`.

### `pip install -e .` fails with "metadata-generation-failed"

- Your `pip` is too old. Run `python3 -m pip install --upgrade pip`.
- Your `setuptools` is older than 68.0. Run `python3 -m pip install --upgrade setuptools wheel`.

### `dailybot --version` reports `0.0.0`

- The package metadata wasn't installed. You ran the source directly without `pip install -e .` — re-install.

### macOS: `brew install dailybothq/tap/dailybot` fails

- Run `brew tap dailybothq/tap` first, then `brew install dailybot`.
- If a previous formula version is broken (resource hash mismatch after a botched release), `brew untap dailybothq/tap && brew tap dailybothq/tap`.

### Linux binary won't run

- Output is `Illegal instruction` or similar → wrong CPU architecture. The binary is x86_64 only; on aarch64, fall back to `pipx install dailybot-cli`.
- Output mentions `GLIBC_2.XX not found` → your distro's glibc is older than 2.31. Use the pip install path instead.

## Authentication

### "Not logged in. Run: dailybot login"

- You haven't logged in yet, **or** `~/.config/dailybot/credentials.json` was cleared.
- For agent commands, you also haven't set `DAILYBOT_API_KEY` and don't have a profile.

### "Session expired. Run 'dailybot login' to re-authenticate."

- The Bearer token has expired. Re-run `dailybot login`.
- The API URL has changed (e.g., switched from prod to staging without re-authenticating). Tokens are URL-scoped — log in to the new URL.

### Login OTP never arrives

- Check spam.
- Check the email is correct (`dailybot login` shows it back to you on success of step 1).
- The mail server may be slow on first delivery. Wait 30–60s, retry.
- If you re-ran `request_code` (e.g., re-ran `dailybot login --email=...` instead of proceeding to step 2), the previous OTP was invalidated. Use the latest code.

### Multi-org login: "No cached organization list found"

You're running the non-interactive step 2 (`--code --org=<uuid>`) without having run step 1 (`--email` only) on the same machine. The org list is cached locally between the two steps. Run step 1 again, then step 2 with the OTP from the latest email.

### "API key is invalid or unauthorized."

- The key was revoked. Generate a new one (`dailybot agent register` or via the web app).
- The key was for a different environment (e.g., staging key tested against prod). Confirm `--api-url` / `DAILYBOT_API_URL`.

## Agent Commands

### "Profile 'X' not found. Run: dailybot agent profiles"

- The slug is misspelled. Run `dailybot agent profiles` to see exactly what's stored.
- The profile was created on a different machine; `agents.json` doesn't sync automatically. Run `dailybot agent configure` again.

### "Profile 'X' has no API key and no login session."

- The profile was configured without `--key` (so it relies on a Bearer token) and you've since logged out.
- Re-run `dailybot agent configure --name "X" --key <api-key>` or `dailybot login`.

### "Specify exactly one of --ok, --fail, or --status."

- You either passed multiple flags or none. Pick one.

### `agent register` fails with "expired"

- The math challenge has a short server-side TTL. The CLI auto-retries once with a fresh challenge, so seeing "expired" twice means something else is wrong (network instability, API outage). Check `https://status.dailybot.com` (if available) or retry in a minute.

### `agent register` returns 429

- Rate-limited. Wait ~5 minutes and retry. If you're testing, lower the rate by re-using an existing key and `dailybot agent configure --key ...` instead of registering anew each run.

### `agent email send` returns "Hourly email limit exceeded"

- Per-org hourly throttle. Wait an hour or rotate to a different agent profile if you have a higher-quota one configured.

## Forms & Workflow

### `dailybot form transition` → 403 / `form_response_change_state_forbidden`

- The form's `state_change_permission` audience excludes you. **There is no response-author short-circuit** — even on your own response, only users in the audience can transition. Ask the form owner to add you (or your team) to the audience, or to transition on your behalf.
- Inspect the response: `dailybot form response get <form_uuid> <resp_uuid>` and look at `can_change_state` (`false` means the server already told you).

### `dailybot form transition` → 403 / `final_state_locked`

- The response is in the workflow's **final state** and the form has `allow_reopen_from_final_state: false` (the default). Once `released` (or whatever the final state is), the response is sticky.
- Resolution: ask the form owner to enable reopening, or create a fresh response with `dailybot form submit`.

### `dailybot form update` → 404 / `form_response_not_found`

- The response UUID doesn't exist, **or** it belongs to another user. `update` is strict own-only; admins are *not* elevated to other users' responses on this endpoint (unlike `delete`).

### `dailybot form delete` → 403 / `form_response_delete_forbidden`

- You're not the response author, the form owner, or an org admin. No CLI workaround — ask one of them to delete it.

### `dailybot form responses --latest` returns nothing

- You haven't submitted a response on this form yet. The endpoint scopes by author server-side. `form list` shows all forms visible to you; `form responses` only shows responses you authored.

### My form response renders as one wall of text in the webapp

- The webapp renders Markdown. The CLI sends `--content` answers verbatim — if you submit `"line 1 line 2 line 3"`, that's what's stored. Embed real `\n` newlines (and Markdown `**bold**`, `# Heading`, `- bullet`, fenced code blocks, tables, etc.) inside each answer string. The CLI doesn't auto-format.

### Form-response Markdown: supported subset

The form-response webapp renders a **constrained Markdown subset**. When authoring `--content` for `form submit` / `form update`, stick to:

- **Single-level headings only** — use `# Heading`. **Do NOT use `##` or `###`** — only one title level is supported; nested heading levels render as plain text. To group sub-sections, use a `# Heading` followed by paragraphs / lists.
- **Real line breaks** — embed actual `\n` characters between paragraphs and list items. Two `\n` for a paragraph break, one `\n` between bullet rows. A single literal newline in a JSON string is `"\n"`.
- **Inline:** `**bold**`, `*italic*`, `` `code` ``, `[link](url)`.
- **Blocks:** `- bullet` lists, `1. numbered` lists, fenced ``` ```code``` ``` blocks, Markdown `|` tables.

Quick smoke-check from the CLI side after a `submit` / `update`:

```bash
dailybot form response get <form_uuid> <resp_uuid> --json | jq -r '.content[]' | head -20
```

If the printed output has real line breaks (not `\n` literals) and uses `#` rather than `##` / `###`, the webapp will render it correctly.

## Teams & Kudos

### `dailybot team list` shows fewer teams than I expect

- Visibility is **server-scoped by role**. Org admins see all org teams; members see only the teams they belong to (via `teammembership_set`). This is not a bug. If you should be in a team but aren't, ask an admin to add you — the CLI never client-filters.

### `dailybot kudos give --team "X"` → "No team named 'X' visible to you"

- The team either doesn't exist or you're not a member (and you're not an admin). Run `dailybot team list` to see exactly what the server returns for your role.

### Can I give kudos to my own team?

- Yes — the backend `kudos_manager` expands a team UUID into its active members and **excludes the caller**. So `kudos give --team "MyTeam"` where you belong to MyTeam is valid; you credit your teammates, not yourself.

### `kudos give` → 400 / `no_valid_users` or `no_valid_team`

- At least one of `--to` / `--team` must resolve to a valid receiver. Empty receiver lists are rejected server-side. Double-check the names with `dailybot user list` and `dailybot team list`.

## Output / Display

### `dailybot agent message list | jq ...` fails with "parse error"

- Errors went to stderr but you piped both. Use `dailybot ... 2>/dev/null | jq ...` or `dailybot ... | jq ...` (the data stream is already clean).
- The command output isn't JSON — `agent message list` renders a Rich table by default. There is no `--json` flag yet; if you need raw JSON, file an issue.

### Rich markup like `[bold]` shows up literally instead of formatted

- Your terminal doesn't support ANSI. Try `TERM=xterm-256color dailybot ...`.
- You're inside a CI runner or `tee` pipe — Rich auto-detects and disables formatting; the literal markup leaking through is a bug. Capture the exact command and open an issue.

### `print_error` text appears on stdout, not stderr

- That's a regression. Confirm you're calling `print_error` (which uses `error_console`) and not `print_info` or `console.print`.

## Tests

### `pytest` reports `0 collected`

- Test file is named `test_<x>.py` instead of `<x>_test.py`. Rename per `pytest.ini::python_files = *_test.py`.

### Test hangs for 30+ seconds

- A real HTTP call is leaking through. You forgot to patch `httpx.<method>`. Run with `pytest -s` to see the request.

### `MagicMock` test passes but real CLI breaks

- The mock didn't match the real signature. Use `MagicMock(spec=DailyBotClient)` (with `spec=`) to enforce attribute parity.

### Click test: `result.exit_code == 1` but `result.output` is empty

- The error went to stderr. Use `runner.invoke(cli, [...], mix_stderr=False)` and check `result.stderr`.

## Releases

### Tag pushed, GitHub Release didn't appear

- Check the Actions tab for the failing job (usually Homebrew waiting for PyPI).
- The release job depends on `build-linux` and `publish-pypi`. If either fails, the GitHub Release won't be created.

### `pip install dailybot-cli` returns the old version

- PyPI CDN propagation is usually fast (< 1 minute) but can take longer. Retry in 30s.
- Confirm the workflow's PyPI step succeeded; a 409 Conflict means the version was never re-uploaded.

### `brew install dailybot` fails: resource X has no candidate

- The Homebrew formula's `resource` list is missing an entry or has an outdated sha256. Run `brew tap` again, or wait for the next release that fixes the formula.
- If you're publishing the release: open `.github/workflows/release.yml` → the `update-homebrew` job inlines the formula. Fix the `resource` block, bump the patch version, re-tag.

## Config Files

### `permission denied` reading `~/.config/dailybot/credentials.json`

- The file is `0o600` and you're running as a different user. Either run the CLI as the owning user or `chown` the file (rare scenario; usually means the home dir is shared between containers).

### Stored API key not picked up

Resolution order for agent commands (most → least specific):
1. `--profile <name>`
2. Default profile in `agents.json`
3. `DAILYBOT_API_KEY` env var
4. `dailybot config key=...`
5. Login Bearer token

If a higher-priority source exists, the lower-priority one is ignored. To debug, run `dailybot agent profiles` and `env | grep DAILYBOT_`.
