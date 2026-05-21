#!/bin/bash

# Dailybot Core CLI - Custom Commands
# This file is sourced in .bashrc for both root and dev-user

function print.success {
    GREEN="\033[0;32m"
    RESET="\033[0m"
    echo -e "${GREEN}$1${RESET}"
}

function print.error {
    RED="\033[0;31m"
    RESET="\033[0m"
    echo -e "${RED}$1${RESET}"
}

# Codex with full permissions (bypass approvals and sandbox)
# Usage:
#   codexx              - Start a new session
#   codexx -l|--last    - Resume the last session
#   codexx -r|--resume  - Interactive session selection
#   codexx -r <id>      - Resume a specific session by ID
function codexx() {
    local resume_mode=""
    local session_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -l|--last)
                resume_mode="last"
                shift
                ;;
            -r|--resume)
                resume_mode="resume"
                shift
                # Check if next argument is a session ID (not another flag)
                if [[ $# -gt 0 && ! "$1" =~ ^- ]]; then
                    session_id="$1"
                    shift
                fi
                ;;
            *)
                break
                ;;
        esac
    done

    case "$resume_mode" in
        last)
            print.success "Resuming last Codex session..."
            codex resume --last --dangerously-bypass-approvals-and-sandbox "$@"
            ;;
        resume)
            if [[ -n "$session_id" ]]; then
                print.success "Resuming Codex session: $session_id..."
                codex resume "$session_id" --dangerously-bypass-approvals-and-sandbox "$@"
            else
                print.success "Selecting Codex session to resume..."
                codex resume --all --dangerously-bypass-approvals-and-sandbox "$@"
            fi
            ;;
        *)
            print.success "Starting Codex with full permissions..."
            codex --dangerously-bypass-approvals-and-sandbox "$@"
            ;;
    esac
}

# Claude Code with full permissions (skip all permission prompts)
# Usage:
#   claudex               - Start a new session
#   claudex -c|--continue - Continue the most recent session
#   claudex -r|--resume   - Interactive session selection
#   claudex -r <id>       - Resume a specific session by ID
function claudex() {
    local resume_mode=""
    local session_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -c|--continue)
                resume_mode="continue"
                shift
                ;;
            -r|--resume)
                resume_mode="resume"
                shift
                # Check if next argument is a session ID (not another flag)
                if [[ $# -gt 0 && ! "$1" =~ ^- ]]; then
                    session_id="$1"
                    shift
                fi
                ;;
            *)
                break
                ;;
        esac
    done

    # Works when running as dev-user (non-root) which is the default in devcontainer
    case "$resume_mode" in
        continue)
            print.success "Continuing most recent Claude Code session..."
            claude --continue --dangerously-skip-permissions "$@"
            ;;
        resume)
            if [[ -n "$session_id" ]]; then
                print.success "Resuming Claude Code session: $session_id..."
                claude --resume "$session_id" --dangerously-skip-permissions "$@"
            else
                print.success "Selecting Claude Code session to resume..."
                claude --resume --dangerously-skip-permissions "$@"
            fi
            ;;
        *)
            print.success "Starting Claude Code with full permissions..."
            claude --dangerously-skip-permissions "$@"
            ;;
    esac
}

# Cursor CLI agent (interactive mode)
# Usage:
#   cursorx             - Start a new session
#   cursorx -l|--list   - List available sessions
#   cursorx -r|--resume - Resume the last session
#   cursorx -r <id>     - Resume a specific session by ID
# Note: Cursor CLI does not have a bypass permissions flag like Claude/Codex
#       It will prompt for approval on file modifications and shell commands
function cursorx() {
    local resume_mode=""
    local session_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -l|--list)
                resume_mode="list"
                shift
                ;;
            -r|--resume)
                resume_mode="resume"
                shift
                # Check if next argument is a session ID (not another flag)
                if [[ $# -gt 0 && ! "$1" =~ ^- ]]; then
                    session_id="$1"
                    shift
                fi
                ;;
            *)
                break
                ;;
        esac
    done

    # Cursor CLI uses 'agent' command - runs interactively by default
    case "$resume_mode" in
        list)
            print.success "Listing Cursor CLI sessions..."
            agent ls "$@"
            ;;
        resume)
            if [[ -n "$session_id" ]]; then
                print.success "Resuming Cursor CLI session: $session_id..."
                agent --resume="$session_id" "$@"
            else
                print.success "Resuming last Cursor CLI session..."
                agent resume "$@"
            fi
            ;;
        *)
            print.success "Starting Cursor CLI agent..."
            agent "$@"
            ;;
    esac
}

# Quality gates for the Dailybot CLI. Each function is a thin wrapper around
# a single underlying tool — you can run the tool directly (e.g. `pytest -x`)
# without sourcing this file. `codecheck` just calls them in sequence.
#
# Manual equivalents (run directly without these helpers):
#   ruff check dailybot_cli tests           # lint
#   ruff check --fix dailybot_cli tests     # lint with auto-fix
#   ruff format --check dailybot_cli tests  # format check (read-only)
#   ruff format dailybot_cli tests          # apply format
#   mypy dailybot_cli                       # type check
#   pytest -x                               # tests, stop on first failure

function lint() {
    print.success "Running ruff (lint check)..."
    ruff check dailybot_cli tests
}

function fix() {
    print.success "Running ruff --fix..."
    ruff check --fix dailybot_cli tests
    if [ $? != 0 ]; then
        print.error "⚠️ Ruff fix failed..."
        return 1
    fi

    print.success "Running ruff format (apply)..."
    ruff format dailybot_cli tests
}

function typecheck() {
    print.success "Running mypy..."
    mypy dailybot_cli
}

function codecheck() {
    fix
    if [ $? != 0 ]; then
        print.error "⚠️ Lint/format failed..."
        return 1
    fi

    typecheck
    if [ $? != 0 ]; then
        print.error "⚠️ Type checks failed..."
        return 1
    fi

    print.success "Running pytest -x..."
    pytest -x
}

function dev_install() {
    print.success "Installing dev extras from pyproject.toml ([dev])..."
    pip install -e ".[dev]"
}

# ============================================================================
# clitest — package smoke-test workspace manager
# ----------------------------------------------------------------------------
# Build the wheel, install it in a fresh isolated venv under /tmp/clitest.*,
# smoke-test the CLI, and DROP YOU INTO that venv (i.e. activate it in your
# current shell). Each invocation creates a new env; older ones stick around
# under /tmp/clitest.* until you `clitest clean` (or `clean --all`).
#
# Subcommands:
#   clitest [--env local] [--port N] [--api-url URL]  Build + activate (default: live).
#   clitest env                                       Show default/local/custom options.
#   clitest-local [--port N]                          Shortcut for --env local.
#
# Defaults: live API (https://api.dailybot.com). Local uses djangovscode:8000 in the
# devcontainer; override host/port via flags or CLITEST_LOCAL_* in cli/.env.
# Private URLs (dev/staging) → pass --api-url explicitly (never hardcoded here).
# ============================================================================

CLITEST_BASE_DIR="${CLITEST_BASE_DIR:-/tmp}"
CLITEST_PREFIX="clitest"
CLITEST_LATEST_LINK="${CLITEST_BASE_DIR}/${CLITEST_PREFIX}.latest"
CLITEST_LIVE_API_URL="${CLITEST_LIVE_API_URL:-https://api.dailybot.com}"
CLITEST_API_URL=""
CLITEST_ENV_NAME=""
CLITEST_LOCAL_HOST_FLAG=""
CLITEST_LOCAL_PORT_FLAG=""
CLITEST_RESOLVED_API_URL=""
CLITEST_RESOLVED_ENV_NAME=""
CLITEST_ARGS=()

function _clitest_local_api_url() {
    local host port
    host="${CLITEST_LOCAL_HOST_FLAG:-${CLITEST_LOCAL_HOST:-djangovscode}}"
    port="${CLITEST_LOCAL_PORT_FLAG:-${CLITEST_LOCAL_PORT:-8000}}"
    if [[ ! "$port" =~ ^[0-9]+$ ]]; then
        print.error "Invalid --port: must be a number (got: $port)"
        return 1
    fi
    echo "http://${host}:${port}"
}

function _clitest_parse_global_flags() {
    CLITEST_API_URL=""
    CLITEST_ENV_NAME=""
    CLITEST_LOCAL_HOST_FLAG=""
    CLITEST_LOCAL_PORT_FLAG=""
    CLITEST_ARGS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --api-url)
                if [[ -z "${2:-}" ]]; then
                    print.error "--api-url requires a URL argument."
                    return 2
                fi
                CLITEST_API_URL="$2"
                shift 2
                ;;
            --api-url=*)
                CLITEST_API_URL="${1#*=}"
                shift
                ;;
            --env|--environment|-e)
                if [[ -z "${2:-}" ]]; then
                    print.error "--env requires a name (only 'local' is built-in)."
                    return 2
                fi
                CLITEST_ENV_NAME="${2,,}"
                shift 2
                ;;
            --env=*|--environment=*)
                CLITEST_ENV_NAME="${1#*=}"
                CLITEST_ENV_NAME="${CLITEST_ENV_NAME,,}"
                shift
                ;;
            --port|-p)
                if [[ -z "${2:-}" ]]; then
                    print.error "--port requires a port number."
                    return 2
                fi
                CLITEST_LOCAL_PORT_FLAG="$2"
                shift 2
                ;;
            --port=*)
                CLITEST_LOCAL_PORT_FLAG="${1#*=}"
                shift
                ;;
            --local-host)
                if [[ -z "${2:-}" ]]; then
                    print.error "--local-host requires a hostname."
                    return 2
                fi
                CLITEST_LOCAL_HOST_FLAG="$2"
                shift 2
                ;;
            --local-host=*)
                CLITEST_LOCAL_HOST_FLAG="${1#*=}"
                shift
                ;;
            *)
                CLITEST_ARGS+=("$1")
                shift
                ;;
        esac
    done
}

function _clitest_resolve_api_target() {
    CLITEST_RESOLVED_API_URL=""
    CLITEST_RESOLVED_ENV_NAME=""

    if [[ -n "$CLITEST_API_URL" && -n "$CLITEST_ENV_NAME" ]]; then
        print.error "Use either --env local or --api-url, not both."
        return 2
    fi

    if [[ -n "$CLITEST_LOCAL_PORT_FLAG" || -n "$CLITEST_LOCAL_HOST_FLAG" ]] \
        && [[ "$CLITEST_ENV_NAME" != "local" ]]; then
        print.error "--port and --local-host require --env local."
        return 2
    fi

    if [[ -n "$CLITEST_ENV_NAME" ]]; then
        if [[ "$CLITEST_ENV_NAME" != "local" ]]; then
            print.error "Unknown environment: $CLITEST_ENV_NAME"
            echo "  Built-in: local (--env local or clitest-local)"
            echo "  Default:  live (omit flags, or run plain 'clitest')"
            echo "  Custom:   clitest --api-url https://your-api.example.com"
            return 2
        fi
        local local_url=""
        local_url="$(_clitest_local_api_url)" || return 2
        CLITEST_RESOLVED_API_URL="$local_url"
        CLITEST_RESOLVED_ENV_NAME="local"
    elif [[ -n "$CLITEST_API_URL" ]]; then
        CLITEST_RESOLVED_API_URL="$CLITEST_API_URL"
    else
        CLITEST_RESOLVED_API_URL="$CLITEST_LIVE_API_URL"
        CLITEST_RESOLVED_ENV_NAME="live"
    fi
}

function _clitest_normalize_api_url() {
    local url="${1%/}"
    if [[ ! "$url" =~ ^https?:// ]]; then
        print.error "Invalid API URL: must start with http:// or https:// (got: $1)"
        return 1
    fi
    echo "$url"
}

function _clitest_configure_environment() {
    local venv_dir="$1"
    local api_url="$2"
    local env_name="${3:-}"
    local activate_script="$venv_dir/bin/activate"
    local hook_marker="clitest dailybot api url hook"

    printf '%s\n' "$api_url" > "$venv_dir/.dailybot_api_url"
    if [[ -n "$env_name" ]]; then
        printf '%s\n' "$env_name" > "$venv_dir/.dailybot_env"
    else
        rm -f "$venv_dir/.dailybot_env"
    fi

    # Python 3.14 venv activate no longer sources bin/activate.d — append directly.
    if [[ -f "$activate_script" ]] && ! grep -q "$hook_marker" "$activate_script" 2>/dev/null; then
        cat >> "$activate_script" <<'EOF'

# >>> clitest dailybot api url hook >>>
if [[ -n "${VIRTUAL_ENV:-}" && -f "${VIRTUAL_ENV}/.dailybot_api_url" ]]; then
    export DAILYBOT_API_URL="$(tr -d '\n\r' < "${VIRTUAL_ENV}/.dailybot_api_url")"
fi
if [[ -n "${VIRTUAL_ENV:-}" && -f "${VIRTUAL_ENV}/.dailybot_env" ]]; then
    export CLITEST_DAILYBOT_ENV="$(tr -d '\n\r' < "${VIRTUAL_ENV}/.dailybot_env")"
fi
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    export DAILYBOT_CONFIG_DIR="${VIRTUAL_ENV}/.dailybot-config"
    mkdir -p "${DAILYBOT_CONFIG_DIR}"
fi
# <<< clitest dailybot api url hook <<<
EOF
    fi
}

function _clitest_read_api_url() {
    local venv_dir="$1"
    if [[ -f "$venv_dir/.dailybot_api_url" ]]; then
        tr -d '\n\r' < "$venv_dir/.dailybot_api_url"
    fi
}

function _clitest_read_env_name() {
    local venv_dir="$1"
    if [[ -f "$venv_dir/.dailybot_env" ]]; then
        tr -d '\n\r' < "$venv_dir/.dailybot_env"
    fi
}

function _clitest_env_list() {
    local local_url=""
    local_url="$(_clitest_local_api_url)" || return 1
    echo "clitest API targets:"
    echo ""
    printf "  %-10s  %s\n" "TARGET" "API URL"
    printf "  %-10s  %s\n" "----------" "----------------------------------------------"
    printf "  %-10s  %s  (default — plain 'clitest')\n" "live" "$CLITEST_LIVE_API_URL"
    printf "  %-10s  %s\n" "local" "$local_url"
    printf "  %-10s  %s\n" "custom" "--api-url URL"
    echo ""
    echo "Local overrides:"
    echo "  --port / -p PORT           default port: ${CLITEST_LOCAL_PORT:-8000}"
    echo "  --local-host HOST          default host: ${CLITEST_LOCAL_HOST:-djangovscode}"
    echo "  CLITEST_LOCAL_PORT / CLITEST_LOCAL_HOST in docker/local/cli/.env"
    echo ""
    echo "Examples:"
    echo "  clitest                              # live (production API)"
    echo "  clitest-local                        # local Django in devcontainer"
    echo "  clitest-local --port 8600            # local on a custom port"
    echo "  clitest --api-url https://your-api.example.com"
}

function clitest() {
    _clitest_parse_global_flags "$@" || return $?
    _clitest_resolve_api_target || return $?

    if [[ ${#CLITEST_ARGS[@]} -eq 0 ]]; then
        _clitest_create "${CLITEST_RESOLVED_API_URL:-}" "${CLITEST_RESOLVED_ENV_NAME:-}"
        return $?
    fi

    local subcmd="${CLITEST_ARGS[0]}"
    case "$subcmd" in
        create)
            _clitest_create "${CLITEST_RESOLVED_API_URL:-}" "${CLITEST_RESOLVED_ENV_NAME:-}"
            ;;
        env)
            if [[ ${#CLITEST_ARGS[@]} -eq 1 ]]; then
                _clitest_env_list
            elif [[ ${#CLITEST_ARGS[@]} -eq 2 && "${CLITEST_ARGS[1],,}" == "local" ]]; then
                CLITEST_ENV_NAME="local"
                _clitest_resolve_api_target || return 2
                _clitest_create "$CLITEST_RESOLVED_API_URL" "$CLITEST_RESOLVED_ENV_NAME"
            else
                print.error "Usage: clitest env   |   clitest env local"
                return 2
            fi
            ;;
        clean)
            _clitest_clean "${CLITEST_ARGS[@]:1}"
            ;;
        exec|attach)
            _clitest_exec "${CLITEST_RESOLVED_API_URL:-}" "${CLITEST_RESOLVED_ENV_NAME:-}" \
                "${CLITEST_ARGS[@]:1}"
            ;;
        list|ls)
            _clitest_list
            ;;
        help|-h|--help)
            _clitest_help
            ;;
        *)
            print.error "Unknown subcommand: $subcmd"
            echo "Run 'clitest help' for usage."
            return 2
            ;;
    esac
}

function clitest-local() {
    clitest --env local "$@"
}

function _clitest_help() {
    cat <<'EOF'
clitest — package smoke-test workspace manager.

Usage:
  clitest [create] [--env local] [--port N] [--local-host HOST]
          [--api-url URL]
                        Build the wheel, install it in a fresh venv under
                          /tmp/clitest.XXXXXX, smoke-test, and ACTIVATE that
                          venv in your current shell.
                        Default API target: live (https://api.dailybot.com).
                        DAILYBOT_API_URL is exported on activate.

  clitest env           List built-in targets (live, local) and --api-url usage.

  clitest list          Show all sandboxes (path, env, API URL, tags).

  clitest exec [--env local | --api-url URL] [--port N] [TARGET]
                        Re-attach to an existing sandbox (default: latest).

  clitest clean         Deactivate and delete the current sandbox.
  clitest clean --all   Remove every /tmp/clitest.* sandbox.

  clitest help          Show this help.

Shortcut:
  clitest-local [--port N] [--local-host HOST]
                        Same as: clitest --env local

Inside an active clitest venv your shell prompt shows `(clitest.XXXXXX)`
to remind you you're in a sandbox, not the editable /workspace install.

Typical flow:
  $ clitest                              # smoke-test against live API
  (clitest.io98bF) $ dailybot login --email me@example.com

  $ clitest-local                        # local Django (djangovscode:8000)
  (clitest.io98bF) $ dailybot login --email me@example.com

  $ clitest --api-url https://your-api.example.com   # private/staging/dev
  ...
  (clitest.io98bF) $ clitest clean
EOF
}

# Returns 0 (and echoes path) iff $VIRTUAL_ENV currently points at a clitest
# venv. Returns 1 if not in any clitest venv (possibly in another venv).
function _clitest_active_venv() {
    if [[ -n "${VIRTUAL_ENV:-}" && "$VIRTUAL_ENV" == "${CLITEST_BASE_DIR}/${CLITEST_PREFIX}".* ]]; then
        echo "$VIRTUAL_ENV"
        return 0
    fi
    return 1
}

# List all clitest venv paths, sorted by mtime (newest first), excluding the
# `latest` symlink itself.
function _clitest_list_paths() {
    ls -dt "${CLITEST_BASE_DIR}/${CLITEST_PREFIX}".*/ 2>/dev/null \
        | sed 's:/$::' \
        | grep -v "${CLITEST_PREFIX}\.latest$"
}

function _clitest_create() {
    local api_url="${1:-}"
    local env_name="${2:-}"
    local project_root venv_dir wheel normalized_api_url=""
    project_root="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"

    # If currently in a non-clitest venv, refuse — don't trample user's env.
    if [[ -n "${VIRTUAL_ENV:-}" ]] && ! _clitest_active_venv >/dev/null; then
        print.error "You're already inside a non-clitest venv: $VIRTUAL_ENV"
        echo "  Run 'deactivate' first, then re-run 'clitest'."
        return 1
    fi

    # If in a clitest venv, deactivate it (don't delete — user might still need it)
    if _clitest_active_venv >/dev/null; then
        print.success "Leaving current clitest venv before creating a new one..."
        deactivate 2>/dev/null || true
    fi

    venv_dir="$(mktemp -d -t "${CLITEST_PREFIX}.XXXXXX")"

    print.success "1/5 — Building sdist + wheel..."
    (cd "$project_root" && rm -rf dist/ build/ && python -m build) || {
        print.error "⚠️  Build failed."
        rm -rf "$venv_dir"
        return 1
    }

    print.success "2/5 — Validating package metadata (twine check)..."
    (cd "$project_root" && twine check dist/*) || {
        print.error "⚠️  twine check failed."
        rm -rf "$venv_dir"
        return 1
    }

    print.success "3/5 — Creating clean venv at $venv_dir ..."
    python -m venv "$venv_dir" || { rm -rf "$venv_dir"; return 1; }

    wheel="$(ls "$project_root"/dist/dailybot_cli-*-py3-none-any.whl 2>/dev/null | head -n1)"
    if [ -z "$wheel" ]; then
        print.error "⚠️  No wheel found under dist/."
        rm -rf "$venv_dir"
        return 1
    fi

    print.success "4/5 — Installing wheel into the clean venv..."
    "$venv_dir/bin/pip" install --upgrade pip --quiet || { rm -rf "$venv_dir"; return 1; }
    "$venv_dir/bin/pip" install "$wheel" --quiet || {
        print.error "⚠️  Wheel install failed."
        rm -rf "$venv_dir"
        return 1
    }

    print.success "5/5 — Smoke-testing the installed CLI..."
    if ! "$venv_dir/bin/dailybot" --version >/dev/null 2>&1; then
        print.error "⚠️  dailybot --version failed inside the venv."
        rm -rf "$venv_dir"
        return 1
    fi
    local subcommand
    for subcommand in login logout status update config agent checkin form kudos; do
        if ! "$venv_dir/bin/dailybot" "$subcommand" --help >/dev/null 2>&1; then
            print.error "⚠️  '$subcommand --help' failed — wheel may be missing files."
            rm -rf "$venv_dir"
            return 1
        fi
    done

    if [[ -n "$api_url" ]]; then
        normalized_api_url="$(_clitest_normalize_api_url "$api_url")" || {
            rm -rf "$venv_dir"
            return 1
        }
        _clitest_configure_environment "$venv_dir" "$normalized_api_url" "$env_name"
    fi

    # Update the "latest" symlink so other terminals can `clitest exec` into it.
    rm -f "$CLITEST_LATEST_LINK"
    ln -s "$venv_dir" "$CLITEST_LATEST_LINK"

    echo ""
    print.success "✅ Package built and verified — entering venv now..."
    echo "    Path:           $venv_dir"
    echo "    dailybot:       $("$venv_dir/bin/dailybot" --version 2>&1 | head -1)"
    if [[ -n "$env_name" ]]; then
        echo "    Environment:    $env_name"
    fi
    if [[ -n "$normalized_api_url" ]]; then
        echo "    API URL:        $normalized_api_url"
        echo "    dailybot uses DAILYBOT_API_URL automatically in this venv."
        echo "    Credentials:    isolated in \$VIRTUAL_ENV/.dailybot-config"
        echo "                    Run: dailybot login  (sandbox session, not live)"
    fi
    echo ""
    echo "    Run 'clitest clean' when done, or 'clitest list' to see all envs."
    echo ""

    # Activate in the caller's interactive shell.
    # shellcheck disable=SC1091
    source "$venv_dir/bin/activate"
}

function _clitest_clean() {
    if [[ "${1:-}" == "--all" ]]; then
        if _clitest_active_venv >/dev/null; then
            deactivate 2>/dev/null || true
        fi
        local v removed=0
        for v in "${CLITEST_BASE_DIR}/${CLITEST_PREFIX}".*; do
            [[ -d "$v" ]] || continue
            rm -rf "$v"
            removed=$((removed + 1))
        done
        rm -f "$CLITEST_LATEST_LINK"
        if [[ $removed -gt 0 ]]; then
            print.success "Removed $removed clitest env(s)."
        else
            echo "No clitest envs to remove."
        fi
        return 0
    fi

    local target
    if target="$(_clitest_active_venv)"; then
        print.success "Deactivating $target ..."
        deactivate 2>/dev/null || true
    elif [[ -L "$CLITEST_LATEST_LINK" ]]; then
        target="$(readlink -f "$CLITEST_LATEST_LINK")"
    else
        print.error "Not in a clitest venv and no clitest.latest exists."
        echo "  Run 'clitest list' to see what's available, or 'clitest' to create one."
        return 1
    fi

    if [[ -d "$target" ]]; then
        print.success "Removing $target ..."
        rm -rf "$target"
    fi

    # If the latest symlink was pointing at this env (or is now broken), drop it.
    if [[ -L "$CLITEST_LATEST_LINK" ]]; then
        local latest_target
        latest_target="$(readlink -f "$CLITEST_LATEST_LINK" 2>/dev/null || echo "")"
        if [[ -z "$latest_target" || "$latest_target" == "$target" || ! -d "$latest_target" ]]; then
            rm -f "$CLITEST_LATEST_LINK"
        fi
    fi

    echo "Done."
}

function _clitest_exec() {
    local api_url="${1:-}"
    local env_name="${2:-}"
    shift 2
    local target="${1:-}" venv_path normalized_api_url="" stored_api_url="" stored_env_name=""

    if [[ -n "$api_url" ]]; then
        normalized_api_url="$(_clitest_normalize_api_url "$api_url")" || return 1
    fi

    if [[ -z "$target" ]]; then
        if [[ ! -L "$CLITEST_LATEST_LINK" ]]; then
            print.error "No clitest.latest exists."
            echo "  Run 'clitest' to create one, or 'clitest list' to see existing envs."
            return 1
        fi
        venv_path="$(readlink -f "$CLITEST_LATEST_LINK")"
    elif [[ "$target" =~ ^[0-9]+$ ]]; then
        venv_path="$(_clitest_list_paths | sed -n "${target}p")"
        if [[ -z "$venv_path" ]]; then
            print.error "No clitest env at index $target. Run 'clitest list' first."
            return 1
        fi
    else
        venv_path="$target"
    fi

    if [[ ! -d "$venv_path" || ! -f "$venv_path/bin/activate" ]]; then
        print.error "$venv_path does not look like a venv."
        return 1
    fi

    # Already attached to that exact one? No-op.
    if [[ "${VIRTUAL_ENV:-}" == "$venv_path" ]]; then
        echo "Already in $venv_path."
        return 0
    fi

    if [[ -n "$normalized_api_url" ]]; then
        _clitest_configure_environment "$venv_path" "$normalized_api_url" "$env_name"
    fi

    stored_api_url="$(_clitest_read_api_url "$venv_path")"
    stored_env_name="$(_clitest_read_env_name "$venv_path")"

    # In some other venv (clitest or not) — leave it first
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        deactivate 2>/dev/null || true
    fi

    print.success "Activating $venv_path ..."
    if [[ -n "$stored_env_name" ]]; then
        echo "    Environment:    $stored_env_name"
    fi
    if [[ -n "$stored_api_url" ]]; then
        echo "    API URL:        $stored_api_url"
    fi
    # shellcheck disable=SC1091
    source "$venv_path/bin/activate"
}

function _clitest_list() {
    local count=0 path latest_target="" current=""
    if [[ -L "$CLITEST_LATEST_LINK" ]]; then
        latest_target="$(readlink -f "$CLITEST_LATEST_LINK" 2>/dev/null || echo "")"
    fi
    current="$(_clitest_active_venv 2>/dev/null || true)"

    printf "%-3s  %-28s  %-8s  %-5s  %-8s  %-18s  %s\n" \
        "#" "Path" "Created" "Size" "Env" "API URL" "Tags"
    printf '%s\n' "--------------------------------------------------------------------------------------------------------------"
    while IFS= read -r path; do
        [[ -z "$path" ]] && continue
        count=$((count + 1))
        local created size tags="" api_display="" api_url="" env_display=""
        created="$(date -r "$path" '+%H:%M:%S' 2>/dev/null || echo "?")"
        size="$(du -sh "$path" 2>/dev/null | cut -f1)"
        api_url="$(_clitest_read_api_url "$path")"
        env_display="$(_clitest_read_env_name "$path")"
        [[ -z "$env_display" ]] && env_display="-"
        if [[ -n "$api_url" ]]; then
            api_display="${api_url#http://}"
            api_display="${api_display#https://}"
        else
            api_display="-"
        fi
        [[ "$path" == "$latest_target" ]] && tags="${tags}latest "
        [[ "$path" == "$current" ]] && tags="${tags}active"
        printf "%-3s  %-28s  %-8s  %-5s  %-8s  %-18s  %s\n" \
            "$count" "$path" "$created" "$size" "$env_display" "$api_display" "${tags% }"
    done < <(_clitest_list_paths)

    if [[ $count -eq 0 ]]; then
        echo "  (no envs — run 'clitest' to create one)"
    fi
}

# ============================================================================
# Dependency lock-file workflow (pip-tools)
# ----------------------------------------------------------------------------
# Mirrors the api-services pattern adapted to setuptools + PEP 621:
#   - pyproject.toml is the source of truth for dep ranges
#   - requirements/base.txt + requirements/dev.txt are the locked outputs
#   - The Dockerfile installs from requirements/dev.txt for reproducible builds
# Run `pip_update` after changing dependencies in pyproject.toml.
# ============================================================================

function pip_update() {
    print.success "Recompiling requirements/base.txt from [project.dependencies]..."
    if pip-compile --quiet --strip-extras --output-file=requirements/base.txt pyproject.toml; then
        print.success "Recompiling requirements/dev.txt from [project.dependencies] + [dev]..."
        if pip-compile --quiet --strip-extras --extra=dev --output-file=requirements/dev.txt pyproject.toml; then
            print.success "Syncing local environment to requirements/dev.txt..."
            pip-sync requirements/dev.txt
        else
            print.error "⚠️ Compiling dev.txt failed."
            return 1
        fi
    else
        print.error "⚠️ Compiling base.txt failed."
        return 1
    fi
}

# Show outdated installed packages (analogous to api-services' `pso` =
# `poetry show -o`). Pipe through column for readability.
alias pso='pip list --outdated'

# Check if running inside Docker container
function check_devcontainer() {
    if [[ -f /.dockerenv ]] || [[ -n "${REMOTE_CONTAINERS:-}" ]] || [[ -n "${CODESPACES:-}" ]]; then
        print.success "✅ Running inside Docker container"
        echo ""
        echo "All development commands are available."
        return 0
    else
        print.error "❌ NOT running inside Docker container"
        echo ""
        echo "⚠️  WARNING: This project can run in a Docker container environment."
        echo "   To work with this project in Docker:"
        echo "   1. Start Docker services: cd docker/local && docker compose up -d"
        echo "   2. Access the container: docker compose exec clivscode /bin/bash"
        echo "   3. Or use VS Code Dev Containers if configured"
        return 1
    fi
}

# ================================
# Git-aware Bash Prompt
# ================================

# Function to get current git branch
function git_branch() {
    local branch
    if branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null); then
        if [[ "$branch" == "HEAD" ]]; then
            branch='detached*'
        fi
        echo "$branch"
    fi
}

# Function to get git status indicators
function git_status_indicator() {
    local git_status
    git_status=$(git status --porcelain 2>/dev/null)

    if [[ -n "$git_status" ]]; then
        echo "*"  # Asterisk for uncommitted changes
    fi
}

# Custom PS1 prompt with colors and git info
function set_bash_prompt() {
    local exit_code=$?

    # Color codes
    local yellow="\[\033[0;33m\]"
    local red="\[\033[0;31m\]"
    local green="\[\033[0;32m\]"
    local magenta="\[\033[0;35m\]"
    local white="\[\033[0;37m\]"
    local reset="\[\033[0m\]"

    # Get git branch and status
    local git_info=""
    if git rev-parse --git-dir > /dev/null 2>&1; then
        local branch
        branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

        if [[ "$branch" == "HEAD" ]]; then
            branch='detached*'
        fi

        # Check if there are uncommitted changes
        if [[ -n $(git status --porcelain 2>/dev/null) ]]; then
            git_info=" ${red}(${branch}*)${reset}"
        else
            git_info=" ${green}(${branch})${reset}"
        fi
    fi

    # Show active venv (clitest sandbox or any other) so it's obvious which
    # `dailybot` you're running. The standard venv activate script's PS1 hack
    # gets blown away by PROMPT_COMMAND, so we re-derive it here.
    local venv_info=""
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        local venv_basename
        venv_basename="$(basename "$VIRTUAL_ENV")"
        venv_info=" ${magenta}(${venv_basename})${reset}"
    fi

    # Build the prompt - simple format: path (git) (venv) $
    PS1="${yellow}\w${reset}${git_info}${venv_info}${white} \$ ${reset}"
}

# Set the custom prompt
PROMPT_COMMAND=set_bash_prompt

# ================================
# Useful Git Aliases
# ================================

alias gs='git status'
alias ga='git add .'
alias gc='git commit -am'
alias gp='git push -u origin HEAD'
alias gl='git log --oneline --graph --decorate --all -20'
alias gd='git diff'
alias gb='git for-each-ref --sort=-committerdate refs/heads/ --format="%(HEAD) %(color:yellow)%(refname:short)%(color:reset) - %(color:green)%(committerdate:relative)%(color:reset) - %(color:blue)%(authorname)%(color:reset)"'
alias gbd='git branch -D'
alias gco='git checkout'
alias gcob='git checkout -b'
alias gpl='git pull origin HEAD'
alias grc='git rm -r --cached .'

# ================================
# Useful Aliases
# ================================

alias help='show_welcome'
alias ll='ls -la'
alias la='ls -A'
alias l='ls -CF'

# Welcome message
function show_welcome() {
    echo ""
    print.success "🚀 Dailybot Core CLI - Development Container"
    echo ""

    # Check container status
    check_devcontainer
    echo ""

    echo "This is the documentation and coordination hub for the Dailybot ecosystem."
    echo ""
    echo "Useful commands:"
    echo "  • check_devcontainer   - Check if running inside Docker container"
    echo "  • help                 - Show this message"
    echo ""
    echo "Quality gates (each runs a single tool — chain manually or use codecheck):"
    echo "  • lint                 - ruff check dailybot_cli tests (read-only)"
    echo "  • fix                  - ruff --fix + ruff format (rewrites in place)"
    echo "  • typecheck            - mypy dailybot_cli"
    echo "  • codecheck            - fix → typecheck → pytest -x (full sequence)"
    echo ""
    echo "Dependency management (pip-tools):"
    echo "  • pip_update           - Recompile requirements/{base,dev}.txt + sync env"
    echo "  • pso                  - List outdated installed packages"
    echo "  • dev_install          - pip install -e \".[dev]\" (one-shot)"
    echo ""
    echo "Package release smoke test (clitest — sandbox manager):"
    echo "  • clitest                  - build wheel → venv → smoke-test → live API (default)"
    echo "  • clitest-local [--port N] - same, pinned to local Django (djangovscode:8000)"
    echo "  • clitest --api-url URL    - same, pinned to a custom API base URL"
    echo "  • clitest env              - show live/local/custom targets"
    echo "  • clitest list             - table of sandboxes (#, env, API URL, tags)"
    echo "  • clitest exec [N|PATH]    - re-attach to an existing sandbox"
    echo "  • clitest clean            - deactivate + remove the current sandbox"
    echo "  • clitest clean --all      - remove every /tmp/clitest.*"
    echo "  • clitest help             - detailed help"
    echo ""
    echo "AI Assistant commands:"
    echo "  • claude            - Claude Code CLI"
    echo "  • codex             - Codex CLI"
    echo "  • agent             - Cursor CLI agent"
    echo ""
    echo "  Enhanced wrappers (with full permissions):"
    echo "  • codexx            - Codex with full permissions"
    echo "      -l, --last      Resume last session"
    echo "      -r, --resume    Interactive session selection (or -r <id> for specific)"
    echo "  • claudex           - Claude Code with full permissions"
    echo "      -c, --continue  Continue most recent session"
    echo "      -r, --resume    Interactive session selection (or -r <id> for specific)"
    echo "  • cursorx           - Cursor CLI agent"
    echo "      -l, --list      List available sessions"
    echo "      -r, --resume    Resume last session (or -r <id> for specific)"
    echo ""
    echo "Git shortcuts:"
    echo "  • gs   - git status"
    echo "  • ga   - git add ."
    echo "  • gc   - git commit"
    echo "  • gp   - git push -u origin HEAD"
    echo "  • gpl  - git pull origin HEAD"
    echo "  • gl   - git log (pretty)"
    echo "  • gd   - git diff"
    echo "  • gb   - git branch"
    echo "  • gbd  - git branch -D"
    echo "  • gco  - git checkout"
    echo "  • gcob - git checkout -b"
    echo "  • grc  - git rm -r --cached . (reset cache, useful after updating .gitignore)"
    echo ""
    echo "Sub-projects (navigate to repositories/<name>/):"
    echo "  Internal (private):"
    echo "    • api-services/         - Django API backend"
    echo "    • chatbot-functions/    - Serverless chatbot handlers"
    echo "    • web-app/              - Vue 3 web application"
    echo "    • discord-gateway/      - Discord bot gateway"
    echo "    • dailybot.com/         - Marketing website (Astro)"
    echo "    • e2e-playwright/       - End-to-end test suite"
    echo "    • labs-projects/        - Experimental projects"
    echo "    • msteams-app-manifesto/- MS Teams app manifest"
    echo ""
    echo "  Public OSS (MIT):"
    echo "    • cli/                  - Dailybot Python CLI (PyPI: dailybot-cli)"
    echo "    • agent-skill/          - AI agent skill pack (skills.sh / OpenClaw)"
    echo ""
}

# Show welcome message only for interactive shells
if [[ $- == *i* ]]; then
    show_welcome
fi
