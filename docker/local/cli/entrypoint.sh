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

# Execute the main command
exec "$@"
