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
    awk -v cwd="${HERDR_CWD}" '
        function keyname(l,  k) { k = l; sub(/[[:space:]]*=.*/, "", k); gsub(/[[:space:]]/, "", k); return k }
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
                if (!done) {
                    print "[terminal]"
                    if (!("new_cwd" in seen))    printf "new_cwd = \"%s\"\n", cwd
                    if (!("shell_mode" in seen)) print "shell_mode = \"non_login\""
                    for (i = 1; i <= n; i++) print order[i]
                    print ""
                    done = 1
                }
                next
            }
            if ($0 ~ /^\[/) { skip = 0 }
            if (skip) next
            print
        }
        END {
            if (!done) {
                print ""
                print "[terminal]"
                printf "new_cwd = \"%s\"\n", cwd
                print "shell_mode = \"non_login\""
            }
        }
    ' "${HERDR_CONFIG}" "${HERDR_CONFIG}" > "${HERDR_CONFIG}.tmp" && mv "${HERDR_CONFIG}.tmp" "${HERDR_CONFIG}"
}
ensure_herdr_terminal_defaults

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
    if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
        echo "Generating SSH host keys..."
        ssh-keygen -A
    fi

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
