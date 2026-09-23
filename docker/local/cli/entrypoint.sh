#!/bin/bash

# Dailybot Core CLI Entrypoint
# Sets up persistence for AI CLI tools and SSH keys

# Setup Claude CLI persistence with symlinks for a given user
# This ensures Claude config persists across container rebuilds
# Principle: seed on first run, preserve on rebuild
setup_claude_persistence_for_user() {
    USER_HOME="$1"
    CLAUDE_DATA_DIR="${USER_HOME}/.claude_data"
    CLAUDE_JSON="${USER_HOME}/.claude.json"
    CLAUDE_DIR="${USER_HOME}/.claude"
    CLAUDE_JSON_BACKUP="${USER_HOME}/.claude.json.backup"
    CLAUDE_CONFIG_DIR="${USER_HOME}/.config/claude-code"

    # Ensure the persistent data directory exists
    mkdir -p "${CLAUDE_DATA_DIR}"

    # Handle .claude.json file — only seed if volume has no existing data
    if [ ! -L "${CLAUDE_JSON}" ]; then
        if [ -f "${CLAUDE_JSON}" ]; then
            if [ ! -f "${CLAUDE_DATA_DIR}/claude.json" ]; then
                cp "${CLAUDE_JSON}" "${CLAUDE_DATA_DIR}/claude.json"
            fi
            rm "${CLAUDE_JSON}"
        fi
        # Create symlink
        ln -sf "${CLAUDE_DATA_DIR}/claude.json" "${CLAUDE_JSON}"
    fi

    # Handle .claude directory — only seed if volume has no existing data
    if [ ! -L "${CLAUDE_DIR}" ]; then
        if [ -d "${CLAUDE_DIR}" ]; then
            if [ ! -d "${CLAUDE_DATA_DIR}/claude_dir" ] || [ -z "$(ls -A "${CLAUDE_DATA_DIR}/claude_dir" 2>/dev/null)" ]; then
                cp -r "${CLAUDE_DIR}" "${CLAUDE_DATA_DIR}/claude_dir"
            fi
            rm -rf "${CLAUDE_DIR}"
        else
            mkdir -p "${CLAUDE_DATA_DIR}/claude_dir"
        fi
        # Create symlink
        ln -sf "${CLAUDE_DATA_DIR}/claude_dir" "${CLAUDE_DIR}"
    fi

    # Handle .claude.json.backup file — only seed if volume has no existing data
    if [ -f "${CLAUDE_JSON_BACKUP}" ] && [ ! -L "${CLAUDE_JSON_BACKUP}" ]; then
        if [ ! -f "${CLAUDE_DATA_DIR}/claude.json.backup" ]; then
            cp "${CLAUDE_JSON_BACKUP}" "${CLAUDE_DATA_DIR}/claude.json.backup"
        fi
        rm "${CLAUDE_JSON_BACKUP}"
        ln -sf "${CLAUDE_DATA_DIR}/claude.json.backup" "${CLAUDE_JSON_BACKUP}"
    fi

    # Handle .config/claude-code directory (auth tokens) — only seed if volume has no existing data
    mkdir -p "${USER_HOME}/.config"
    if [ ! -L "${CLAUDE_CONFIG_DIR}" ]; then
        if [ -d "${CLAUDE_CONFIG_DIR}" ]; then
            if [ ! -d "${CLAUDE_DATA_DIR}/config_claude_code" ] || [ -z "$(ls -A "${CLAUDE_DATA_DIR}/config_claude_code" 2>/dev/null)" ]; then
                cp -r "${CLAUDE_CONFIG_DIR}" "${CLAUDE_DATA_DIR}/config_claude_code"
            fi
            rm -rf "${CLAUDE_CONFIG_DIR}"
        else
            mkdir -p "${CLAUDE_DATA_DIR}/config_claude_code"
        fi
        # Create symlink
        ln -sf "${CLAUDE_DATA_DIR}/config_claude_code" "${CLAUDE_CONFIG_DIR}"
    fi
}

# Setup Claude persistence for dev-user only
setup_claude_persistence_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.claude_data /home/dev-user/.claude.json /home/dev-user/.claude /home/dev-user/.config/claude-code 2>/dev/null || true

# Setup Codex CLI persistence with symlinks for a given user
# This ensures OpenAI Codex config persists across container rebuilds
setup_codex_persistence_for_user() {
    USER_HOME="$1"
    CODEX_DATA_DIR="${USER_HOME}/.codex_data"
    CODEX_DIR="${USER_HOME}/.codex"

    # Ensure the persistent data directory exists
    mkdir -p "${CODEX_DATA_DIR}"

    # Handle .codex directory
    if [ ! -L "${CODEX_DIR}" ]; then
        # If it's a real directory, move it to the persistent volume
        if [ -d "${CODEX_DIR}" ]; then
            cp -r "${CODEX_DIR}" "${CODEX_DATA_DIR}/codex_dir"
            rm -rf "${CODEX_DIR}"
        else
            mkdir -p "${CODEX_DATA_DIR}/codex_dir"
        fi
        # Create symlink
        ln -sf "${CODEX_DATA_DIR}/codex_dir" "${CODEX_DIR}"
    fi
}

# Setup Codex persistence for dev-user only
setup_codex_persistence_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.codex_data /home/dev-user/.codex 2>/dev/null || true

# Setup Cursor CLI persistence with symlinks for a given user
# This ensures Cursor CLI config persists across container rebuilds
# Cursor stores data in two locations:
#   - ~/.cursor (CLI config, chats, projects)
#   - ~/.config/cursor (auth tokens - accessToken, refreshToken)
setup_cursor_persistence_for_user() {
    USER_HOME="$1"
    CURSOR_DATA_DIR="${USER_HOME}/.cursor_data"
    CURSOR_DIR="${USER_HOME}/.cursor"
    CURSOR_CONFIG_DIR="${USER_HOME}/.config/cursor"

    # Ensure the persistent data directory exists
    mkdir -p "${CURSOR_DATA_DIR}"

    # Handle .cursor directory (CLI config, chats, projects)
    if [ ! -L "${CURSOR_DIR}" ]; then
        # If it's a real directory, move it to the persistent volume
        if [ -d "${CURSOR_DIR}" ]; then
            cp -r "${CURSOR_DIR}" "${CURSOR_DATA_DIR}/cursor_dir"
            rm -rf "${CURSOR_DIR}"
        else
            mkdir -p "${CURSOR_DATA_DIR}/cursor_dir"
        fi
        # Create symlink
        ln -sf "${CURSOR_DATA_DIR}/cursor_dir" "${CURSOR_DIR}"
    fi

    # Handle .config/cursor directory (auth tokens)
    mkdir -p "${USER_HOME}/.config"
    if [ ! -L "${CURSOR_CONFIG_DIR}" ]; then
        # If it's a real directory, move it to the persistent volume
        if [ -d "${CURSOR_CONFIG_DIR}" ]; then
            cp -r "${CURSOR_CONFIG_DIR}" "${CURSOR_DATA_DIR}/config_cursor"
            rm -rf "${CURSOR_CONFIG_DIR}"
        else
            mkdir -p "${CURSOR_DATA_DIR}/config_cursor"
        fi
        # Create symlink
        ln -sf "${CURSOR_DATA_DIR}/config_cursor" "${CURSOR_CONFIG_DIR}"
    fi
}

# Setup Cursor persistence for dev-user only
setup_cursor_persistence_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.cursor_data /home/dev-user/.cursor 2>/dev/null || true

# Setup GitHub CLI persistence with symlinks for a given user
# This ensures gh config persists across container rebuilds
setup_gh_persistence_for_user() {
    USER_HOME="$1"
    GH_DATA_DIR="${USER_HOME}/.gh_data"
    GH_CONFIG_DIR="${USER_HOME}/.config/gh"

    # Ensure the persistent data directory exists
    mkdir -p "${GH_DATA_DIR}"

    # Handle .config/gh directory
    if [ ! -L "${GH_CONFIG_DIR}" ]; then
        # Create parent directory if needed
        mkdir -p "${USER_HOME}/.config"

        # If it's a real directory, move it to the persistent volume
        if [ -d "${GH_CONFIG_DIR}" ]; then
            cp -r "${GH_CONFIG_DIR}" "${GH_DATA_DIR}/gh_config"
            rm -rf "${GH_CONFIG_DIR}"
        else
            mkdir -p "${GH_DATA_DIR}/gh_config"
        fi
        # Create symlink
        ln -sf "${GH_DATA_DIR}/gh_config" "${GH_CONFIG_DIR}"
    fi
}

# Setup GitHub CLI persistence for dev-user only
setup_gh_persistence_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.gh_data /home/dev-user/.config 2>/dev/null || true

# Setup Dailybot CLI persistence with symlinks for a given user
# This ensures Dailybot CLI config persists across container rebuilds
setup_dailybot_persistence_for_user() {
    USER_HOME="$1"
    DAILYBOT_DATA_DIR="${USER_HOME}/.dailybot_data"
    DAILYBOT_CONFIG_DIR="${USER_HOME}/.config/dailybot"

    # Ensure the persistent data directory exists
    mkdir -p "${DAILYBOT_DATA_DIR}"
    mkdir -p "${DAILYBOT_DATA_DIR}/config_local"
    mkdir -p "${DAILYBOT_DATA_DIR}/config_custom"

    # Handle .config/dailybot directory (auth tokens and config)
    mkdir -p "${USER_HOME}/.config"
    if [ ! -L "${DAILYBOT_CONFIG_DIR}" ]; then
        if [ -d "${DAILYBOT_CONFIG_DIR}" ]; then
            if [ ! -d "${DAILYBOT_DATA_DIR}/config_dailybot" ] || [ -z "$(ls -A "${DAILYBOT_DATA_DIR}/config_dailybot" 2>/dev/null)" ]; then
                cp -r "${DAILYBOT_CONFIG_DIR}" "${DAILYBOT_DATA_DIR}/config_dailybot"
            fi
            rm -rf "${DAILYBOT_CONFIG_DIR}"
        else
            mkdir -p "${DAILYBOT_DATA_DIR}/config_dailybot"
        fi
        # Create symlink
        ln -sf "${DAILYBOT_DATA_DIR}/config_dailybot" "${DAILYBOT_CONFIG_DIR}"
    fi
}

# Setup Dailybot persistence for dev-user only
setup_dailybot_persistence_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.dailybot_data /home/dev-user/.config/dailybot 2>/dev/null || true

# Setup Herdr persistence with symlinks for a given user
# Herdr keeps its session layout -- workspaces, tabs, panes and each pane's
# directory -- in ~/.config/herdr. That path lives in the container's writable
# layer, so stopping the container discarded it and every console had to be
# rebuilt by hand. Symlinking it into the mounted volume makes the layout
# survive a recreate. Running processes cannot survive: removing the container
# kills the shells. What comes back is the arrangement of consoles.
setup_herdr_persistence_for_user() {
    USER_HOME="$1"
    HERDR_DATA_DIR="${USER_HOME}/.herdr_data/config"
    HERDR_CONFIG_DIR="${USER_HOME}/.config/herdr"

    mkdir -p "${USER_HOME}/.config"

    if [ ! -L "${HERDR_CONFIG_DIR}" ]; then
        if [ -e "${HERDR_CONFIG_DIR}" ]; then
            if [ ! -e "${HERDR_DATA_DIR}" ]; then
                mkdir -p "$(dirname "${HERDR_DATA_DIR}")"
                cp -r "${HERDR_CONFIG_DIR}" "${HERDR_DATA_DIR}"
            fi
            rm -rf "${HERDR_CONFIG_DIR}"
        else
            mkdir -p "${HERDR_DATA_DIR}"
        fi
        ln -sf "${HERDR_DATA_DIR}" "${HERDR_CONFIG_DIR}"
    fi
}

# Setup Herdr persistence for dev-user only
setup_herdr_persistence_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.herdr_data 2>/dev/null || true

# Nested Herdr -- needed when a Herdr client attaches to this container. The image
# may seed it, but that seed only reaches an EMPTY volume: a volume created
# before the seed keeps the old file forever, so ensure it at runtime too.
# Inserted into [experimental] when that table already exists, never duplicated.
ensure_herdr_allow_nested() {
    HERDR_CONFIG="/home/dev-user/.config/herdr/config.toml"
    mkdir -p "$(dirname "${HERDR_CONFIG}")"
    if [ ! -f "${HERDR_CONFIG}" ]; then
        printf '%s\n' '[experimental]' 'allow_nested = true' > "${HERDR_CONFIG}"
    elif ! grep -qE '^[[:space:]]*allow_nested[[:space:]]*=' "${HERDR_CONFIG}"; then
        if grep -qE '^[[:space:]]*\[experimental\]' "${HERDR_CONFIG}"; then
            awk '
                BEGIN { done = 0 }
                /^[[:space:]]*\[experimental\]/ { print; if (!done) { print "allow_nested = true"; done = 1; next } }
                { print }
            ' "${HERDR_CONFIG}" > "${HERDR_CONFIG}.tmp" && mv "${HERDR_CONFIG}.tmp" "${HERDR_CONFIG}"
        else
            printf '\n%s\n%s\n' '[experimental]' 'allow_nested = true' >> "${HERDR_CONFIG}"
        fi
    fi
}
ensure_herdr_allow_nested

# Herdr opens new panes, tabs and workspaces in $HOME unless told otherwise, so a
# console opened in a fresh container landed nowhere useful and every new pane had
# to be cd'd by hand. The project directory is the container's own WORKDIR -- the
# same path devcontainer.json calls workspaceFolder -- so it is read from there
# rather than written down a third time and left to drift out of step.
#
# The table is rewritten in place, never appended: a second [terminal] is invalid
# TOML and makes Herdr reject the WHOLE file, silently, taking allow_nested and
# the shell with it. Reading the file twice also repairs one already in that
# state. Keys already present win, so a developer's own new_cwd is kept.
ensure_herdr_terminal_defaults() {
    HERDR_CONFIG="/home/dev-user/.config/herdr/config.toml"
    HERDR_CWD="$(pwd)"
    mkdir -p "$(dirname "${HERDR_CONFIG}")"
    [ -f "${HERDR_CONFIG}" ] || : > "${HERDR_CONFIG}"
    # shell_mode was pinned to "non_login" here on 2026-09-18. That was wrong: a
    # non-login shell reads neither /etc/profile.d nor ~/.profile, and that is
    # where PATH picks up the agent CLIs -- `claude` became "command not found"
    # in a Herdr pane while the same command worked in Cursor, which uses docker
    # exec and inherits the container's PATH. Repair that exact value; a value a
    # developer chose themselves is left alone.
    sed -i 's/^shell_mode = "non_login"$/shell_mode = "login"/' "${HERDR_CONFIG}"
    awk -v cwd="${HERDR_CWD}" '
    function keyname(l,  k) { k = l; sub(/[[:space:]]*=.*/, "", k); gsub(/[[:space:]]/, "", k); return k }
    # Blank lines are held back and only flushed before real content, so a table
    # appended at EOF does not leave a trailing blank that the next start would
    # append to again -- the file would grow a line on every container start.
    function emit(l) {
        if (l == "") { if (any) pend++; return }
        while (pend > 0) { print ""; pend-- }
        print l; any = 1
    }
    function table(  i) {
        emit("[terminal]")
        if (!("new_cwd" in seen))    emit(sprintf("new_cwd = \"%s\"", cwd))
        if (!("shell_mode" in seen)) emit("shell_mode = \"login\"")
        for (i = 1; i <= n; i++) emit(order[i])
        emit("")
    }
    FNR == NR {
        if ($0 ~ /^\[terminal\]/) { insec = 1; next }
        if ($0 ~ /^\[/)            { insec = 0 }
        if (insec && $0 ~ /^[[:space:]]*[A-Za-z_]+[[:space:]]*=/) {
            k = keyname($0); if (!(k in seen)) { seen[k] = 1; order[++n] = $0 }
        }
        next
    }
    {
        if ($0 ~ /^\[terminal\]/) {
            skip = 1
            if (!done) { table(); done = 1 }
            next
        }
        if ($0 ~ /^\[/) { skip = 0 }
        if (skip) next
        emit($0)
    }
    END { if (!done) { emit(""); table() } }
' "${HERDR_CONFIG}" "${HERDR_CONFIG}" > "${HERDR_CONFIG}.tmp" && mv "${HERDR_CONFIG}.tmp" "${HERDR_CONFIG}"
}
ensure_herdr_terminal_defaults

# Herdr itself runs as dev-user, but everything above wrote as root, and
# .config/herdr is a symlink -- chowning that path would only touch the link.
# Take the real directory, after the last write, or Herdr cannot rewrite its
# own config (onboarding flag, settings changed from the UI).
chown -R dev-user:dev-user "/home/dev-user/.herdr_data" 2>/dev/null || true

# OpenCode, Pi, Cline and Grok each got a named volume, but nothing linked the
# paths those CLIs actually write to it. The volume stayed empty while the real
# state sat in the container layer, so `docker volume ls` looked reassuring and
# the developer still lost their sign-in on the next recreate. Same shape as the
# Claude/Codex/Cursor helpers above: seed on first run, preserve after that.
setup_agent_state_persistence() {
    USER_HOME="$1"; AGENT_DATA_DIR="${USER_HOME}/$2"; AGENT_LIVE_DIR="${USER_HOME}/$3"; AGENT_SLOT="$4"
    # Only ever relink into a directory that is actually a mounted volume. A
    # repository that keeps this state somewhere else entirely would otherwise
    # have its working arrangement replaced by one pointing at the container
    # layer -- persistence that looks right and is silently thrown away on the
    # next recreate, which is the very bug this function exists to prevent.
    # A volume is a different device from the layer it is mounted into.
    if [ "$(stat -c %d "${AGENT_DATA_DIR}" 2>/dev/null)" = "$(stat -c %d "$(dirname "${AGENT_DATA_DIR}")" 2>/dev/null)" ]; then
        return 0
    fi
    mkdir -p "${AGENT_DATA_DIR}"
    # A link left pointing at nothing is worse than no link: the CLI recreates
    # the path as a real directory beside it and the volume stays empty.
    if [ -L "${AGENT_LIVE_DIR}" ] && [ ! -e "${AGENT_LIVE_DIR}" ]; then
        mkdir -p "${AGENT_DATA_DIR}/${AGENT_SLOT}"
    fi
    if [ ! -L "${AGENT_LIVE_DIR}" ]; then
        if [ -d "${AGENT_LIVE_DIR}" ]; then
            if [ ! -d "${AGENT_DATA_DIR}/${AGENT_SLOT}" ] || [ -z "$(ls -A "${AGENT_DATA_DIR}/${AGENT_SLOT}" 2>/dev/null)" ]; then
                cp -r "${AGENT_LIVE_DIR}" "${AGENT_DATA_DIR}/${AGENT_SLOT}"
            fi
            rm -rf "${AGENT_LIVE_DIR}"
        else
            mkdir -p "${AGENT_DATA_DIR}/${AGENT_SLOT}"
        fi
        mkdir -p "$(dirname "${AGENT_LIVE_DIR}")"
        ln -sf "${AGENT_DATA_DIR}/${AGENT_SLOT}" "${AGENT_LIVE_DIR}"
    fi
}
setup_agent_state_persistence "/home/dev-user" ".opencode_data" ".opencode" "opencode_dir"
setup_agent_state_persistence "/home/dev-user" ".opencode_data" ".local/share/opencode" "opencode_share"
setup_agent_state_persistence "/home/dev-user" ".pi_data" ".pi" "pi_dir"
setup_agent_state_persistence "/home/dev-user" ".grok_data" ".grok" "grok_dir"
chown -R dev-user:dev-user "/home/dev-user/.opencode_data" "/home/dev-user/.pi_data" "/home/dev-user/.grok_data" 2>/dev/null || true

# Herdr reaches this container over SSH, and sshd starts every session with a
# clean environment: nothing compose passed in through env_file or environment
# survives. Cursor uses docker exec, which does inherit it -- which is why the
# same command works in Cursor and fails in a Herdr pane ("API key is not set").
# Put the container's own environment back, for the login shell.
#
# It goes in the user's home rather than /etc/profile.d because an entrypoint
# does not always run as root, and writing under /etc then fails outright. The
# file is rewritten from the live environment on every start, so it cannot go
# stale, and it is 0600: it holds whatever secrets compose was given, for the
# one user whose shell is meant to have them.
write_container_env_profile() {
    python3 - "$1" "$2" <<'PY'
import os, pwd, shlex, sys

home, user = sys.argv[1], sys.argv[2]
# Shell- and container-managed names: re-exporting them would fight the login
# shell that is in the middle of building them.
SKIP = {"PATH", "HOME", "HOSTNAME", "PWD", "OLDPWD", "SHLVL", "SHELL",
        "USER", "LOGNAME", "TERM", "_"}
MARK = "# >>> dailybot container env >>>"

env_path = os.path.join(home, ".container-env.sh")
lines = ["# Generated by the entrypoint from the container's own environment.",
         "# Do not edit: rewritten on every container start.", ""]
for k, v in sorted(os.environ.items()):
    if k in SKIP or not k or k[0].isdigit() or not k.replace("_", "").isalnum():
        continue
    lines.append("export %s=%s" % (k, shlex.quote(v)))
tmp = env_path + ".tmp"
# Opened 0600 rather than written and chmod'd afterwards: this file holds every
# value compose was given, so a umask-default 0644 window between the two calls
# is a window where anyone on the box can read live credentials.
# O_EXCL and O_NOFOLLOW as well as the mode: this path is predictable and the
# file holds every value compose was given, so refuse to write through a
# symlink or into something already sitting there rather than following it.
try:
    os.unlink(tmp)
except FileNotFoundError:
    pass
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines) + "\n")
os.replace(tmp, env_path)

# bash reads the FIRST of these that exists, and ignores the rest, so the
# source line has to go in that one -- not always ~/.profile.
rc = None
for cand in (".bash_profile", ".bash_login", ".profile"):
    p = os.path.join(home, cand)
    if os.path.exists(p):
        rc = p
        break
if rc is None:
    rc = os.path.join(home, ".profile")
    open(rc, "a").close()
if MARK not in open(rc).read():
    with open(rc, "a") as f:
        f.write('\n%s\n[ -f "$HOME/.container-env.sh" ] && . "$HOME/.container-env.sh"\n'
                '# <<< dailybot container env <<<\n' % MARK)

if os.geteuid() == 0:
    try:
        pw = pwd.getpwnam(user)
        for p in (env_path, rc):
            os.chown(p, pw.pw_uid, pw.pw_gid)
    except KeyError:
        pass
PY
}
write_container_env_profile "/home/dev-user" "dev-user"

# Generate ~/.pypirc from environment variables for a given user
# This avoids hand-maintaining a .pypirc file in the repo or home dir.
# Tokens are read from PYPI_API_TOKEN / TESTPYPI_API_TOKEN (see cli/.env).
# If neither is set, no file is written (no-op).
setup_pypirc_from_env_for_user() {
    USER_HOME="$1"
    PYPIRC_PATH="${USER_HOME}/.pypirc"

    # Skip entirely if no tokens were provided
    if [ -z "${PYPI_API_TOKEN}" ] && [ -z "${TESTPYPI_API_TOKEN}" ]; then
        return 0
    fi

    # Build index-servers list dynamically based on which tokens are set
    INDEX_SERVERS=""
    [ -n "${PYPI_API_TOKEN}" ]     && INDEX_SERVERS="${INDEX_SERVERS}    pypi
"
    [ -n "${TESTPYPI_API_TOKEN}" ] && INDEX_SERVERS="${INDEX_SERVERS}    testpypi
"

    {
        echo "[distutils]"
        echo "index-servers ="
        printf "%s" "${INDEX_SERVERS}"

        if [ -n "${PYPI_API_TOKEN}" ]; then
            echo ""
            echo "[pypi]"
            echo "username = __token__"
            echo "password = ${PYPI_API_TOKEN}"
        fi

        if [ -n "${TESTPYPI_API_TOKEN}" ]; then
            echo ""
            echo "[testpypi]"
            echo "repository = https://test.pypi.org/legacy/"
            echo "username = __token__"
            echo "password = ${TESTPYPI_API_TOKEN}"
        fi
    } > "${PYPIRC_PATH}"

    chmod 600 "${PYPIRC_PATH}"
}

# Generate .pypirc for dev-user if tokens are present in the environment
setup_pypirc_from_env_for_user "/home/dev-user"
chown dev-user:dev-user /home/dev-user/.pypirc 2>/dev/null || true

# Setup SSH keys from host with correct permissions for a given user
# This allows git operations with GitHub/GitLab
setup_ssh_keys_for_user() {
    USER_HOME="$1"
    SSH_HOST_DIR="${USER_HOME}/.ssh_host"
    SSH_DIR="${USER_HOME}/.ssh"

    # Only setup if host SSH directory is mounted
    if [ -d "${SSH_HOST_DIR}" ]; then
        # Create SSH directory if it doesn't exist
        mkdir -p "${SSH_DIR}"

        # Check if any private SSH key already exists in the container
        # (skip .pub entries — those are public and don't count).
        KEYS_EXIST=false
        for existing_key in "${SSH_DIR}"/id_*; do
            [ -f "$existing_key" ] || continue
            case "$(basename "$existing_key")" in *.pub) continue ;; esac
            KEYS_EXIST=true
            break
        done

        # Only copy if keys don't exist yet (to avoid overwriting persistent volume)
        if [ "$KEYS_EXIST" = false ]; then
            echo "Setting up SSH keys from host for ${USER_HOME}..."

            # Copy any private key matching id_* (skipping .pub files, which are handled below).
            # This covers id_rsa, id_ed25519, id_ecdsa, id_rsa_xergioalex, etc.
            for key_file in "${SSH_HOST_DIR}"/id_*; do
                [ -f "$key_file" ] || continue
                key_name="$(basename "$key_file")"
                case "$key_name" in *.pub) continue ;; esac
                cp "$key_file" "${SSH_DIR}/$key_name"
                chmod 600 "${SSH_DIR}/$key_name"
                echo "  ✓ Copied $key_name"
            done

            # Copy public keys
            cp "${SSH_HOST_DIR}"/*.pub "${SSH_DIR}/" 2>/dev/null || true

            # Copy config if exists
            if [ -f "${SSH_HOST_DIR}/config" ]; then
                cp "${SSH_HOST_DIR}/config" "${SSH_DIR}/config"
                chmod 600 "${SSH_DIR}/config"
                echo "  ✓ Copied SSH config"
            fi

            # Copy known_hosts if exists (git can write to it)
            if [ -f "${SSH_HOST_DIR}/known_hosts" ]; then
                cp "${SSH_HOST_DIR}/known_hosts" "${SSH_DIR}/known_hosts"
                echo "  ✓ Copied known_hosts"
            fi

            echo "SSH keys setup completed for ${USER_HOME}"
        fi

        # Always ensure correct permissions (even if keys already existed)
        chmod 700 "${SSH_DIR}" 2>/dev/null || true
        chmod 600 "${SSH_DIR}"/id_* 2>/dev/null || true
        chmod 600 "${SSH_DIR}/config" 2>/dev/null || true
    fi
}

# Setup SSH keys for dev-user only
setup_ssh_keys_for_user "/home/dev-user"
chown -R dev-user:dev-user /home/dev-user/.ssh 2>/dev/null || true

# dailybot-herdr-peer-mesh
install_herdr_peer_mesh() {
  local home="$1"
  local user="$2"
  local ssh_config="${home}/.ssh/config"
  local include_line='Include ~/.ssh_host/config.d/dailybot-peers'
  local src="${home}/.herdr_client_host/endpoints.json"
  local dest_dir="${home}/.local/state/herdr/client"
  local dest="${dest_dir}/endpoints.json"
  if [ ! -f "${home}/.ssh_host/config.d/dailybot-peers" ]; then
    echo "herdr peers: ~/.ssh_host/config.d/dailybot-peers missing; skip include"
  elif [ -f "${ssh_config}" ]; then
    if ! grep -qxF "${include_line}" "${ssh_config}"; then
      local tmp
      tmp="$(mktemp)"
      printf '%s\n' "${include_line}" | cat - "${ssh_config}" > "${tmp}"
      mv "${tmp}" "${ssh_config}"
      chown "${user}:${user}" "${ssh_config}" 2>/dev/null || true
      chmod 600 "${ssh_config}" 2>/dev/null || true
    fi
  else
    mkdir -p "${home}/.ssh"
    printf '%s\n' "${include_line}" > "${ssh_config}"
    chown -R "${user}:${user}" "${home}/.ssh" 2>/dev/null || true
    chmod 700 "${home}/.ssh" 2>/dev/null || true
    chmod 600 "${ssh_config}" 2>/dev/null || true
  fi
  # Herdr writes endpoints.json, so the Mac catalog stays on a read-only mount
  # and this copy is what Herdr reads. Refresh it before every agent listing
  # so a machine created on the Mac shows up without a container restart.
  # The mount is the source; a container must not write back to it.
  # A missing catalog must not skip host-key trust below.
  # dailybot-herdr-refresh-catalog
  mkdir -p "${home}/.local/bin"
  cat > "${home}/.local/bin/herdr-refresh-catalog" <<'EOF'
#!/bin/sh
src="${HOME}/.herdr_client_host/endpoints.json"
dest="${HOME}/.local/state/herdr/client/endpoints.json"
if [ ! -f "$src" ]; then
  echo "herdr peers: catalog missing at $src" >&2
  exit 1
fi
mkdir -p "$(dirname "$dest")"
if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
  exit 0
fi
if [ -f "$dest" ]; then
  cp -p "$dest" "${dest}.bak"
fi
cp -p "$src" "$dest"
chmod 600 "$dest" 2>/dev/null || true
EOF
  chown "${user}:${user}" "${home}/.local/bin/herdr-refresh-catalog"
  chmod 755 "${home}/.local/bin/herdr-refresh-catalog"
  if [ ! -f "${src}" ]; then
    echo "herdr peers: catalog missing at ${src}; skip copy"
  else
    mkdir -p "${dest_dir}"
    if [ -f "${dest}" ]; then
      cp -p "${dest}" "${dest}.bak"
    fi
    cp -p "${src}" "${dest}"
    chown -R "${user}:${user}" "${dest_dir}" 2>/dev/null || true
    chmod 600 "${dest}" 2>/dev/null || true
  fi
  # Peers connect as host.docker.internal:<port>. The copied known_hosts only
  # has 127.0.0.1 from the Mac, so the first agent prompt dies on strict
  # checking. ssh-keyscan does not answer on these published ports, so accept
  # the key the same way a first SSH does. A peer that is down is skipped.
  if [ -f "${home}/.ssh_host/config.d/dailybot-peers" ]; then
    local known="${home}/.ssh/known_hosts"
    touch "${known}"
    chown "${user}:${user}" "${known}" 2>/dev/null || true
    awk '
      /^Host / { host=$2; port="" }
      /^[[:space:]]*Port / && host != "" { port=$2 }
      host != "" && port != "" {
        printf "%s %s\n", host, port
        host=""; port=""
      }
    ' "${home}/.ssh_host/config.d/dailybot-peers" | while read -r peer_host peer_port; do
      # Host is an SSH alias. known_hosts stores [host.docker.internal]:port.
      case "${peer_port}" in
        ''|*[!0-9]*) continue ;;
      esac
      # Primaries 22022-22032 (22032 is the Mac). Satellites 22400-22999.
      case "${peer_port}" in
        2202[2-9]|2203[0-2]|22[4-9][0-9][0-9]) ;;
        *) continue ;;
      esac
      if ssh-keygen -F "[host.docker.internal]:${peer_port}" -f "${known}" >/dev/null 2>&1; then
        continue
      fi
      # Dial the gateway directly. The peers file is host-mounted; never
      # interpolate its Host alias into a shell string.
      su -s /bin/bash "${user}" -c "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=4 -o PreferredAuthentications=publickey -p ${peer_port} host.docker.internal true" >/dev/null 2>&1 || true
    done
    chmod 600 "${known}" 2>/dev/null || true
  fi
}

install_herdr_peer_mesh "/home/dev-user" "dev-user"

# Same name as the Mac command. This repo's launcher lists the live agents.
# This repo's workspace is /workspace, not /app. Link whichever is mounted.
_dbdev_src=""
if [ -f /workspace/dev.sh ]; then
  _dbdev_src=/workspace/dev.sh
elif [ -f /app/dev.sh ]; then
  _dbdev_src=/app/dev.sh
fi
if [ -n "$_dbdev_src" ]; then
  # The entrypoint may already be dev-user. /usr/local/bin is root-owned.
  if [ "$(id -u)" = "0" ]; then
    ln -sfn "$_dbdev_src" /usr/local/bin/dbdev
  else
    sudo ln -sfn "$_dbdev_src" /usr/local/bin/dbdev
  fi
  chmod 755 "$_dbdev_src" 2>/dev/null || true
fi
unset _dbdev_src

# Start sshd so a Herdr client on the host can attach to this container as a
# saved machine. The compose file publishes container port 22 on
# 127.0.0.1:${HERDR_SSH_HOST_PORT} — loopback only, never every interface.
#
# Authentication is public-key only: every *.pub found in the read-only mount of
# the host's ~/.ssh is appended to authorized_keys. No password is ever accepted,
# and no private key is read for this purpose.
setup_sshd_for_herdr() {
    USER_HOME="$1"
    SSH_HOST_DIR="${USER_HOME}/.ssh_host"
    SSH_DIR="${USER_HOME}/.ssh"
    AUTHORIZED_KEYS="${SSH_DIR}/authorized_keys"

    if [ ! -x /usr/sbin/sshd ]; then
        echo "Warning: openssh-server is not installed; SSH into this container is unavailable."
        return 0
    fi

    mkdir -p "${SSH_DIR}"
    touch "${AUTHORIZED_KEYS}"
    if [ -d "${SSH_HOST_DIR}" ]; then
        for public_key in "${SSH_HOST_DIR}"/*.pub; do
            if [ -f "${public_key}" ] && ! grep -Fqx -f "${public_key}" "${AUTHORIZED_KEYS}" 2>/dev/null; then
                cat "${public_key}" >> "${AUTHORIZED_KEYS}"
                printf '\n' >> "${AUTHORIZED_KEYS}"
            fi
        done
    fi
    chmod 700 "${SSH_DIR}"
    chmod 600 "${AUTHORIZED_KEYS}"
    chown -R dev-user:dev-user "${SSH_DIR}"

    mkdir -p /var/run/sshd

    # Host keys live in the volume that already persists this container's state,
    # never in the image and never in /etc/ssh. Baking them shipped the PRIVATE
    # key inside the image layer; generating them into /etc/ssh at start would
    # mint a new identity on every recreate. Either way the client's pinned key
    # stops matching and the developer has to clear it by hand before Herdr can
    # attach. Generated once, they outlive both rebuilds and recreates.
    if [ "$(id -u)" = "0" ]; then SSH_SUDO=""; else SSH_SUDO="sudo"; fi
    HOST_KEY_DIR="${USER_HOME}/.herdr_data/ssh_host_keys"
    ${SSH_SUDO} mkdir -p "${HOST_KEY_DIR}"
    for key_type in rsa ecdsa ed25519; do
        # Tested through the same privilege the directory was created with: it is
        # 0700 root, so a plain [ -f ] from a non-root entrypoint always reads
        # false and the key gets regenerated on every start.
        if ! ${SSH_SUDO} test -f "${HOST_KEY_DIR}/ssh_host_${key_type}_key"; then
            echo "Generating a persistent SSH host key (${key_type})..."
            ${SSH_SUDO} ssh-keygen -q -t "${key_type}" -N '' -f "${HOST_KEY_DIR}/ssh_host_${key_type}_key"
        fi
    done
    # sshd refuses a host key that is group- or world-readable, or not its own.
    ${SSH_SUDO} chown root:root "${HOST_KEY_DIR}" "${HOST_KEY_DIR}"/ssh_host_*
    ${SSH_SUDO} chmod 700 "${HOST_KEY_DIR}"
    ${SSH_SUDO} chmod 600 "${HOST_KEY_DIR}"/ssh_host_*_key
    ${SSH_SUDO} chmod 644 "${HOST_KEY_DIR}"/ssh_host_*_key.pub
    printf 'HostKey %s/ssh_host_rsa_key\nHostKey %s/ssh_host_ecdsa_key\nHostKey %s/ssh_host_ed25519_key\n' \
        "${HOST_KEY_DIR}" "${HOST_KEY_DIR}" "${HOST_KEY_DIR}" \
        | ${SSH_SUDO} tee /etc/ssh/sshd_config.d/00-persistent-host-keys.conf >/dev/null

    # The drop-in must not redefine Subsystem sftp; the base config already has it.
    if [ -f /etc/ssh/sshd_config.d/herdr.conf ]; then
        sed -i '/^Subsystem[[:space:]]\+sftp/d' /etc/ssh/sshd_config.d/herdr.conf 2>/dev/null || true
    fi

    if /usr/sbin/sshd -t 2>/tmp/sshd-test.err; then
        /usr/sbin/sshd
        echo "SSH listening on container port 22 (published on the host as HERDR_SSH_HOST_PORT)"
    else
        echo "Warning: SSH server config invalid — attaching a Herdr machine will fail:"
        cat /tmp/sshd-test.err >&2 || true
    fi
}

setup_sshd_for_herdr "/home/dev-user"

# Execute the main command
exec "$@"
