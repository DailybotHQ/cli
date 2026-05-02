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

    # Build the prompt - simple format: path (git) $
    PS1="${yellow}\w${reset}${git_info}${white} \$ ${reset}"
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
