# Herdr SSH setup — cli

One-time recipe for reaching this repository's container over SSH, so Herdr can
attach to it from the Mac. Day-to-day container commands are in
[`LOCAL_ENVIRONMENT.md`](LOCAL_ENVIRONMENT.md); this file is only about SSH.

> **Per-repo template.** Every Dailybot repository carries a file with this name
> and this structure. Everything below is identical everywhere except the four
> values in the table immediately following, and the "Files in this repo" table
> at the end.

| This repository | Value |
|---|---|
| Container | `dailybot-cli` |
| Host SSH port | `22031` |
| Container user | `dev-user` |
| SSH alias / Herdr machine | `dailybot-cli` |

## How it works

The container runs `sshd` and publishes it on the host as
`127.0.0.1:22031` — loopback only, never every interface. Authentication is
**public key only**: on start the entrypoint appends every `*.pub` it finds in
the read-only mount of your `~/.ssh` to the container's `authorized_keys`. No
password is ever accepted, and no private key is read for this purpose.

| Piece | Where |
|---|---|
| `openssh-server`, generated host keys, sshd drop-in | `docker/local/cli/Dockerfile` |
| Importing your public keys and starting sshd | `docker/local/cli/entrypoint.sh` |
| The published host port, bound to loopback | `docker/local/docker-compose.yaml` |

If you would rather not use SSH at all, `bash dev.sh shell` from the repository
root opens a shell through Docker and needs none of this.

Do **not** publish `2222:22`. Cursor listens on `127.0.0.1:2222` and `[::1]:2222`
and steals `localhost` connections before they reach Docker.

## Quick start

```bash
# From the Mac host, at this repository's root
bash dev.sh setup        # first time only
bash dev.sh build
bash dev.sh up

# One-time SSH alias (~/.ssh/config)
# Prefer 127.0.0.1 over localhost to avoid ::1 hitting Cursor.
# Do not set UserKnownHostsFile /dev/null — Herdr multi-machine uses strict checks.
```

```sshconfig
Host dailybot-cli
  HostName 127.0.0.1
  Port 22031
  User dev-user
  StrictHostKeyChecking accept-new
```

```bash
ssh-keyscan -p 22031 127.0.0.1 >> ~/.ssh/known_hosts
ssh -o BatchMode=yes dailybot-cli 'echo OK && herdr --version && herdr status server --json'
```

Override the host port if 22031 is already taken on your machine:

```bash
# docker/local/cli/.env (compose interpolation)
HERDR_SSH_HOST_PORT=<a free port on your Mac>
```

Then point the SSH `Port` at the same value.

On start, the entrypoint prepends `Include ~/.ssh_host/config.d/dailybot-peers`
to the copied SSH config when that peers file is present, and copies the host
Herdr catalog from the read-only `~/.herdr_client_host` mount. It does not
rewrite `HostName`. The Mac config must not Include `dailybot-peers`.

## Saved machine (unified sidebar)

```bash
herdr machine add dailybot-cli --label "Dailybot CLI"
herdr machine list
```

If `machine add` fails with `server closed connection; machine was not saved`
(Herdr 0.9.0 Docker-SSH setup race), write the catalog by hand:

```bash
mkdir -p ~/.local/state/herdr/client

python3 - <<'PY'
import json, secrets
from pathlib import Path

path = Path.home() / ".local/state/herdr/client" / "endpoints.json"
catalog = {"version": 1, "ssh": []}
if path.exists():
    catalog = json.loads(path.read_text())
catalog.setdefault("version", 1)
catalog.setdefault("ssh", [])
catalog["ssh"].append({
    "id": secrets.token_hex(16),
    "label": "Dailybot CLI",
    "target": "dailybot-cli",
    "session": "default",
    "enabled": True,
})
path.write_text(json.dumps(catalog, indent=2) + "\n")
path.chmod(0o600)
print(path.read_text())
PY

herdr machine list
```

Restart the **local** Herdr client. If status is `! attention`:

```bash
herdr --remote dailybot-cli --session default
# detach: ctrl+b q
herdr
```

## Host Herdr config (recommended, one-time)

`~/.config/herdr/config.toml`:

```toml
[experimental]
allow_nested = true

[remote]
manage_ssh_config = false
```

`allow_nested` is also seeded in the container (image + entrypoint patch on
existing `herdr_data` volumes).

## Day-to-day

| Path | When to use |
|------|-------------|
| `herdr` then sidebar → **Dailybot CLI** | Local + remote agents in one UI |
| `herdr --remote dailybot-cli` | Full-screen remote only |
| `bash dev.sh agents` | From inside this container: live machines and the agents on them right now |
| `dbdev agents` | The same list from the Mac |
| Nest `--remote` inside a local Herdr pane | Avoid — two sidebars |

### Finding another agent

`dbdev agents` (inside a container or on the Mac; `bash dev.sh agents` is the same list) prints one row per agent. **ID** is the hex machine id. **PANE** (`w5:p2`) is the conversation. A machine with five agents is five rows. The list is live: rerun it. A rebuild does not refresh it.

```bash
herdr --machine <machine id> agent prompt <pane> "Prompt..."
```

The listing prints one filled-in example under the table. `no agents` means the machine answered and nobody is running. `unreachable` means SSH did not answer. Contributor tooling only — keep machine ids and ports out of the public README and CLI help.

Phone / Tailscale / Moshi should SSH to the **Mac**, not to `22031`. Herdr
on the Mac reaches this container.

## Diagnostics

```bash
lsof -nP -iTCP:22031 -sTCP:LISTEN
lsof -nP -iTCP:2222 -sTCP:LISTEN

ssh -vvv -p 22031 dev-user@127.0.0.1 true
ssh -o BatchMode=yes dailybot-cli 'herdr status server --json'
# need: surface_interest, health_check (typically detached_server_daemon)

docker exec dailybot-cli sh -c 'ps aux | grep sshd; ls -la /etc/ssh/ssh_host_*; ls -la /home/dev-user/.ssh'
docker exec -u dev-user dailybot-cli herdr status
```

## Files in this repo

| File | Change |
|------|--------|
| `docker/local/docker-compose.yaml` | publishes `127.0.0.1:22031 -> 22` (override with `HERDR_SSH_HOST_PORT` in `docker/local/cli/.env`) |

Host-only (not in git): `~/.ssh/config`, `~/.ssh/known_hosts`,
`~/.config/herdr/config.toml`, `~/.local/state/herdr/client/endpoints.json`.


## Starting the container

Nothing here requires Cursor. From the repository root:

```bash
bash dev.sh up          # starts this repo's services
bash dev.sh ps          # confirm the SSH port is published
herdr --remote dailybot-cli   # after `bash dev.sh up`
```

If Herdr shows `reconnecting`, the container is almost always stopped rather
than Herdr being at fault. Check `bash dev.sh ps` first. The devcontainer sets
`"shutdownAction": "none"`, so closing Cursor no longer stops it.
