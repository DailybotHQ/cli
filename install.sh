#!/usr/bin/env bash
# DailyBot CLI installer
# Usage: curl -sSL https://cli.dailybot.com/install.sh | bash
#
# macOS  → Homebrew (brew install dailybothq/tap/dailybot)
# Linux  → Pre-built binary, fallback to pip
# Others → pip install

set -euo pipefail

REPO="DailyBotHQ/cli"
PACKAGE="dailybot-cli"
COMMAND="dailybot"
MIN_PYTHON="3.10"

# --- Helpers ---

has() { command -v "$1" &>/dev/null; }

info()    { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
success() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn()    { printf '\033[1;33m==>\033[0m %s\n' "$*" >&2; }
error()   { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; }

finish() {
    echo ""
    if has "$COMMAND"; then
        ver=$($COMMAND --version 2>&1) && rc=$? || rc=$?
        if [ $rc -eq 0 ]; then
            success "DailyBot CLI installed successfully! ($ver)"
        else
            warn "DailyBot CLI was installed but may not be working correctly."
            warn "Running 'dailybot --version' failed:"
            echo "  $ver"
            echo ""
            echo "  Try: pip install --force-reinstall dailybot-cli"
        fi
    else
        success "DailyBot CLI installed successfully!"
        warn "The '$COMMAND' command is not on your PATH yet."
        echo "  You may need to restart your terminal or add the install directory to PATH."
    fi
    echo ""
    echo "  Get started:"
    echo "    dailybot login"
    echo "    dailybot --help"
    echo ""
}

# --- Detect OS ---

OS="$(uname -s)"

# =============================================================================
# macOS → Homebrew
# =============================================================================
if [ "$OS" = "Darwin" ]; then
    if ! has brew; then
        error "Homebrew is required on macOS."
        echo ""
        echo "  Install Homebrew first:"
        echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        echo ""
        echo "  Then re-run this script."
        exit 1
    fi

    info "Installing via Homebrew..."
    brew install dailybothq/tap/dailybot
    finish
    exit 0
fi

# =============================================================================
# Linux → Binary download, fallback to pip
# =============================================================================
if [ "$OS" = "Linux" ]; then
    install_binary() {
        local latest url status_code install_dir="/usr/local/bin"
        local arch
        arch="$(uname -m)"

        # Only x86_64 binary is available; skip on other architectures
        if [ "$arch" != "x86_64" ]; then
            warn "Pre-built binary is only available for x86_64 (detected: $arch)."
            return 1
        fi

        latest=$(curl -sI "https://github.com/$REPO/releases/latest" \
            | grep -i "^location:" | sed 's/.*tag\///' | tr -d '\r\n')

        if [ -z "$latest" ]; then
            return 1
        fi

        url="https://github.com/$REPO/releases/download/$latest/dailybot-linux-x86_64"

        status_code=$(curl -sI -o /dev/null -w "%{http_code}" "$url")
        if [ "$status_code" != "200" ] && [ "$status_code" != "302" ]; then
            return 1
        fi

        info "Downloading dailybot ($latest) for Linux..."
        curl -sL "$url" -o "/tmp/$COMMAND"
        chmod +x "/tmp/$COMMAND"

        info "Installing to $install_dir/$COMMAND..."
        if [ -w "$install_dir" ]; then
            mv "/tmp/$COMMAND" "$install_dir/$COMMAND"
        else
            sudo mv "/tmp/$COMMAND" "$install_dir/$COMMAND"
        fi
        return 0
    }

    if install_binary; then
        finish
        exit 0
    fi

    warn "Binary download failed. Falling back to pip..."
fi

# =============================================================================
# Fallback: pip-based install (Linux fallback + Windows + other)
# =============================================================================

in_virtualenv() {
    "$PYTHON" -c "import sys; sys.exit(0 if (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)) else 1)" 2>/dev/null
}

PYTHON=""
for cmd in python3 python; do
    if has "$cmd"; then
        ok=$("$cmd" -c "
import sys
v = sys.version_info
print('yes' if v >= (3, 9) else 'no')
" 2>/dev/null || echo "no")
        if [ "$ok" = "yes" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    error "Python >= $MIN_PYTHON is required but not found."
    echo "  Install Python from https://www.python.org/downloads/"
    exit 1
fi

info "Found $($PYTHON --version 2>&1)"

installed=false

# 1. pipx (preferred — isolated env, manages PATH)
if ! $installed && has pipx; then
    info "Installing with pipx..."
    if pipx install "$PACKAGE" --force 2>&1; then
        installed=true
    else
        warn "pipx install failed, trying next method..."
    fi
fi

# 2. uv tool (same benefits as pipx)
if ! $installed && has uv; then
    info "Installing with uv..."
    if uv tool install "$PACKAGE" --force 2>&1; then
        installed=true
    else
        warn "uv install failed, trying next method..."
    fi
fi

# 3. pip inside an active virtualenv
if ! $installed && in_virtualenv; then
    info "Virtualenv detected, installing with pip..."
    if $PYTHON -m pip install --upgrade "$PACKAGE" 2>&1; then
        installed=true
    else
        warn "pip install failed inside virtualenv."
    fi
fi

# 4. pip (system or --user fallback)
if ! $installed; then
    if ! $PYTHON -m pip --version &>/dev/null; then
        error "No suitable installer found."
        echo ""
        echo "  Install one of the following, then re-run this script:"
        echo "    pipx  - https://pipx.pypa.io/stable/installation/"
        echo "    uv    - https://docs.astral.sh/uv/getting-started/installation/"
        echo "    pip   - $PYTHON -m ensurepip --upgrade"
        exit 1
    fi

    info "Installing with pip..."
    if $PYTHON -m pip install --upgrade "$PACKAGE" 2>&1; then
        installed=true
    else
        warn "System pip install failed, trying --user install..."
        if $PYTHON -m pip install --user --upgrade "$PACKAGE" 2>&1; then
            installed=true

            user_bin="$($PYTHON -c "import site; print(site.getusersitepackages().replace('/lib/python', '/bin').split('/lib/')[0] + '/bin')" 2>/dev/null || echo "$HOME/.local/bin")"
            case ":$PATH:" in
                *":$user_bin:"*) ;;
                *)
                    warn "$user_bin is not in your PATH."
                    echo ""
                    echo "  Add it by running:"
                    echo "    export PATH=\"$user_bin:\$PATH\""
                    echo ""
                    echo "  To make it permanent, add that line to your ~/.bashrc or ~/.zshrc"
                    ;;
            esac
        fi
    fi
fi

if ! $installed; then
    error "All installation methods failed."
    echo ""
    echo "  You can try manually:"
    echo "    pipx install $PACKAGE"
    echo "    # or"
    echo "    pip install $PACKAGE"
    exit 1
fi

finish
