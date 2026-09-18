#!/usr/bin/env bash
#
# dev.sh — Dailybot dev stack launcher.
#
# Starts exactly the services this repository's devcontainer.json declares,
# without VS Code or Cursor. The devcontainer file is the single source of
# truth: change "runServices" there and nothing else.
#
# Usage:  bash dev.sh <verb> [args]              from any repository
#         bash dev.sh <repo> <verb> [args]       from the hub, targeting a child
#
# This file is generated from the hub's canonical copy and must stay
# byte-identical in every repository. Do not edit a copy: raise the change in
# the hub and re-sync. See docs/LOCAL_ENVIRONMENT.md.

set -euo pipefail

# --------------------------------------------------------------------------
# Basics
# --------------------------------------------------------------------------

die() { printf 'dev.sh: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }

# Resolve this script's own directory, following symlinks, so the launcher
# behaves identically from the repo root, a subdirectory, or an absolute path.
_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
  _dir="$(cd -P "$(dirname "$_self")" && pwd)"
  _self="$(readlink "$_self")"
  case "$_self" in /*) ;; *) _self="$_dir/$_self" ;; esac
done
SELF_DIR="$(cd -P "$(dirname "$_self")" && pwd)"

VERBS=" setup up down stop start restart ps logs shell exec build ls config doctor help "

# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

TARGET_REPO=""
VERB=""
ALL=0
WITH_VOLUMES=0
RECREATE=0
PROJECT_OVERRIDE=""
ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all) ALL=1; shift ;;
    --volumes) WITH_VOLUMES=1; shift ;;
    --recreate) RECREATE=1; shift ;;
    --repo) [ $# -ge 2 ] || die "--repo needs a repository name"; TARGET_REPO="$2"; shift 2 ;;
    --project) [ $# -ge 2 ] || die "--project needs a name"; PROJECT_OVERRIDE="$2"; shift 2 ;;
    -h|--help) VERB="help"; shift ;;
    --) shift; while [ $# -gt 0 ]; do ARGS+=("$1"); shift; done ;;
    *)
      if [ -z "$VERB" ]; then
        case "$VERBS" in
          *" $1 "*) VERB="$1" ;;
          *)
            [ -z "$TARGET_REPO" ] || die "unexpected argument '$1' (repository already set to '$TARGET_REPO')"
            TARGET_REPO="$1"
            ;;
        esac
      else
        ARGS+=("$1")
      fi
      shift
      ;;
  esac
done

[ -n "$VERB" ] || VERB="help"

# --------------------------------------------------------------------------
# Repository resolution
# --------------------------------------------------------------------------

has_devcontainer() {
  [ -f "$1/.devcontainer/devcontainer.json" ] || [ -f "$1/.devcontainer_example/devcontainer.json" ]
}

# Every repository this launcher can address: the one it lives in, plus any
# child under repositories/ that carries a devcontainer file. In a leaf
# repository the loop simply finds no children — there is no hub-only path.
# Repositories the launcher deliberately does not claim, declared one name per
# line in .devstack-ignore at the workspace root (blank lines and # comments are
# skipped). A repository can carry a devcontainer and still not belong to the
# stack this launcher maintains, and that is a fact about the workspace, not
# about this file -- which is byte-identical in every repository and must not
# know any of them by name. Sub-repository copies have no repositories/ dir, so
# this never fires there.
devstack_ignored() {
  local name="$1" line
  [ -f "$SELF_DIR/.devstack-ignore" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | tr -d '[:space:]')"
    [ -n "$line" ] || continue
    [ "$line" = "$name" ] && return 0
  done < "$SELF_DIR/.devstack-ignore"
  return 1
}

# The one definition of "a repository this launcher works with". It feeds the
# table, the check that a target is valid, and the --all fan-out, so an ignored
# repository is not merely hidden: --all never touches it either.
child_repos() {
  local d name
  [ -d "$SELF_DIR/repositories" ] || return 0
  for d in "$SELF_DIR"/repositories/*/; do
    [ -d "$d" ] || continue
    name="$(basename "${d%/}")"
    devstack_ignored "$name" && continue
    has_devcontainer "${d%/}" || continue
    printf '%s\n' "$name"
  done
}

resolve_repo_root() {
  local want="$1"
  if [ -z "$want" ]; then
    printf '%s\n' "$SELF_DIR"
    return 0
  fi
  # An ignored repository is named before the directory check, so the answer is
  # "on purpose, here is where that is declared" rather than the generic unknown
  # target error -- which would read like the repository is missing.
  if devstack_ignored "$want"; then
    die "'$want' is listed in .devstack-ignore, so this launcher does not manage it.
       Remove the line there to bring it back, or open the repository directly."
  fi
  local cand="$SELF_DIR/repositories/$want"
  if [ -d "$cand" ] && has_devcontainer "$cand"; then
    printf '%s\n' "$cand"
    return 0
  fi
  local valid
  valid="$(child_repos | tr '\n' ' ')"
  if [ -z "$valid" ]; then
    die "unknown target '$want' — this repository has no addressable children"
  fi
  die "unknown repository '$want' — valid targets: ${valid% }"
}

# --------------------------------------------------------------------------
# devcontainer.json (JSONC) resolution
# --------------------------------------------------------------------------

# Prints KEY=VALUE lines. Never eval'd: the caller reads them with IFS.
read_devcontainer() {
  local root="$1"
  python3 - "$root" <<'PY'
import json, os, sys

root = sys.argv[1]

def strip_jsonc(s):
    out = []; i = 0; n = len(s); instr = False
    while i < n:
        c = s[i]
        if instr:
            out.append(c)
            if c == '\\' and i + 1 < n:
                out.append(s[i + 1]); i += 2; continue
            if c == '"':
                instr = False
            i += 1; continue
        if c == '"':
            instr = True; out.append(c); i += 1; continue
        if c == '/' and i + 1 < n and s[i + 1] == '/':
            while i < n and s[i] != '\n':
                i += 1
            continue
        if c == '/' and i + 1 < n and s[i + 1] == '*':
            i += 2
            while i + 1 < n and not (s[i] == '*' and s[i + 1] == '/'):
                i += 1
            i += 2; continue
        out.append(c); i += 1
    return ''.join(out)

active = os.path.join(root, '.devcontainer', 'devcontainer.json')
tmpl = os.path.join(root, '.devcontainer_example', 'devcontainer.json')
if os.path.isfile(active):
    path, source = active, 'active'
elif os.path.isfile(tmpl):
    path, source = tmpl, 'example'
else:
    sys.stderr.write('no devcontainer.json under .devcontainer/ or .devcontainer_example/\n')
    raise SystemExit(2)

try:
    data = json.loads(strip_jsonc(open(path).read()))
except Exception as exc:                                    # noqa: BLE001
    sys.stderr.write('cannot parse %s: %s\n' % (path, exc))
    raise SystemExit(2)

cf = data.get('dockerComposeFile')
if isinstance(cf, list):
    cf = cf[0] if cf else None
if not cf:
    sys.stderr.write('%s declares no dockerComposeFile\n' % path)
    raise SystemExit(2)
compose = os.path.normpath(os.path.join(os.path.dirname(path), cf))

service = data.get('service') or ''
run = data.get('runServices') or ([service] if service else [])

print('DC_FILE=%s' % path)
print('DC_SOURCE=%s' % source)
print('DC_COMPOSE=%s' % compose)
print('DC_SERVICE=%s' % service)
print('DC_RUNSERVICES=%s' % ' '.join(run))
print('DC_USER=%s' % (data.get('remoteUser') or ''))
print('DC_WORKSPACE=%s' % (data.get('workspaceFolder') or ''))
print('DC_SHUTDOWN=%s' % (data.get('shutdownAction') or ''))
print('DC_HAS_MOUNTS=%s' % ('1' if data.get('mounts') or data.get('containerEnv') else '0'))
PY
}

load_context() {
  local root="$1" line k v
  DC_FILE=""; DC_SOURCE=""; DC_COMPOSE=""; DC_SERVICE=""
  DC_RUNSERVICES=""; DC_USER=""; DC_WORKSPACE=""; DC_SHUTDOWN=""; DC_HAS_MOUNTS="0"
  while IFS= read -r line; do
    k="${line%%=*}"; v="${line#*=}"
    case "$k" in
      DC_FILE) DC_FILE="$v" ;;
      DC_SOURCE) DC_SOURCE="$v" ;;
      DC_COMPOSE) DC_COMPOSE="$v" ;;
      DC_SERVICE) DC_SERVICE="$v" ;;
      DC_RUNSERVICES) DC_RUNSERVICES="$v" ;;
      DC_USER) DC_USER="$v" ;;
      DC_WORKSPACE) DC_WORKSPACE="$v" ;;
      DC_SHUTDOWN) DC_SHUTDOWN="$v" ;;
      DC_HAS_MOUNTS) DC_HAS_MOUNTS="$v" ;;
    esac
  done < <(read_devcontainer "$root")
  [ -n "$DC_COMPOSE" ] || die "could not resolve the devcontainer configuration in $root"
  [ -f "$DC_COMPOSE" ] || die "compose file not found: $DC_COMPOSE"
  COMPOSE_DIR="$(cd -P "$(dirname "$DC_COMPOSE")" && pwd)"
}

# --------------------------------------------------------------------------
# Compose project name
# --------------------------------------------------------------------------

resolve_project() {
  PROJECT=""; PROJECT_FROM=""
  if [ -n "$PROJECT_OVERRIDE" ]; then
    PROJECT="$PROJECT_OVERRIDE"; PROJECT_FROM="--project flag"; return 0
  fi
  if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
    PROJECT="$COMPOSE_PROJECT_NAME"; PROJECT_FROM="COMPOSE_PROJECT_NAME in the environment"; return 0
  fi
  if [ -f "$COMPOSE_DIR/.env" ]; then
    local v
    v="$(sed -n 's/^[[:space:]]*COMPOSE_PROJECT_NAME[[:space:]]*=[[:space:]]*\(.*\)$/\1/p' "$COMPOSE_DIR/.env" | tail -1)"
    v="${v%\"}"; v="${v#\"}"
    if [ -n "$v" ]; then
      PROJECT="$v"; PROJECT_FROM="COMPOSE_PROJECT_NAME in $(basename "$COMPOSE_DIR")/.env"; return 0
    fi
  fi
  local n
  n="$(sed -n 's/^name:[[:space:]]*\([A-Za-z0-9_.-]*\).*$/\1/p' "$DC_COMPOSE" | head -1)"
  if [ -n "$n" ]; then
    PROJECT="$n"; PROJECT_FROM="top-level name: in the compose file"; return 0
  fi
  # Never the directory default: that would create a second, parallel container
  # set that looks correct and is not the one the Dev Container manages.
  die "cannot resolve the compose project name — set COMPOSE_PROJECT_NAME in $(basename "$COMPOSE_DIR")/.env or pass --project"
}

# --------------------------------------------------------------------------
# Compose binary and invocation
# --------------------------------------------------------------------------

# Resolved with command -v, never by running `docker compose version`: that
# call costs ~155 ms and the fast check must stay imperceptible.
resolve_compose_bin() {
  if command -v docker >/dev/null 2>&1; then
    COMPOSE_BIN="docker"; COMPOSE_SUB="compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_BIN="docker-compose"; COMPOSE_SUB=""
  else
    die "neither 'docker' nor 'docker-compose' is on PATH — install Docker Desktop"
  fi
}

override_path() {
  # A per-user directory created 0700, not the temp root directly: TMPDIR is
  # private per user on macOS, but the /tmp fallback is world-writable and a
  # predictable name there is a symlink target another local user can plant.
  local d
  d="${TMPDIR:-/tmp}/dev-sh-$(id -u)"
  if [ ! -d "$d" ]; then
    mkdir -p "$d"
    chmod 700 "$d"
  fi
  printf '%s/%s-override.yml' "$d" "$(basename "$REPO_ROOT")"
}

# Reproduce the devcontainer's own `mounts` and `containerEnv`, which the Dev
# Containers plugin injects through a generated overlay and plain compose does
# not. Written outside the repository so no tree gains an untracked file.
write_override() {
  [ "$DC_HAS_MOUNTS" = "1" ] || return 0
  python3 - "$DC_FILE" "$DC_SERVICE" "$PROJECT" "$(override_path)" <<'PY'
import json, sys, os

src, service, project, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

def strip_jsonc(s):
    o=[];i=0;n=len(s);ins=False
    while i<n:
        c=s[i]
        if ins:
            o.append(c)
            if c=='\\' and i+1<n: o.append(s[i+1]); i+=2; continue
            if c=='"': ins=False
            i+=1; continue
        if c=='"': ins=True;o.append(c);i+=1;continue
        if c=='/' and i+1<n and s[i+1]=='/':
            while i<n and s[i]!='\n': i+=1
            continue
        if c=='/' and i+1<n and s[i+1]=='*':
            i+=2
            while i+1<n and not (s[i]=='*' and s[i+1]=='/'): i+=1
            i+=2; continue
        o.append(c); i+=1
    return ''.join(o)

d = json.loads(strip_jsonc(open(src).read()))
mounts, env = d.get('mounts') or [], d.get('containerEnv') or {}

vols, decls = [], {}
for m in mounts:
    if not isinstance(m, str):
        continue
    parts = dict(p.split('=', 1) for p in m.split(',') if '=' in p)
    if parts.get('type') != 'volume':
        continue
    source, target = parts.get('source'), parts.get('target')
    if not source or not target:
        continue
    # The Dev Containers plugin passes source= straight through as a compose
    # volume short name, and compose then prefixes it with the project. That is
    # why a real container shows <project>_<source>. Reproduce that exactly:
    # declaring a stripped name would mount a different, empty volume.
    # If the source already looks like a fully-qualified Docker volume name
    # (contains underscores and matches the pattern used by Compose), treat it
    # as external so we do not create an empty anonymous volume.
    if '_' in source and source.startswith(project + '_'):
        decls[source] = source
    else:
        decls[source] = None
    vols.append('      - %s:%s' % (source, target))

lines = ['# Generated by dev.sh from %s — do not edit.' % os.path.basename(src),
         '# Reproduces the devcontainer mounts/containerEnv that plain compose omits.',
         'services:', '  %s:' % service]
if env:
    lines.append('    environment:')
    for k, v in env.items():
        lines.append('      %s: %s' % (k, json.dumps(str(v))))
if vols:
    lines.append('    volumes:')
    lines.extend(vols)
if decls:
    lines.append('volumes:')
    for short, external in decls.items():
        if external is None:
            lines.append('  %s: {}' % short)
        else:
            lines.append('  %s:' % short)
            lines.append('    external: true')
            lines.append('    name: %s' % external)
open(out, 'w').write('\n'.join(lines) + '\n')
PY
}

compose_files_args() {
  COMPOSE_ARGS=(-f "$DC_COMPOSE")
  if [ "$DC_HAS_MOUNTS" = "1" ] && [ -f "$(override_path)" ]; then
    COMPOSE_ARGS+=(-f "$(override_path)")
  fi
}

# NOTE: --remove-orphans is deliberately never passed. All seven repositories
# share one compose project while each has its own compose file, so that flag
# would treat every other repository's container as an orphan and remove it.
dc() {
  resolve_compose_bin
  compose_files_args
  if [ -n "$COMPOSE_SUB" ]; then
    "$COMPOSE_BIN" "$COMPOSE_SUB" -p "$PROJECT" "${COMPOSE_ARGS[@]}" "$@"
  else
    "$COMPOSE_BIN" -p "$PROJECT" "${COMPOSE_ARGS[@]}" "$@"
  fi
}

# --------------------------------------------------------------------------
# Environment files and external networks
# --------------------------------------------------------------------------

env_examples() {
  [ -d "$COMPOSE_DIR" ] || return 0
  find "$COMPOSE_DIR" -type f -name '.env*.example' 2>/dev/null | sort
}

external_networks() {
  python3 - "$DC_COMPOSE" <<'PY'
import re, sys
txt = open(sys.argv[1]).read()
m = re.search(r'^networks:\s*$', txt, re.M)
if not m:
    raise SystemExit(0)
body = txt[m.end():]
end = re.search(r'^\S', body, re.M)
body = body[:end.start()] if end else body
if 'external' not in body:
    raise SystemExit(0)
for name in re.findall(r'^\s*name:\s*([A-Za-z0-9_.-]+)\s*$', body, re.M):
    print(name)
PY
}

# Detect only. Never creates. Runs for the verbs that start containers.
fast_check() {
  local missing="" f target
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    [ -f "$target" ] || missing="${missing}${missing:+, }${target#"$REPO_ROOT"/}"
  done < <(env_examples)
  if [ -n "$missing" ]; then
    die "local environment not ready (missing $missing) — run: bash dev.sh setup"
  fi
  local net
  while IFS= read -r net; do
    [ -n "$net" ] || continue
    if ! docker network inspect "$net" >/dev/null 2>&1; then
      die "docker network '$net' is missing — run: bash dev.sh setup"
    fi
  done < <(external_networks)
}

# --------------------------------------------------------------------------
# Verbs
# --------------------------------------------------------------------------

# Rewrite one SERVICE_PERMISSIONS line atomically, leaving no backup behind.
stamp_permissions() {
  python3 -c '
import os, sys, tempfile
path, perms = sys.argv[1], sys.argv[2]
out = []
for line in open(path).read().splitlines(True):
    if line.lstrip().startswith("SERVICE_PERMISSIONS="):
        out.append("SERVICE_PERMISSIONS=%s\n" % perms)
    else:
        out.append(line)
d = os.path.dirname(path) or "."
mode = os.stat(path).st_mode & 0o7777
fd, tmp = tempfile.mkstemp(dir=d, prefix=".dev-sh-", suffix=".tmp")
try:
    os.fchmod(fd, mode)
    with os.fdopen(fd, "w") as fh:
        fh.write("".join(out))
    os.replace(tmp, path)
except BaseException:
    try: os.unlink(tmp)
    except OSError: pass
    raise
' "$1" "$2"
}

cmd_setup() {
  local created=0 f target net
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    if [ ! -f "$target" ]; then
      cp "$f" "$target"
      note "created ${target#"$REPO_ROOT"/}"
      created=$((created + 1))
    fi
  done < <(env_examples)

  # Match the repositories' own utils.sh: only files that already declare the
  # key are stamped. Values are never printed.
  local perms
  perms="$(id -u):$(id -g)"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    [ -f "$target" ] || continue
    grep -q '^[[:space:]]*SERVICE_PERMISSIONS=' "$target" 2>/dev/null || continue
    # Rewritten through a temp file in the same directory, never with
    # `sed -i.bak`: that leaves a backup of a .env — real values and all — next
    # to it, and `.env.<suffix>` is covered by none of these repositories'
    # gitignore rules. A failed run must not be able to strand secrets in a
    # trackable file.
    stamp_permissions "$target" "$perms" || die "could not update SERVICE_PERMISSIONS in $target"
  done < <(env_examples)

  while IFS= read -r net; do
    [ -n "$net" ] || continue
    if docker network inspect "$net" >/dev/null 2>&1; then
      note "network $net already present"
    else
      docker network create "$net" >/dev/null
      note "created network $net"
      created=$((created + 1))
    fi
  done < <(external_networks)

  if [ ! -d "$REPO_ROOT/.devcontainer" ] && [ -d "$REPO_ROOT/.devcontainer_example" ]; then
    mkdir -p "$REPO_ROOT/.devcontainer"
    cp -R "$REPO_ROOT/.devcontainer_example/." "$REPO_ROOT/.devcontainer/"
    note "created .devcontainer/ from .devcontainer_example/"
    created=$((created + 1))
  fi
  if [ ! -d "$REPO_ROOT/.vscode" ] && [ -d "$REPO_ROOT/.vscode_example" ]; then
    mkdir -p "$REPO_ROOT/.vscode"
    cp -R "$REPO_ROOT/.vscode_example/." "$REPO_ROOT/.vscode/"
    note "created .vscode/ from .vscode_example/"
    created=$((created + 1))
  fi

  ensure_shutdown_action && created=$((created + 1)) || true

  # Repository-specific bootstrap the generic steps above cannot know about
  # (generated version files, sample credential files, service seeds). Optional:
  # a repository that needs none simply has no hook. Keeping it here is what lets
  # this launcher stay byte-identical across repositories.
  if [ -f "$COMPOSE_DIR/dev-setup-hook.sh" ]; then
    note "running docker/local/dev-setup-hook.sh"
    ( cd "$COMPOSE_DIR" && bash dev-setup-hook.sh )
    created=$((created + 1))
  fi

  if [ "$created" -eq 0 ]; then
    note "setup: everything was already in place"
  else
    note "setup: done"
  fi
}

# Keeps the stack running when the editor window closes. Additive key of the
# Dev Container spec, so the plugin path is unaffected.
ensure_shutdown_action() {
  local f="$REPO_ROOT/.devcontainer/devcontainer.json"
  [ -f "$f" ] || return 1
  python3 - "$f" <<'PY'
import json, os, re, shutil, sys

path = sys.argv[1]
src = open(path).read()

def strip_jsonc(s):
    o=[];i=0;n=len(s);ins=False
    while i<n:
        c=s[i]
        if ins:
            o.append(c)
            if c=='\\' and i+1<n: o.append(s[i+1]); i+=2; continue
            if c=='"': ins=False
            i+=1; continue
        if c=='"': ins=True;o.append(c);i+=1;continue
        if c=='/' and i+1<n and s[i+1]=='/':
            while i<n and s[i]!='\n': i+=1
            continue
        if c=='/' and i+1<n and s[i+1]=='*':
            i+=2
            while i+1<n and not (s[i]=='*' and s[i+1]=='/'): i+=1
            i+=2; continue
        o.append(c); i+=1
    return ''.join(o)

if 'shutdownAction' in strip_jsonc(src):
    raise SystemExit(1)                      # already set, nothing created

commented = re.search(r'^([ \t]*)//[ \t]*("shutdownAction"[^\n]*)$', src, re.M)
if commented:
    new = src[:commented.start()] + commented.group(1) + commented.group(2) + src[commented.end():]
else:
    anchor = re.search(r'^([ \t]*)"(runServices|service)"[^\n]*\n', src, re.M)
    if not anchor:
        raise SystemExit(1)
    indent = anchor.group(1)
    new = src[:anchor.end()] + '%s"shutdownAction": "none",\n' % indent + src[anchor.end():]

try:
    json.loads(strip_jsonc(new))
except Exception:
    raise SystemExit(1)                      # refuse to write something unparsable

shutil.copyfile(path, path + '.bak')
tmp = path + '.tmp'
open(tmp, 'w').write(new)
os.replace(tmp, path)
print('set "shutdownAction": "none" in .devcontainer/devcontainer.json')
PY
}

services_or_default() {
  if [ "${#ARGS[@]}" -gt 0 ]; then
    printf '%s\n' "${ARGS[@]}"
  else
    printf '%s\n' $DC_RUNSERVICES
  fi
}

cmd_up() {
  fast_check
  write_override
  local svc=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  [ "${#svc[@]}" -gt 0 ] || die "no services to start — $DC_FILE declares neither runServices nor service"
  note "starting ${svc[*]} (project $PROJECT)"
  # --no-recreate by default. A container created by the Dev Containers plugin
  # carries generated overlay compose files, so its config differs from this
  # file alone and a plain `up` would silently replace it, dropping the
  # plugin's features. Pass --recreate to apply compose changes on purpose.
  if [ "$RECREATE" -eq 1 ]; then
    dc up -d --force-recreate "${svc[@]}"
  else
    dc up -d --no-recreate "${svc[@]}"
    note "existing containers were left as they are; use --recreate to apply compose changes"
  fi
}

cmd_down() {
  write_override
  local svc=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  # Scoped to this repository's own services: never `compose down`, which would
  # act on the shared project as a whole.
  note "stopping and removing ${svc[*]} (project $PROJECT)"
  dc rm -sf "${svc[@]}"
  if [ "$WITH_VOLUMES" -eq 1 ]; then
    note "--volumes was passed; remove named volumes manually after reviewing: docker volume ls"
  fi
}

cmd_simple() {
  fast_check
  write_override
  local verb="$1"; shift
  local svc=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  dc "$verb" "${svc[@]}"
}

cmd_ps() {
  write_override
  # Scoped to this repository's own services. The compose project is shared by
  # every repository, so an unscoped `compose ps` would list all of them.
  local svc=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  dc ps "${svc[@]}"
}

cmd_logs() {
  write_override
  local service="${ARGS[0]:-$DC_SERVICE}"
  dc logs -f "$service"
}

cmd_shell() {
  write_override
  local service="${ARGS[0]:-$DC_SERVICE}"
  local -a opts=()
  # remoteUser and workspaceFolder describe the devcontainer's MAIN service only.
  # A backing service such as postgres has no such user, and passing it there
  # fails with "unable to find user ... in passwd file".
  if [ "$service" = "$DC_SERVICE" ]; then
    if [ -n "$DC_USER" ]; then
      # docker exec inherits PID 1's environment, including HOME=/root, so a
      # non-root shell needs these or the user's profile never loads.
      opts+=(--user "$DC_USER" -e "HOME=/home/$DC_USER" -e "USER=$DC_USER" -e "LOGNAME=$DC_USER")
    fi
    [ -n "$DC_WORKSPACE" ] && opts+=(-w "$DC_WORKSPACE")
  fi
  dc exec ${opts[@]+"${opts[@]}"} "$service" bash -l 2>/dev/null || dc exec ${opts[@]+"${opts[@]}"} "$service" sh -l
}

cmd_exec() {
  write_override
  [ "${#ARGS[@]}" -ge 2 ] || die "exec needs a service and a command: bash dev.sh exec <service> <cmd...>"
  local service="${ARGS[0]}"
  local rest=("${ARGS[@]:1}")
  local -a opts=()
  # Same rule as shell: the devcontainer user and workspace belong to the main
  # service. Backing services run as whatever their own image defines.
  if [ "$service" = "$DC_SERVICE" ]; then
    [ -n "$DC_USER" ] && opts+=(--user "$DC_USER" -e "HOME=/home/$DC_USER" -e "USER=$DC_USER" -e "LOGNAME=$DC_USER")
    [ -n "$DC_WORKSPACE" ] && opts+=(-w "$DC_WORKSPACE")
  fi
  dc exec ${opts[@]+"${opts[@]}"} "$service" ${rest[@]+"${rest[@]}"}
}

cmd_build() {
  fast_check
  write_override
  local svc=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  dc build "${svc[@]}"
}

cmd_config() {
  note "repository      $REPO_ROOT"
  note "devcontainer    $DC_FILE ($DC_SOURCE)"
  note "compose file    $DC_COMPOSE"
  note "compose project $PROJECT (from $PROJECT_FROM)"
  note "main service    $DC_SERVICE"
  note "runServices     $DC_RUNSERVICES"
  note "remoteUser      ${DC_USER:-<unset>}"
  note "workspaceFolder ${DC_WORKSPACE:-<unset>}"
  note "shutdownAction  ${DC_SHUTDOWN:-<unset>}"
  local nets
  nets="$(external_networks | tr '\n' ' ')"
  note "external nets   ${nets:-<none>}"
  if [ "$DC_HAS_MOUNTS" = "1" ]; then
    note "overlay         $(override_path) (generated on the next up; devcontainer mounts/containerEnv)"
  fi
}

cmd_doctor() {
  resolve_compose_bin
  if [ -n "$COMPOSE_SUB" ]; then
    note "compose         $($COMPOSE_BIN $COMPOSE_SUB version 2>/dev/null | head -1)"
  else
    note "compose         $($COMPOSE_BIN --version 2>/dev/null | head -1)"
  fi
  note "docker daemon   $(docker info --format '{{.ServerVersion}}' 2>/dev/null || echo 'not reachable')"
  cmd_config
  local f target net ok
  note "--- environment files"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    note "  ${target#"$REPO_ROOT"/}: $([ -f "$target" ] && echo present || echo MISSING)"
  done < <(env_examples)
  note "--- external networks"
  while IFS= read -r net; do
    [ -n "$net" ] || continue
    ok=$(docker network inspect "$net" >/dev/null 2>&1 && echo present || echo MISSING)
    note "  $net: $ok"
  done < <(external_networks)
  note "--- declared environment keys (names only, never values)"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    [ -f "$target" ] || continue
    while IFS= read -r line; do
      case "$line" in \#*|'') continue ;; esac
      case "$line" in *=*) ;; *) continue ;; esac
      key="${line%%=*}"; val="${line#*=}"
      note "  ${key}: $([ -n "$val" ] && echo set || echo unset)"
    done < "$target"
  done < <(env_examples)
}

cmd_ls() {
  local repos name root
  repos="$(child_repos)"
  note "repositories addressable from $(basename "$SELF_DIR"):"
  note ""
  printf '  %-22s %-28s %s\n' "REPO" "MAIN SERVICE" "RUNNING"
  local label
  for name in "." $repos; do
    if [ "$name" = "." ]; then
      root="$SELF_DIR"; label="$(basename "$SELF_DIR")"
    else
      root="$SELF_DIR/repositories/$name"; label="$name"
    fi
    has_devcontainer "$root" || continue
    (
      load_context "$root" 2>/dev/null || exit 0
      running=0
      for s in $DC_RUNSERVICES; do
        if docker ps --filter "label=com.docker.compose.service=$s" --format '{{.Names}}' 2>/dev/null | grep -q .; then
          running=$((running + 1))
        fi
      done
      total=$(printf '%s\n' $DC_RUNSERVICES | grep -c . || true)
      printf '  %-22s %-28s %s\n' "$label" "$DC_SERVICE" "$running/$total up"
    )
  done
}

cmd_help() {
  cat <<'USAGE'
dev.sh — start this repository's dev containers without VS Code.

  bash dev.sh <verb> [args]            operate on this repository
  bash dev.sh <repo> <verb> [args]     from the hub, operate on a child repo

Verbs
  setup                 one-time bootstrap: env files, network, .devcontainer/
  up [service...]       start the devcontainer's runServices, detached
  down                  stop and remove this repository's services
  stop | start | restart
  ps                    what is running here
  logs [service]        follow logs
  shell [service]       shell as the devcontainer's remoteUser, in its workspace
  exec <service> <cmd>  run one command in a service
  build [service]       build images
  ls                    repositories this launcher can address, and their state
  config                resolved configuration; writes nothing
  doctor                environment diagnosis; writes nothing
  help                  this text

Flags
  --repo <name>         unambiguous repository target
  --all                 fan the verb out over every addressable repository
  --project <name>      override the compose project name
  --recreate            with up, recreate containers to apply compose changes
  --volumes             with down, report named volumes for manual removal

The devcontainer.json "runServices" list is the single source of truth for
what starts. Change it there and nothing else.
USAGE
}

# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

run_one() {
  REPO_ROOT="$1"
  load_context "$REPO_ROOT"
  resolve_project
  case "$VERB" in
    setup)   cmd_setup ;;
    up)      cmd_up ;;
    down)    cmd_down ;;
    stop|start|restart) cmd_simple "$VERB" ;;
    ps)      cmd_ps ;;
    logs)    cmd_logs ;;
    shell)   cmd_shell ;;
    exec)    cmd_exec ;;
    build)   cmd_build ;;
    config)  cmd_config ;;
    doctor)  cmd_doctor ;;
    *)       die "unknown verb '$VERB' — run: bash dev.sh help" ;;
  esac
}

case "$VERB" in
  help) cmd_help; exit 0 ;;
  ls)   SELF_DIR="$SELF_DIR"; cmd_ls; exit 0 ;;
esac

if [ "$ALL" -eq 1 ]; then
  targets=("$SELF_DIR")
  while IFS= read -r c; do [ -n "$c" ] && targets+=("$SELF_DIR/repositories/$c"); done < <(child_repos)
  note "dev.sh $VERB --all will touch:"
  for t in "${targets[@]}"; do note "  $(basename "$t")"; done
  note ""
  for t in "${targets[@]}"; do
    note "=== $(basename "$t")"
    run_one "$t"
  done
  exit 0
fi

# Resolved into a variable first, and the status checked. A failure inside
# `$(...)` only exits the SUBSHELL: written as run_one "$(resolve_repo_root …)"
# an unknown or ignored target printed its error and then ran the verb against
# an empty root, which falls back to this repository -- so `dev.sh typo down`
# reported the typo and took the hub's containers down anyway, exiting 0.
_resolved_root="$(resolve_repo_root "$TARGET_REPO")" || exit 1
[ -n "$_resolved_root" ] || die "could not resolve a target for '${TARGET_REPO:-.}'"
run_one "$_resolved_root"
