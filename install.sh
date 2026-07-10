#!/usr/bin/env bash
# DailyBot CLI installer
# Usage: curl -fsSL https://cli.dailybot.com/install.sh | bash
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

# True if version $1 >= version $2, compared as dotted version tokens via the
# version-aware `sort -V` (GNU coreutils, always present on the Linux binary
# path). Used only to check a ">=" floor against the latest published release.
version_ge() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n1)" = "$1" ]; }

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

# --- Version selection ---
# Install a specific version, or a minimum version floor, instead of the
# latest. Provide it either as an environment variable or a CLI flag:
#   curl -fsSL https://cli.dailybot.com/install.sh | DAILYBOT_VERSION=1.15.0 bash
#   curl -fsSL https://cli.dailybot.com/install.sh | bash -s -- --version 1.15.0
#
# Accepted forms:
#   (empty)     install the latest published version
#   1.15.0      install exactly 1.15.0
#   ==1.15.0    install exactly 1.15.0 (explicit form of the above)
#   >=1.15.0    install the newest published version at or above 1.15.0
VERSION="${DAILYBOT_VERSION:-}"

while [ $# -gt 0 ]; do
    case "$1" in
        --version)
            VERSION="${2:-}"
            shift
            [ $# -gt 0 ] && shift
            ;;
        --version=*)
            VERSION="${1#--version=}"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Split an optional comparison operator from the numeric version. VERSION_OP is
# "" (latest), "==" (exact pin) or ">=" (minimum floor); VERSION_NUM holds the
# bare number. Unsupported operators (<, >, <=, ~=, !=) are rejected outright so
# the binary path never has to resolve a range it can't map to a single tag.
VERSION_OP=""
VERSION_NUM=""
case "$VERSION" in
    "")    ;;
    ">="*) VERSION_OP=">="; VERSION_NUM="${VERSION#>=}" ;;
    "=="*) VERSION_OP="=="; VERSION_NUM="${VERSION#==}" ;;
    *[\<\>\~\!=]*)
        error "Unsupported version specifier '$VERSION'. Use an exact version (1.15.0 or ==1.15.0) or a minimum floor (>=1.15.0)."
        exit 1
        ;;
    *)     VERSION_OP="=="; VERSION_NUM="$VERSION" ;;
esac

# Tolerate whitespace around the number (e.g. DAILYBOT_VERSION=">= 1.15.0").
VERSION_NUM="${VERSION_NUM//[[:space:]]/}"

# Reject anything that is not a plain version token so it cannot be smuggled
# into the pip spec or the release download URL.
case "$VERSION_NUM" in
    "") ;;
    *[!0-9A-Za-z.+-]*)
        error "Invalid version '$VERSION_NUM'. Expected a version like 1.15.0."
        exit 1
        ;;
esac

# Human-readable specifier for log lines: "", "==1.15.0" or ">=1.15.0".
VERSION_DISPLAY=""
[ -n "$VERSION_NUM" ] && VERSION_DISPLAY="${VERSION_OP}${VERSION_NUM}"

# Emit the pip requirement: "dailybot-cli", "dailybot-cli==<v>" or
# "dailybot-cli>=<v>". pip natively resolves ">=" to the newest matching release.
pip_spec() {
    if [ -n "$VERSION_NUM" ]; then
        printf '%s%s%s' "$PACKAGE" "$VERSION_OP" "$VERSION_NUM"
    else
        printf '%s' "$PACKAGE"
    fi
}

if [ -n "$VERSION_NUM" ]; then
    if [ "$VERSION_OP" = ">=" ]; then
        info "Requested Dailybot CLI: >=$VERSION_NUM (minimum floor — installing the newest at or above it)"
    else
        info "Requested Dailybot CLI version: $VERSION_NUM"
    fi
fi

# --- Detect OS ---

OS="$(uname -s)"

# =============================================================================
# macOS → Homebrew
# =============================================================================
if [ "$OS" = "Darwin" ]; then
    # Homebrew always installs the latest formula version. When a specific
    # version (or a floor) is requested we fall through to the pip path, which
    # can honour both an exact pin and a ">=" minimum.
    if [ -n "$VERSION_NUM" ]; then
        info "Homebrew installs only the latest release; using pip to install $VERSION_DISPLAY..."
    else
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
fi

# =============================================================================
# Linux → Binary download, fallback to pip
# =============================================================================
if [ "$OS" = "Linux" ]; then
    install_binary() {
        local latest url status_code install_dir="/usr/local/bin"
        local arch latest_num
        arch="$(uname -m)"

        # Only x86_64 binary is available; skip on other architectures
        if [ "$arch" != "x86_64" ]; then
            warn "Pre-built binary is only available for x86_64 (detected: $arch)."
            return 1
        fi

        if [ "$VERSION_OP" = "==" ]; then
            # Exact pin: request that release tag directly. If its binary asset
            # is missing the caller falls back to a pinned pip install.
            latest="v$VERSION_NUM"
        else
            # Latest, or a ">=" floor: resolve the newest published release tag.
            latest=$(curl -sI "https://github.com/$REPO/releases/latest" \
                | grep -i "^location:" | sed 's/.*tag\///' | tr -d '\r\n')

            if [ -z "$latest" ]; then
                return 1
            fi

            # For a floor, only take the latest binary if it satisfies the floor;
            # otherwise defer to pip, which resolves/verifies the ">=" spec and
            # errors clearly when the floor is unpublishable.
            if [ "$VERSION_OP" = ">=" ]; then
                latest_num="${latest#v}"
                if ! version_ge "$latest_num" "$VERSION_NUM"; then
                    warn "Latest release $latest does not satisfy >=$VERSION_NUM; deferring to pip."
                    return 1
                fi
            fi
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
print('yes' if v >= (3, 10) else 'no')
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
    if pipx install "$(pip_spec)" --force 2>&1; then
        installed=true
    else
        warn "pipx install failed, trying next method..."
    fi
fi

# 2. uv tool (same benefits as pipx)
if ! $installed && has uv; then
    info "Installing with uv..."
    if uv tool install "$(pip_spec)" --force 2>&1; then
        installed=true
    else
        warn "uv install failed, trying next method..."
    fi
fi

# 3. pip inside an active virtualenv
if ! $installed && in_virtualenv; then
    info "Virtualenv detected, installing with pip..."
    if $PYTHON -m pip install --upgrade "$(pip_spec)" 2>&1; then
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
    if $PYTHON -m pip install --upgrade "$(pip_spec)" 2>&1; then
        installed=true
    else
        warn "System pip install failed, trying --user install..."
        if $PYTHON -m pip install --user --upgrade "$(pip_spec)" 2>&1; then
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
    echo "    pipx install $(pip_spec)"
    echo "    # or"
    echo "    pip install $(pip_spec)"
    exit 1
fi

finish
