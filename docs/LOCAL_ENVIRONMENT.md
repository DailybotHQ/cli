# Local environment — cli

How to start this repository's containers, day to day, with or without an
editor. Written for humans and for AI agents landing here cold.

> This file documents the optional container used by contributors. It is not
> needed to use or install the Dailybot CLI.

---

## 1. First time, one command

```bash
bash dev.sh setup
```

That creates what the stack needs and nothing else:

- every `.env` under `docker/local/` that is missing, copied from its
  `.env.example` sibling;
- the external docker network, when this repository's compose file declares one;
- `.devcontainer/` from the tracked `.devcontainer_example/`, and `.vscode/` from
  `.vscode_example/` where the repository has one;
- `"shutdownAction": "none"` in the active devcontainer file, so closing Cursor
  does not stop your containers;
- whatever `docker/local/dev-setup-hook.sh` does, when this repository has one —
  the escape hatch for bootstrap the generic steps cannot know about.

It is safe to run again. It **never overwrites an existing file** and **never
prints an environment value**. A second run says `everything was already in
place`.

You do not need to run it before `config`, `ps`, `logs`, `ls` or `doctor` —
those work on a tree that was never set up, which is what makes `doctor` useful
when something is wrong.

---

## 2. Daily use

```bash
bash dev.sh up        # starts clivscode
bash dev.sh shell     # shell in clivscode as dev-user, in /workspace
bash dev.sh ps        # what is running here
bash dev.sh logs      # follow the main service
bash dev.sh down      # stop and remove this repo's containers
```

| Verb | What it does |
|---|---|
| `up [service...]` | Starts the devcontainer's `runServices`, detached. Existing containers are left as they are; pass `--recreate` to apply compose changes. |
| `down` | Stops and removes **this repository's** services. Never removes a named volume. |
| `stop` · `start` · `restart` | Lifecycle on containers that already exist. |
| `ps` | This repository's containers, with published ports. |
| `logs [service]` | Follow logs. Defaults to the main service. |
| `shell [service]` | Interactive shell as the devcontainer's `remoteUser`, in its `workspaceFolder`. |
| `exec <service> <cmd...>` | Run one command in a service. |
| `build [service]` | Build images. |
| `ls` | Every repository this launcher can address, and how many of each one's services are up. |
| `config` | The resolved configuration. Writes nothing, starts nothing. |
| `doctor` | Environment diagnosis. Writes nothing, starts nothing. |

---

## 3. Two entry paths, both first class

The same containers serve either client. You do not pick one stack for Cursor
and another for a terminal.

| Path | How you enter | What you get |
|---|---|---|
| **Cursor or VS Code** | Reopen in Container, using `.devcontainer/` | The editor's integrated terminal, extensions and automatic port forwarding |
| **Terminal or Herdr** | `bash dev.sh up`, then `bash dev.sh shell` or `herdr --remote <machine>` | The same container over SSH or `docker exec`, with ports published by compose |

Closing Cursor does **not** stop the stack, because the devcontainer sets
`"shutdownAction": "none"`. If you prefer the old behavior, set `"stopCompose"`
in your **local** `.devcontainer/devcontainer.json`; it is gitignored, so that
choice stays yours.

One caveat worth knowing: while a Cursor Dev Container window is attached, it can
temporarily own the container's SSH host port, and Herdr will show
`reconnecting` until that window disconnects. Use one SSH-style client at a time
on a given container, or edit from the host while Herdr owns the remote.

Herdr setup is a separate, one-time recipe:
[`HERDR_SSH_SETUP.md`](HERDR_SSH_SETUP.md).

---

## 4. What the launcher reads

`dev.sh` has no service list of its own. It reads
`.devcontainer/devcontainer.json` — the same file Cursor reads — and takes:

| Key | Used for |
|---|---|
| `runServices` | Exactly what `up` starts |
| `service` | The main service for `shell` and `logs` |
| `remoteUser` | Who `shell` runs as |
| `workspaceFolder` | Where `shell` starts |
| `dockerComposeFile` | Which compose file, resolved relative to the devcontainer file |

**To change what starts, edit `runServices` and nothing else.** There is no
second list anywhere.

If `.devcontainer/` does not exist yet, the launcher falls back to the tracked
`.devcontainer_example/devcontainer.json` and says so, so a fresh clone works
before you have run `setup`.

Run `bash dev.sh config` to see exactly what it resolved, including the compose
project name and which rule produced it.

---

## 5. Ports

Everything is bound to loopback. Nothing is published on all interfaces.

| Host | Container | Purpose |
|---|---|---|
| (none) |  | This container publishes no ports today. |

Override a port in `docker/local/.env`, not in the compose file.

**This table describes what the compose file declares.** A container that is
already running keeps the mapping it was created with until it is recreated, so
after any port change `docker ps` can disagree with the table until you run
`bash dev.sh up --recreate`. Check what a running container actually publishes
with `bash dev.sh ps`.

---

## 6. Troubleshooting

**`local environment not ready ... run: bash dev.sh setup`**
The fast check found a missing `.env` or a missing docker network. Run `setup`.
That check only runs for verbs that start containers, and costs about thirty
milliseconds.

**`cannot resolve the compose project name`**
The launcher refuses to guess the Compose project name from the directory name,
because guessing would create a second, parallel set of containers that look
correct and are not the ones your Dev Container manages. Set
`COMPOSE_PROJECT_NAME` in `docker/local/.env`, or pass `--project`.

**A container came back different, or an editor feature disappeared**
`up` defaults to `--no-recreate` precisely so it never silently replaces a
container the Dev Containers plugin created. If you changed the compose file and
want it applied, that is what `--recreate` is for.

**Herdr shows `reconnecting`**
Almost always the container is stopped, not a Herdr fault. Check with
`bash dev.sh ps`, then `bash dev.sh up`. If the container is up, see the Cursor
port caveat in section 3.

**Which compose project does a container belong to?**

```bash
docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}'
```

**Never run compose with `--remove-orphans` here.** This container shares a
compose project with other local development containers, so that flag would
remove them. `dev.sh` never passes it.

---

## 7. What this does not replace

- **The Dev Container workflow.** Fully supported, unchanged, same containers.
- Nothing — this repository never had a `docker/local/docker.sh`.

This project does **not** require Docker. It is a plain Python package; `pip install -e .` and `pytest` run on the host. The container is contributor tooling for the coding-agent CLIs.
