#!/usr/bin/env bash
#
# docker/local/docker.sh — cli helpers for agent workspaces.
# Generic verbs live in bash dev.sh. This file adds satellite.up/focus/rm and
# primary.backend/restore. Contract: hub docs/technical/AGENT_WORKSPACES.md
#
# A satellite goes through `bash dev.sh satellite` (devcontainer-kit when dck
# is installed: host keys, accounts, git identity and the Herdr machine), so
# the workspace can reach it over SSH like every other dck satellite.
set -eo pipefail

db_ws_root() {
  local root="${DAILYBOT_WORKSPACES_ROOT:-$HOME/.dailybot-ws/workspaces}"
  local old="$HOME/.dailybot-dev/workspaces"
  if [ -z "${DAILYBOT_WORKSPACES_ROOT:-}" ] && [ ! -e "$root" ] && [ -d "$old" ]; then
    mkdir -p "$(dirname "$root")"
    mv "$old" "$root"
  fi
  printf '%s\n' "$root"
}

ROOT_DOCKER="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DOCKER"

say() { printf '%s\n' "$*"; }

# The workspace's SSH port must win over the primary's in .env.
WS_REQUESTED_HERDR_SSH_HOST_PORT="${HERDR_SSH_HOST_PORT:-}"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

COMPOSE=(docker-compose)
if ! command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker compose)
fi

compose() {
  "${COMPOSE[@]}" -f docker-compose.yaml "$@"
}

# -p is the satellite project. Agent volumes use PRIMARY_COMPOSE_PROJECT from
# docker/local/.env because -p overwrites COMPOSE_PROJECT_NAME.
: "${PRIMARY_COMPOSE_PROJECT:=${COMPOSE_PROJECT_NAME:-dailybotplatformlocal}}"
export PRIMARY_COMPOSE_PROJECT
sat_compose() {
  local sid="$1"
  shift
  compose -p "dailybotclilocal_${sid}" "$@"
}

satellite_env() {
  local id="$1"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export HERDR_SSH_HOST_PORT="${WS_REQUESTED_HERDR_SSH_HOST_PORT:-$((22900 + id))}"
}

satellite_label() {
  local id="$1"
  local workspace_name="${DAILYBOT_WORKSPACE_ID:-$id}"
  local default_label="${id} - CLI · WS ${workspace_name}"
  printf '%s\n' "${DAILYBOT_WS_HERDR_LABEL:-${DCK_SATELLITE_LABEL:-$default_label}}"
}

satellite_dev() {
  local id="$1"
  local action="$2"
  shift 2
  bash ../../dev.sh satellite "$action" \
    --project "dailybotclilocal_${id}" \
    --service clivscodesatellite \
    --compose-file docker-compose.yaml \
    --compose-file docker-compose.satellite-stable.yaml \
    "$@"
}

usage() {
  cat <<'EOF'
Usage: bash docker.sh <verb> [id]

  satellite.up {id}       Start clivscodesatellite (SSH only). Always runs
                          dev.sh satellite up (dck up when installed): a
                          no-op on a healthy satellite, and it re-registers
                          the Herdr machine and dck key on one that lacks them
  satellite.down {id}     Stop and remove the satellite (dck down)
  satellite.focus {id}    Ensure satellite up, same path as satellite.up
                          (no HTTP preview)
  satellite.unfocus {id}  Clear focus marker
  primary.backend         No-op for CLI (no HTTP port to free)
  primary.restore         No-op for CLI
  satellite.bash {id}     Shell in the satellite
  satellite.stop {id}     Stop satellite
  satellite.rm {id}       Remove satellite
  satellite.rebuild {id}  Rebuild image (cache on; SATELLITE_NO_CACHE=1 for wipe) and recreate
  satellite.logs|ps|shell {id}
EOF
}

sat_id() {
  local id="${1:-${DEVCONTAINER_INSTANCE_ID:-1}}"
  [[ "$id" =~ ^[0-9]+$ ]] || { say "Satellite instance id must be a positive integer"; exit 1; }
  printf '%s\n' "$id"
}

primary_docker_local() {
  if [ -n "${DAILYBOT_ROOT:-}" ] && [ -f "${DAILYBOT_ROOT}/repositories/cli/docker/local/docker-compose.yaml" ]; then
    printf '%s\n' "${DAILYBOT_ROOT}/repositories/cli/docker/local"
    return 0
  fi
  printf '%s\n' "$ROOT_DOCKER"
}

cmd_satellite_up() {
  local id
  id="$(sat_id "${1:-}")"
  satellite_env "$id"
  say "Starting clivscodesatellite #${id} SSH :${HERDR_SSH_HOST_PORT}"
  satellite_dev "$id" up --seed-state --label "$(satellite_label "$id")"
}

cmd_satellite_focus() {
  local id
  id="$(sat_id "${1:-}")"
  satellite_env "$id"
  # Same path as satellite.up: dck up is idempotent on a healthy satellite and
  # heals one left by the old plain-compose path (authorized dck key, Herdr
  # machine, SSH alias) instead of skipping it because the container runs.
  satellite_dev "$id" up --seed-state --label "$(satellite_label "$id")"
  mkdir -p "$(db_ws_root)"
  printf '%s\n' "$id" >"$(db_ws_root)/_cli_focus_id"
  say "CLI satellite ready SSH :${HERDR_SSH_HOST_PORT} (no HTTP preview)"
}

cmd_satellite_down() {
  local id
  id="$(sat_id "${1:-}")"
  satellite_env "$id"
  satellite_dev "$id" down
}

cmd_satellite_unfocus() {
  local id
  id="$(sat_id "${1:-}")"
  FOCUS_STATE="$(db_ws_root)/_cli_focus_id"
  if [ -f "$FOCUS_STATE" ] && [ "$(tr -d '[:space:]' <"$FOCUS_STATE")" = "$id" ]; then
    rm -f "$FOCUS_STATE"
  fi
  say "Unfocusing CLI satellite ${id}"
}

cmd_primary_backend() {
  # CLI has no HTTP preview port; primary SSH stays on :22031.
  say "Primary CLI — no HTTP backend move (SSH :22031)"
}

cmd_primary_restore() {
  say "Primary CLI — no HTTP restore needed"
}

cmd_primary_refocus() {
  cmd_primary_restore
}

cmd_satellite_bash() {
  local id; id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  sat_compose "$id" exec clivscodesatellite bash
}
cmd_satellite_stop() {
  local id; id="$(sat_id "${1:-}")"
  satellite_env "$id"
  satellite_dev "$id" stop
}
cmd_satellite_ps() {
  local id; id="$(sat_id "${1:-}")"
  satellite_env "$id"
  satellite_dev "$id" ps
}
cmd_satellite_shell() {
  local id; id="$(sat_id "${1:-}")"
  satellite_env "$id"
  satellite_dev "$id" shell
}
cmd_satellite_rm() {
  local id; id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  # dck down first, so dck also removes the satellite's Herdr machine and SSH alias.
  satellite_env "$id"
  satellite_dev "$id" down 2>/dev/null || true
  sat_compose "$id" stop clivscodesatellite 2>/dev/null || true
  sat_compose "$id" rm -f clivscodesatellite 2>/dev/null || true
  docker rm -f "dailybot_clivscodesatellite_${id}" 2>/dev/null || true
}
cmd_satellite_rebuild() {
  local id build_args=()
  id="$(sat_id "${1:-}")"
  satellite_env "$id"
  if [ "${SATELLITE_NO_CACHE:-0}" = "1" ]; then
    build_args=(--no-cache)
    say "Rebuilding clivscodesatellite #${id} --no-cache --pull"
  else
    say "Rebuilding clivscodesatellite #${id} (layer cache on)"
  fi
  satellite_dev "$id" rebuild --seed-state --label "$(satellite_label "$id")" --recreate ${build_args[@]+"${build_args[@]}"}
}
cmd_satellite_logs() {
  local id; id="$(sat_id "${1:-}")"
  satellite_env "$id"
  satellite_dev "$id" logs
}

case "${1:-}" in
  satellite.up) cmd_satellite_up "${2:-}" ;;
  satellite.down) cmd_satellite_down "${2:-}" ;;
  satellite.focus) cmd_satellite_focus "${2:-}" ;;
  satellite.unfocus) cmd_satellite_unfocus "${2:-}" ;;
  primary.backend) cmd_primary_backend ;;
  primary.restore) cmd_primary_restore ;;
  primary.refocus) cmd_primary_refocus ;;
  satellite.bash) cmd_satellite_bash "${2:-}" ;;
  satellite.stop) cmd_satellite_stop "${2:-}" ;;
  satellite.ps) cmd_satellite_ps "${2:-}" ;;
  satellite.shell) cmd_satellite_shell "${2:-}" ;;
  satellite.rm) cmd_satellite_rm "${2:-}" ;;
  satellite.rebuild) cmd_satellite_rebuild "${2:-}" ;;
  satellite.logs) cmd_satellite_logs "${2:-}" ;;
  -h|--help|help|"") usage ;;
  *) say "Unknown verb: $1"; usage; exit 1 ;;
esac
