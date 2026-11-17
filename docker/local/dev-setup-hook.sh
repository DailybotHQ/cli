#!/usr/bin/env bash
# devcontainer-kit start hook for the Dailybot CLI (dck_repo_hook).
#
# The dck entrypoint runs this file at every container start, as dev-user, from
# /workspace (DCK_USER is set by the compose service). A failing step is reported and the container keeps running. It
# carries the CLI-specific start-up the old hand-written entrypoint did; the
# rest (persistence, sshd, Herdr, agents, git identity) is dck's.
set -u

log() { printf 'dev-setup-hook: %s\n' "$*"; }

# Container only. The Dailybot hub launcher (`bash dev.sh setup`) also runs a
# docker/local/dev-setup-hook.sh, on the host; there is nothing to do there.
if [ -z "${DCK_USER:-}" ] || [ ! -f /.dockerenv ]; then
  log "container start hook; nothing to do on the host"
  exit 0
fi

rc=0

# 1. /app -> /workspace. The Dailybot tooling contract is /workspace; tools that
#    assume the devcontainer-kit default path find the same checkout at /app.
if [ ! -e /app ]; then
  sudo ln -sfn /workspace /app && log "linked /app -> /workspace" || rc=1
fi

# 2. dbdev: the Dailybot hub launcher by the same name as on the host.
if [ -f /workspace/dev.sh ]; then
  sudo ln -sfn /workspace/dev.sh /usr/local/bin/dbdev || rc=1
fi

# 3. ~/.dailybot_data on the state volume: clitest's local and custom
#    credential stores (CLITEST_LOCAL_CONFIG_DIR, CLITEST_CUSTOM_CONFIG_BASE)
#    survive a rebuild, like ~/.config/dailybot, which dck already keeps there.
state="$HOME/.dck/volumes/state"
if [ -d "$state" ] && [ ! -L "$HOME/.dailybot_data" ]; then
  if [ -d "$HOME/.dailybot_data" ]; then
    log "~/.dailybot_data is a directory; left as is"
  else
    mkdir -p "$state/dailybot_data" && ln -sfn "$state/dailybot_data" "$HOME/.dailybot_data" || rc=1
  fi
fi

# 4. ~/.pypirc from PYPI_API_TOKEN / TESTPYPI_API_TOKEN (docker/local/clivscode/.env),
#    for manual twine flows. Written 0600; the values are never printed.
write_pypirc() {
  local f="$HOME/.pypirc" tmp
  if [ -z "${PYPI_API_TOKEN:-}" ] && [ -z "${TESTPYPI_API_TOKEN:-}" ]; then
    return 0
  fi
  tmp="$(umask 077 && mktemp "$HOME/.pypirc.XXXXXX")" || return 1
  {
    echo "[distutils]"
    echo "index-servers ="
    [ -n "${PYPI_API_TOKEN:-}" ] && echo "    pypi"
    [ -n "${TESTPYPI_API_TOKEN:-}" ] && echo "    testpypi"
    if [ -n "${PYPI_API_TOKEN:-}" ]; then
      printf '\n[pypi]\nusername = __token__\npassword = %s\n' "$PYPI_API_TOKEN"
    fi
    if [ -n "${TESTPYPI_API_TOKEN:-}" ]; then
      printf '\n[testpypi]\nrepository = https://test.pypi.org/legacy/\nusername = __token__\npassword = %s\n' "$TESTPYPI_API_TOKEN"
    fi
  } > "$tmp" && chmod 600 "$tmp" && mv -f "$tmp" "$f" && log "wrote ~/.pypirc (0600)"
}
write_pypirc || { log "could not write ~/.pypirc"; rc=1; }

# 5. The locked development requirements (requirements/dev.txt) in the user's
#    site, reinstalled only when the lock changes or the container is new. It
#    runs in the background so a first start does not hold sshd and Herdr
#    back; the log is ~/.local/share/dailybot-cli-dev/install.log. The checkout
#    itself is installed editable on demand with `dev_install`.
lock=/workspace/requirements/dev.txt
dir="$HOME/.local/share/dailybot-cli-dev"
if [ -f "$lock" ]; then
  want="$(sha256sum "$lock" | cut -d' ' -f1)"
  if [ "$(cat "$dir/requirements.sha256" 2>/dev/null)" != "$want" ]; then
    mkdir -p "$dir"
    log "installing requirements/dev.txt in the background (pip --user; log: ${dir#"$HOME"/}/install.log)"
    nohup bash -c '
      if pip install --user --quiet --disable-pip-version-check --no-warn-script-location -r "$1"; then
        printf "%s\n" "$2" > "$3/requirements.sha256"; echo "dev-setup-hook: requirements installed"
      else
        echo "dev-setup-hook: pip install -r requirements/dev.txt failed"
      fi' _ "$lock" "$want" "$dir" > "$dir/install.log" 2>&1 < /dev/null &
  fi
fi

exit "$rc"
