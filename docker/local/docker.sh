#!/usr/bin/env bash
#
# docker/local/docker.sh — cli helpers for agent workspaces.
# Generic verbs live in bash dev.sh. This file adds satellite.up/focus/rm and
# primary.backend/restore. Contract: hub docs/technical/AGENT_WORKSPACES.md
#
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

usage() {
  cat <<'EOF'
Usage: bash docker.sh <verb> [id]

  satellite.up {id}       Start clivscodesatellite (SSH only)
  satellite.focus {id}    Ensure satellite up (no HTTP preview)
  satellite.unfocus {id}  Clear focus marker
  primary.backend         No-op for CLI (no HTTP port to free)
  primary.restore         No-op for CLI
  satellite.bash {id}     Shell in the satellite
  satellite.stop {id}     Stop satellite
  satellite.rm {id}       Remove satellite
  satellite.rebuild {id}  Rebuild image (cache on; SATELLITE_NO_CACHE=1 for wipe) and recreate
  satellite.logs {id}     Follow satellite logs
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
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  # The primary port in docker/local/.env must not pin every satellite.
  export HERDR_SSH_HOST_PORT="$((22900 + id))"
  say "Starting clivscodesatellite #${id} SSH :${HERDR_SSH_HOST_PORT}"
  if docker ps --format '{{.Names}}' | grep -qx "dailybot_clivscodesatellite_${id}"; then
    say "CLI satellite already running — leave it"
  else
    compose -f docker-compose.satellite-stable.yaml up -d --no-deps clivscodesatellite
  fi
}

cmd_satellite_focus() {
  local id
  id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  export HERDR_SSH_HOST_PORT="$((22900 + id))"
  if ! docker ps --format '{{.Names}}' | grep -qx "dailybot_clivscodesatellite_${id}"; then
    compose -f docker-compose.satellite-stable.yaml up -d --no-deps clivscodesatellite
  else
    say "CLI satellite ${id} already up (no recreate)"
  fi
  mkdir -p "$(db_ws_root)"
  printf '%s\n' "$id" >"$(db_ws_root)/_cli_focus_id"
  say "CLI satellite ready SSH :${HERDR_SSH_HOST_PORT}"
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
  local id
  id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  compose exec clivscodesatellite bash
}

cmd_satellite_stop() {
  local id
  id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  compose stop clivscodesatellite
}

cmd_satellite_rm() {
  local id
  id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  compose stop clivscodesatellite 2>/dev/null || true
  compose rm -f clivscodesatellite 2>/dev/null || true
  docker rm -f "dailybot_clivscodesatellite_${id}" 2>/dev/null || true
}

cmd_satellite_rebuild() {
  local id build_args=()
  id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  export HERDR_SSH_HOST_PORT="$((22900 + id))"
  if [ "${SATELLITE_NO_CACHE:-0}" = "1" ]; then
    build_args=(--no-cache --pull)
    say "Rebuilding clivscodesatellite #${id} --no-cache --pull"
  else
    say "Rebuilding clivscodesatellite #${id} (layer cache on)"
  fi
  compose stop clivscodesatellite 2>/dev/null || true
  compose -f docker-compose.satellite-stable.yaml build ${build_args[@]+"${build_args[@]}"} clivscodesatellite
  compose -f docker-compose.satellite-stable.yaml up -d --force-recreate --no-deps clivscodesatellite
}

cmd_satellite_logs() {
  local id
  id="$(sat_id "${1:-}")"
  export DEVCONTAINER_INSTANCE_ID="$id"
  export COMPOSE_PROJECT_NAME="dailybotclilocal_${id}"
  compose logs -f clivscodesatellite
}

case "${1:-}" in
  satellite.up) cmd_satellite_up "${2:-}" ;;
  satellite.focus) cmd_satellite_focus "${2:-}" ;;
  satellite.unfocus) cmd_satellite_unfocus "${2:-}" ;;
  primary.backend) cmd_primary_backend ;;
  primary.restore) cmd_primary_restore ;;
  primary.refocus) cmd_primary_refocus ;;
  satellite.bash) cmd_satellite_bash "${2:-}" ;;
  satellite.stop) cmd_satellite_stop "${2:-}" ;;
  satellite.rm) cmd_satellite_rm "${2:-}" ;;
  satellite.rebuild) cmd_satellite_rebuild "${2:-}" ;;
  satellite.logs) cmd_satellite_logs "${2:-}" ;;
  -h|--help|help|"") usage ;;
  *) say "Unknown verb: $1"; usage; exit 1 ;;
esac
