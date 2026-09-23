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
| `rebuild [service]` | Stop this repo's services, rebuild images (**layer cache on** by default), and recreate containers. Same idea as VS Code **Rebuild and Reopen Container**. Pass `--no-cache` for a full wipe (`--no-cache --pull`, slow). Host: `dbdev api rebuild`. |
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
[`HERDR_SSH_SETUP.md`](HERDR_SSH_SETUP.md). To see the agents on the other
machines, run `dbdev agents` inside this container. `bash dev.sh agents`
is the same list. On the Mac, `dbdev agents` prints the same table.
One row per agent; **ID** is the machine, **PANE** is the
conversation. Message one with
`herdr --machine <machine id> agent prompt <pane> "Prompt..."`.
Rerun the list when you need a fresh view. Contributor tooling only — keep
it out of the public README and CLI help.

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


### A change to the image needs a rebuild

`up` starts containers from the image that exists; it does not build one. The
entrypoint is `COPY`ed into the image, so a change to it — or to the Dockerfile —
is invisible until you rebuild. The one-step form matches the Dev Containers
plugin "Rebuild and Reopen Container":

```bash
bash dev.sh rebuild              # default: layer cache on (fast)
bash dev.sh rebuild --no-cache   # full wipe + pull base images (slow)
```

That stops this repository's services, builds their images, and starts them
again with `--force-recreate`. Cache is on by default so only changed layers
re-run; `--no-cache` is the full wipe when you need a clean base. The same
verb is available from the host as `dbdev api rebuild` /
`dailybot-dev web rebuild [--no-cache]`.

The equivalent three-step form still works when you want the pieces separate:

```bash
bash dev.sh build && bash dev.sh down && bash dev.sh up
```

`down` then `up` alone only recreates the container from the *old* image, which
is why a container can keep the shape it was created with long after the file
changed. Compose-only changes (ports, volumes, environment) do take effect on a
recreate, no build required.

---

## 4.1 Coding CLIs and the editor

A default image build does not download Claude, Cursor, Codex, Pi, OpenCode,
Cline, or Grok. Each one installs only when its flag is the exact string
`true`. Compose interpolates those flags from `docker/local/.env` (next to
the compose file; stubs in `docker/local/.env.example` are `false`). The Dev
Containers plugin and `bash dev.sh rebuild` both read that file. Set a flag,
then rebuild.

| Flag | CLI |
|---|---|
| `INSTALL_CLAUDE_CLI` | Claude Code |
| `INSTALL_CURSOR_CLI` | Cursor CLI |
| `INSTALL_CODEX_CLI` | Codex |
| `INSTALL_PI_CLI` | Pi |
| `INSTALL_OPENCODE_CLI` | OpenCode |
| `INSTALL_CLINE_CLI` | Cline |
| `INSTALL_GROK_CLI` | Grok |

`nvim` for `dev-user` is the full Dailybot mu-vim config. The image clones
`https://github.com/DailybotHQ/mu-vim.git` into `~/.config/nvim` and runs
`lua install.lua`, then a headless plugin sync. The binary is the Neovim
0.12.5 tarball in `~/.local`, ahead of any apt package the installer adds.
`EDITOR`, `VISUAL`, and `GIT_EDITOR` are `nvim`.

---

## 5. Ports
