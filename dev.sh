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

VERBS=" setup up down stop start restart ps logs shell exec build rebuild ls config doctor agents ask herdr-layout help "

# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

TARGET_REPO=""
VERB=""
ALL=0
WITH_VOLUMES=0
RECREATE=0
NO_CACHE=0
PROJECT_OVERRIDE=""
ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all) ALL=1; shift ;;
    --volumes) WITH_VOLUMES=1; shift ;;
    --recreate) RECREATE=1; shift ;;
    --no-cache) NO_CACHE=1; shift ;;
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
  # Created with the mode already set, never created-then-chmod'd, and never
  # reused unless we own it: the name is predictable, so on a world-writable
  # /tmp another local account can plant the directory first. Testing -d and
  # skipping the chmod would then hand them the compose override, which names
  # mounts and environment, plus a symlink race on the file inside.
  if ! (umask 077 && mkdir -p "$d") 2>/dev/null; then
    die "could not create $d"
  fi
  if [ -L "$d" ] || [ ! -d "$d" ] || [ ! -O "$d" ]; then
    die "$d is not a directory you own — refusing to write the compose override there.
       Remove it, or point TMPDIR somewhere private."
  fi
  chmod 700 "$d"
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

# Copy each docker/local/**/.env*.example to the matching .env when missing.
# Created at 0600 (umask 077) so a later paste of API keys is not world-readable.
# Sets _ensure_created to the number of files/networks this call created
# so cmd_setup can fold them into its summary counter.
ensure_env_from_examples() {
  local f target
  _ensure_created=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    if [ ! -f "$target" ]; then
      if ! (umask 077 && : > "$target"); then
        die "could not create $target"
      fi
      cat "$f" > "$target"
      note "created ${target#"$REPO_ROOT"/} from ${f#"$REPO_ROOT"/} (0600)"
      _ensure_created=$((_ensure_created + 1))
    fi
  done < <(env_examples)
}

ensure_external_networks() {
  local net
  _ensure_created=0
  while IFS= read -r net; do
    [ -n "$net" ] || continue
    if docker network inspect "$net" >/dev/null 2>&1; then
      continue
    fi
    docker network create "$net" >/dev/null
    note "created docker network $net"
    _ensure_created=$((_ensure_created + 1))
  done < <(external_networks)
}

# Runs before verbs that start containers. Missing .env files are created from
# .env.example; missing compose external networks are created. Remaining gaps
# (no example file at all) still fail with a clear path.
fast_check() {
  local missing="" f target
  ensure_env_from_examples
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    [ -f "$target" ] || missing="${missing}${missing:+, }${target#"$REPO_ROOT"/}"
  done < <(env_examples)
  if [ -n "$missing" ]; then
    die "local environment not ready (missing $missing and no matching .env.example)"
  fi
  ensure_external_networks
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
  ensure_env_from_examples
  created=$((created + _ensure_created))

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

  ensure_external_networks
  created=$((created + _ensure_created))

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
  dc exec ${opts[@]+"${opts[@]}"} "$service" bash -l || dc exec ${opts[@]+"${opts[@]}"} "$service" sh -l
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
  local svc=() build_args=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  if [ "$NO_CACHE" -eq 1 ]; then
    build_args=(--no-cache --pull)
  fi
  dc build ${build_args[@]+"${build_args[@]}"} "${svc[@]}"
}

cmd_rebuild() {
  # Same intent as the Dev Containers plugin "Rebuild and Reopen Container":
  # stop this repository's services, rebuild their images, and start them
  # again. Default uses Docker layer cache (fast). Pass --no-cache for a full
  # wipe of layers + --pull of base images (slow). Scoped to runServices only
  # — never compose down on the shared project, which would take sibling
  # repositories with it.
  fast_check
  write_override
  local svc=() build_args=()
  while IFS= read -r s; do [ -n "$s" ] && svc+=("$s"); done < <(services_or_default)
  [ "${#svc[@]}" -gt 0 ] || die "no services to rebuild — $DC_FILE declares neither runServices nor service"
  if [ "$NO_CACHE" -eq 1 ]; then
    build_args=(--no-cache --pull)
    note "rebuilding ${svc[*]} (project $PROJECT, --no-cache --pull)"
  else
    note "rebuilding ${svc[*]} (project $PROJECT, with build cache)"
  fi
  note "stopping and removing current containers"
  dc rm -sf "${svc[@]}" || true
  if [ "$NO_CACHE" -eq 1 ]; then
    note "building images without cache"
  else
    note "building images (layer cache enabled)"
  fi
  dc build ${build_args[@]+"${build_args[@]}"} "${svc[@]}"
  note "starting rebuilt containers"
  dc up -d --force-recreate "${svc[@]}"
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
      # Each repository resolves its own compose project; the filter below reads
      # PROJECT, which only the main dispatch sets, and set -u would abort here.
      resolve_project 2>/dev/null || exit 0
      running=0
      for s in $DC_RUNSERVICES; do
        if docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$s" --format '{{.Names}}' 2>/dev/null | grep -q .; then
          running=$((running + 1))
        fi
      done
      total=$(printf '%s\n' $DC_RUNSERVICES | grep -c . || true)
      printf '  %-22s %-28s %s\n' "$label" "$DC_SERVICE" "$running/$total up"
    )
  done
}

# Herdr dials peers with strict checking and ignores the peers-file
# accept-new. It also requires the ED25519 host key. A machine created after
# this container started, or one whose known_hosts only has the RSA key,
# fails as unreachable. Trust the ED25519 key before asking for agents.
herdr_trust_peer_keys() {
  local peers="${HOME}/.ssh_host/config.d/dailybot-peers"
  local workspace_peers="${HOME}/.ssh/${HERDR_WORKSPACE_PEERS_REL}"
  local known="${HOME}/.ssh/known_hosts"
  local sources=()
  [ -f "$peers" ] && sources+=("$peers")
  [ -f "$workspace_peers" ] && sources+=("$workspace_peers")
  [ "${#sources[@]}" -gt 0 ] || return 0
  touch "$known"
  awk '
    /^Host / { host=$2; port="" }
    /^[[:space:]]*Port / && host != "" { port=$2 }
    host != "" && port != "" {
      printf "%s %s\n", host, port
      host=""; port=""
    }
  ' "${sources[@]}" | while read -r peer_host peer_port; do
    # Host is an SSH alias. ssh stores [host.docker.internal]:port.
    # Primaries 22022-22032 (22032 is the Mac); satellites 22400-22999.
    case "${peer_port}" in
      ''|*[!0-9]*) continue ;;
      2202[2-9]|2203[0-2]|22[4-9][0-9][0-9]) ;;
      *) continue ;;
    esac
    # Debian hashes known_hosts, so a plaintext grep never sees the type.
    # ssh-keygen -F prints the stored line; skip only when that line is the
    # ED25519 key Herdr's strict client requires. An older RSA/ECDSA line
    # for the same port must not hide a missing ED25519 key.
    if ssh-keygen -F "[host.docker.internal]:${peer_port}" -f "$known" 2>/dev/null \
      | grep -q 'ssh-ed25519'; then
      continue
    fi
    # keyscan writes the plaintext ED25519 line. accept-new stores whatever
    # type the server offers first, which on these images is often RSA, and
    # Herdr then refuses the port. A down peer is skipped.
    if ! ssh-keyscan -T 4 -t ed25519 -p "${peer_port}" host.docker.internal 2>/dev/null \
      | grep -v '^#' >>"$known"; then
      ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=4 \
        -o PreferredAuthentications=publickey -p "${peer_port}" \
        host.docker.internal true >/dev/null 2>&1 || true
    fi
  done
  return 0
}

# The Mac rewrites ~/.ssh/config.d/dailybot-workspaces every time a workspace
# is created, but the container peers file is only regenerated by
# `dbdev onboard herdr`, so a workspace created later is in the Herdr catalog
# and unresolvable here. Derive container aliases from the live Mac file on
# every call: same Host and Port, HostName swapped for the Docker gateway.
# Only satellite ports are kept, and aliases are checked before they are
# written into an ssh config.
HERDR_WORKSPACE_PEERS_REL="config.d/dailybot-workspace-peers"
herdr_sync_workspace_peers() {
  local src="${HOME}/.ssh_host/config.d/dailybot-workspaces"
  local dest="${HOME}/.ssh/${HERDR_WORKSPACE_PEERS_REL}"
  local ssh_config="${HOME}/.ssh/config"
  local include_line="Include ~/.ssh/${HERDR_WORKSPACE_PEERS_REL}"
  [ -f "$src" ] || return 0
  mkdir -p "$(dirname "$dest")"
  local tmp
  tmp="$(mktemp "${dest}.XXXXXX")"
  awk '
    function flush() {
      if (host != "" && port != "" && user != "") {
        printf "Host %s\n  HostName host.docker.internal\n  Port %s\n  User %s\n  StrictHostKeyChecking accept-new\n\n", host, port, user
      }
      host=""; port=""; user=""
    }
    BEGIN { print "# Generated by dbdev from ~/.ssh_host/config.d/dailybot-workspaces. Do not edit.\n" }
    /^Host / { flush(); if ($2 ~ /^[A-Za-z0-9._-]+$/ && NF == 2) host=$2; next }
    /^[[:space:]]*Port / { if ($2 ~ /^22[4-9][0-9][0-9]$/) port=$2; next }
    /^[[:space:]]*User / { if ($2 ~ /^[a-z_][a-z0-9_-]*$/) user=$2; next }
    END { flush() }
  ' "$src" > "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$dest"
  touch "$ssh_config"
  if ! grep -qxF "$include_line" "$ssh_config"; then
    # First match wins, so this goes above the (possibly stale) peers include.
    tmp="$(mktemp "${ssh_config}.XXXXXX")"
    printf '%s\n' "$include_line" | cat - "$ssh_config" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$ssh_config"
  fi
}

# Copy the read-only Mac catalog over the local Herdr file, then trust peer
# keys. ask and agents both need a catalog that already contains the Mac.
herdr_prepare_mesh() {
  local refresh="${HOME}/.local/bin/herdr-refresh-catalog"
  local src="${HOME}/.herdr_client_host/endpoints.json"
  if [ -x "$refresh" ]; then
    # A missing Mac catalog is an empty mesh, not a failed command.
    if [ -f "$src" ]; then
      "$refresh" || die "could not refresh the Herdr catalog from the Mac mount"
    fi
  elif [ -f "$src" ]; then
    die "catalog mount is present but ${refresh} is missing; restart this container once so the entrypoint installs it"
  fi
  herdr_sync_workspace_peers
  herdr_trust_peer_keys
}

# Copy the read-only Mac catalog over the local Herdr file, then ask every
# enabled machine for its agents. The mount updates when the Mac catalog
# changes; Herdr itself only reads the copy, because it also writes that path.
cmd_herdr_agents() {
  command -v herdr >/dev/null 2>&1 || die "herdr is not on PATH"
  command -v python3 >/dev/null 2>&1 || die "python3 is required to read the catalog"
  herdr_prepare_mesh
  python3 - <<'PY'
import json, os, subprocess, sys

def machines():
    try:
        raw = subprocess.run(
            ["herdr", "machine", "list", "--json"],
            capture_output=True, text=True, timeout=12,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("herdr machine list timed out\n")
        sys.exit(1)
    if raw.returncode != 0:
        sys.stderr.write(raw.stderr or "herdr machine list failed\n")
        sys.exit(raw.returncode or 1)
    try:
        data = json.loads(raw.stdout or "[]")
    except json.JSONDecodeError:
        sys.stderr.write("herdr machine list did not return JSON\n")
        sys.exit(1)
    if not isinstance(data, list):
        sys.stderr.write("herdr machine list JSON was not a list\n")
        sys.exit(1)
    return [m for m in data if isinstance(m, dict)]

def agents_for(machine_id):
    try:
        raw = subprocess.run(
            ["herdr", "--machine", machine_id, "agent", "list"],
            capture_output=True, text=True, timeout=12,
        )
    except subprocess.TimeoutExpired:
        return None, ["timed out"]
    if raw.returncode != 0 or not raw.stdout.strip():
        return None, (raw.stderr or "no answer").strip().splitlines()[-1:] or ["no answer"]
    try:
        payload = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return None, ["agent list was not JSON"]
    result = payload.get("result") if isinstance(payload, dict) else None
    found = result.get("agents") if isinstance(result, dict) else None
    if not isinstance(found, list):
        return None, ["agent list had no agents array"]
    return found, None

def current_pane():
    # pane current is this process's own pane. The table loop matches it
    # against the agents it already fetched, so each machine is asked once.
    try:
        raw = subprocess.run(
            ["herdr", "pane", "current"],
            capture_output=True, text=True, timeout=8,
        )
    except subprocess.TimeoutExpired:
        return "", ""
    if raw.returncode != 0 or not raw.stdout.strip():
        return "", ""
    try:
        pane = ((json.loads(raw.stdout).get("result") or {}).get("pane") or {})
    except json.JSONDecodeError:
        return "", ""
    return str(pane.get("pane_id") or ""), str(pane.get("terminal_id") or "")

self_pane, self_terminal = current_pane()
self_machine = ""

rows = []
for machine in machines():
    if not machine.get("enabled"):
        continue
    label = str(machine.get("label") or "").replace("\t", " ")
    mid = str(machine.get("id") or "")
    if not mid:
        continue
    found, err = agents_for(mid)
    if err is not None:
        rows.append((label, mid, "-", "-", "unreachable", "", ""))
        continue
    if not found:
        rows.append((label, mid, "-", "-", "no agents", "", ""))
        continue
    for agent in found:
        if not isinstance(agent, dict):
            continue
        pane_id = str(agent.get("pane_id") or "-")
        terminal_id = str(agent.get("terminal_id") or "")
        if (
            not self_machine
            and self_pane
            and pane_id == self_pane
            and (not self_terminal or terminal_id == self_terminal)
        ):
            self_machine = mid
        rows.append((
            label,
            mid,
            str(agent.get("agent") or "-"),
            pane_id,
            str(agent.get("agent_status") or "-"),
            str(agent.get("terminal_title_stripped") or "").replace("\n", " "),
            terminal_id,
        ))

def clean(label):
    text = label.strip()
    if len(text) > 3 and text[0].isdigit() and " - " in text[:6]:
        text = text.split(" - ", 1)[1]
    return text

def paint(code, text):
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return "\033[%sm%s\033[0m" % (code, text)

state_color = {
    "idle": "32",
    "working": "33",
    "blocked": "31",
    "done": "36",
    "unreachable": "90",
    "no agents": "90",
}
shown = []
number = 0
you = None
for label, mid, name, pane, state, title, _terminal in rows:
    if pane != "-":
        number += 1
        short = str(number)
    else:
        short = "-"
    mine = bool(self_machine) and mid == self_machine and pane == self_pane
    if mine:
        you = short
    shown.append((short, clean(label), mid, name, pane, state, title[:36], mine))

headers = ("#", "MACHINE", "ID", "AGENT", "PANE", "STATE", "TITLE")
widths = [len(h) for h in headers]
for row in shown:
    for i, cell in enumerate(row[:7]):
        if i == 6:
            continue
        widths[i] = max(widths[i], len(cell))

def line(cells, color_state=None, mine=False):
    parts = []
    for i, cell in enumerate(cells):
        text = cell.ljust(widths[i]) if i < 6 else cell
        if i == 5 and color_state:
            text = paint(state_color.get(color_state, "0"), text)
        parts.append(text)
    body = "  " + "  ".join(parts).rstrip()
    if mine:
        body = paint("1;32", body) + "  <- you"
    return body

if you:
    print(paint("1;32", "  you are #%s. That row is this session." % you))
else:
    print("  this session is not a row in the list.")
print()
print(paint("1", line(headers)))
print("  " + "  ".join("-" * w for w in widths))
if not shown:
    print("  (no enabled machines)")
else:
    for row in shown:
        print(line(row[:7], row[5], row[7]))

example = next((row for row in shown if row[0] != "-" and not row[7]), None)
print()
print("  # is the short id from this list. PANE is the stable address.")
print("  bash dev.sh ask <#> \"Prompt...\"")
print("  bash dev.sh ask <machine id> <pane> \"Prompt...\"")
if example:
    print("  bash dev.sh ask %s \"Prompt...\"" % example[0])
PY
}

# Send one prompt and stamp where the reply should go.
#
# The stamp is permission and a return address. The receiver sends the answer
# itself, and keeps the stamp in that command so the answer is marked as a
# reply. A reply carries a stamp that says not to answer it. That is what
# stops two agents from looping.
#
# A reply lands on the Herdr machine that sent the prompt. On the Mac that
# machine is dailybot-mac (127.0.0.1:22032). Inside a container it is that
# container's own pane. Pass --from <machine-id> <pane> only when this session
# has no pane of its own.
cmd_herdr_ask() {
  local from_machine="" from_pane=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --from)
        [ $# -ge 3 ] || die "ask --from needs <machine-id> <pane>"
        from_machine="$2"
        from_pane="$3"
        shift 3
        ;;
      --)
        shift
        break
        ;;
      -*)
        die "unknown ask flag '$1'"
        ;;
      *)
        break
        ;;
    esac
  done
  local machine="" pane="" number=""
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    number="$1"
    shift
  else
    [ $# -ge 3 ] || die "ask needs <#> \"prompt\", or <machine-id> <pane> \"prompt\""
    machine="$1"
    pane="$2"
    shift 2
  fi
  [ $# -ge 1 ] || die "ask needs a prompt"
  local text="$*"
  [ -n "$text" ] || die "ask needs a prompt"
  herdr_prepare_mesh
  if [ -n "$number" ]; then
    local resolved
    resolved="$(HERDR_ASK_NUMBER="$number" python3 - <<'PY'
import json, os, subprocess, sys
want = int(os.environ["HERDR_ASK_NUMBER"])
raw = subprocess.run(["herdr", "machine", "list", "--json"], capture_output=True, text=True, timeout=12)
if raw.returncode != 0:
    sys.stderr.write(raw.stderr or "herdr machine list failed\n")
    sys.exit(1)
machines = json.loads(raw.stdout or "[]")
n = 0
for machine in machines if isinstance(machines, list) else []:
    if not isinstance(machine, dict) or not machine.get("enabled") or not machine.get("id"):
        continue
    listed = subprocess.run(["herdr", "--machine", str(machine["id"]), "agent", "list"], capture_output=True, text=True, timeout=12)
    if listed.returncode != 0 or not listed.stdout.strip():
        continue
    try:
        payload = json.loads(listed.stdout)
    except json.JSONDecodeError:
        continue
    agents = ((payload.get("result") or {}).get("agents") if isinstance(payload, dict) else None) or []
    if not isinstance(agents, list):
        continue
    for agent in agents:
        if not isinstance(agent, dict) or not agent.get("pane_id"):
            continue
        n += 1
        if n == want:
            print("%s %s" % (machine["id"], agent["pane_id"]))
            sys.exit(0)
sys.stderr.write("no agent #%s in the current list; run: bash dev.sh agents\n" % want)
sys.exit(1)
PY
)" || die "could not resolve agent #$number"
    machine="${resolved%% *}"
    pane="${resolved##* }"
  fi
  case "$machine" in
    ""|*[!0-9a-fA-F]*) die "machine id must be the hex id from: bash dev.sh agents" ;;
  esac
  case "$pane" in
    w*:p*) ;;
    *) die "pane must look like w5:p2 (the PANE column from: bash dev.sh agents)" ;;
  esac
  case "$from_pane" in
    ""|w*:p*) ;;
    *) die "--from pane must look like w5:p2" ;;
  esac
  case "$from_machine" in
    ""|*[!0-9a-fA-F]*)
      [ -z "$from_machine" ] || die "--from machine id must be hex"
      ;;
  esac

  command -v herdr >/dev/null 2>&1 || die "herdr is not on PATH"
  command -v python3 >/dev/null 2>&1 || die "python3 is required"

  HERDR_ASK_MACHINE="$machine" \
  HERDR_ASK_PANE="$pane" \
  HERDR_ASK_TEXT="$text" \
  HERDR_ASK_FROM_MACHINE="$from_machine" \
  HERDR_ASK_FROM_PANE="$from_pane" \
  python3 - <<'PY'
import json, os, subprocess, sys

machine = os.environ["HERDR_ASK_MACHINE"]
pane = os.environ["HERDR_ASK_PANE"]
text = os.environ["HERDR_ASK_TEXT"]
from_machine = os.environ.get("HERDR_ASK_FROM_MACHINE") or ""
from_pane = os.environ.get("HERDR_ASK_FROM_PANE") or ""

def run(args, timeout):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.stderr.write("herdr timed out: %s\n" % " ".join(args[:4]))
        sys.exit(1)

def pane_here(pane_id):
    raw = run(["herdr", "pane", "get", pane_id], 8)
    if raw.returncode != 0:
        return False
    try:
        payload = json.loads(raw.stdout or "{}")
    except json.JSONDecodeError:
        return False
    found = ((payload.get("result") or {}).get("pane") or {}).get("pane_id")
    return found == pane_id

def enabled_ids():
    raw = run(["herdr", "machine", "list", "--json"], 12)
    if raw.returncode != 0:
        sys.stderr.write(raw.stderr or "herdr machine list failed\n")
        sys.exit(raw.returncode or 1)
    try:
        data = json.loads(raw.stdout or "[]")
    except json.JSONDecodeError:
        sys.stderr.write("herdr machine list did not return JSON\n")
        sys.exit(1)
    ids = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("enabled") and item.get("id"):
            ids.append(str(item["id"]))
    return ids

if not from_machine or not from_pane:
    current = run(["herdr", "pane", "current"], 8)
    if current.returncode != 0:
        sys.stderr.write("could not read the current pane; pass --from <machine-id> <pane>\n")
        sys.exit(1)
    try:
        from_pane = str(((json.loads(current.stdout).get("result") or {}).get("pane") or {}).get("pane_id") or "")
    except json.JSONDecodeError:
        from_pane = ""
    if not from_pane:
        sys.stderr.write("this session has no pane id; pass --from <machine-id> <pane>\n")
        sys.exit(1)
    for candidate in enabled_ids():
        probe = run(["herdr", "--machine", candidate, "pane", "get", from_pane], 8)
        if probe.returncode != 0:
            continue
        try:
            found = ((json.loads(probe.stdout or "{}").get("result") or {}).get("pane") or {}).get("pane_id")
        except json.JSONDecodeError:
            continue
        if found == from_pane:
            from_machine = candidate
            break
    if not from_machine:
        sys.stderr.write(
            "this session is not on a reachable Herdr machine, so a reply cannot come back here.\n"
            "Run ask from inside a container, or pass --from <machine-id> <pane>\n"
            "of a pane that bash dev.sh agents lists.\n"
        )
        sys.exit(1)

if from_machine == machine and from_pane == pane:
    sys.stderr.write("refusing to ask a pane to reply to itself\n")
    sys.exit(1)

if not pane_here(pane) and machine not in enabled_ids():
    sys.stderr.write("machine %s is not an enabled Herdr machine\n" % machine)
    sys.exit(1)

# A body that already has the stamp is a reply. Mark it as a reply so the
# sender sees the answer, and does not get a second order to answer.
if "[dailybot-mesh]" in text:
    stamp = (
        "[dailybot-mesh] This is the reply. Do not answer it.\n"
        "The conversation stops here."
    )
else:
    stamp = (
        "[dailybot-mesh] You are allowed to answer this, and you must answer it now. "
        "Send the reply yourself with the command below. Do not ask a person for permission, "
        "do not draft the answer and wait, and do not stop after writing it in this pane. "
        "Keep the dailybot-mesh stamp in that command, so your answer is marked as a reply and the conversation stops.\n"
        "Reply with: bash dev.sh ask %s %s \"[dailybot-mesh] your answer\"\n"
        "Or: dbdev ask %s %s \"[dailybot-mesh] your answer\""
    ) % (from_machine, from_pane, from_machine, from_pane)
body = text.rstrip() + "\n\n" + stamp

sent = run(["herdr", "--machine", machine, "agent", "prompt", pane, body], 20)
sys.stdout.write(sent.stdout or "")
sys.stderr.write(sent.stderr or "")
if sent.returncode != 0:
    sys.exit(sent.returncode)
print("asked %s %s" % (machine, pane))
print("reply address: bash dev.sh ask %s %s \"...\"" % (from_machine, from_pane))
PY
}

# Standard Herdr sidebar: Home · Editor · Development · Agents.
# Intended to run inside the vscode container (herdr talks to this machine).
# From the Mac, the same verb docker-execs into this repo's main service.
_hl_json_field() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
start = raw.find("{")
end = raw.rfind("}")
if start < 0 or end < start:
    raise SystemExit(0)
d = json.loads(raw[start:end + 1])
cur = d
for part in sys.argv[1].split("."):
    if not isinstance(cur, dict):
        cur = ""
        break
    cur = cur.get(part)
if cur is None or isinstance(cur, (dict, list)):
    cur = ""
print(cur)
' "$1"
}

_hl_ws_id() {
  local mid="$1" want="$2"
  herdr workspace list 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(0)
d=json.loads(raw[s:e+1])
ws=(d.get("result") or {}).get("workspaces") or d.get("workspaces") or []
want=sys.argv[1]
for w in ws:
    if (w.get("label") or "")==want:
        print(w.get("workspace_id") or "")
        break
' "$want" 2>/dev/null || true
}

_hl_ws_create() {
  local mid="$1" cwd="$2" label="$3" raw
  raw="$(herdr workspace create --cwd "$cwd" --label "$label" --no-focus 2>&1)" || true
  printf '%s' "$raw" | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(0)
d=json.loads(raw[s:e+1]); r=d.get("result") or d
ws=(r.get("workspace") or {}); rp=(r.get("root_pane") or {}); tab=(r.get("tab") or {})
print("%s\t%s\t%s" % (ws.get("workspace_id") or rp.get("workspace_id") or "", rp.get("pane_id") or "", tab.get("tab_id") or rp.get("tab_id") or ""))
' 2>/dev/null || true
}

_hl_tab_create() {
  local mid="$1" wid="$2" cwd="$3" label="$4" raw
  raw="$(herdr tab create --workspace "$wid" --cwd "$cwd" --label "$label" --no-focus 2>&1)" || true
  printf '%s' "$raw" | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(0)
d=json.loads(raw[s:e+1]); r=d.get("result") or d
tab=(r.get("tab") or {}); rp=(r.get("root_pane") or r.get("pane") or {})
print("%s\t%s" % (tab.get("tab_id") or rp.get("tab_id") or "", rp.get("pane_id") or ""))
' 2>/dev/null || true
}

_hl_pane_split() {
  local mid="$1" pane="$2" cwd="$3" direction="${4:-right}"
  local raw
  raw="$(herdr pane split "$pane" --direction "$direction" --cwd "$cwd" --no-focus 2>&1)" || true
  printf '%s' "$raw" | _hl_json_field 'result.pane.pane_id'
}

# True when workspace $1 already has a tab whose label is exactly $2.
_hl_tab_has_label() {
  local wid="$1" want="$2"
  herdr tab list --workspace "$wid" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(1)
d=json.loads(raw[s:e+1])
tabs=(d.get("result") or {}).get("tabs") or d.get("tabs") or []
want=sys.argv[1]
for t in tabs:
    if (t.get("label") or "")==want:
        raise SystemExit(0)
raise SystemExit(1)
' "$want" 2>/dev/null
}

# Print pane_id of the first pane in workspace $1 whose label is $2, else empty.
_hl_pane_id_by_label() {
  local wid="$1" want="$2"
  herdr pane list --workspace "$wid" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(0)
d=json.loads(raw[s:e+1])
panes=(d.get("result") or {}).get("panes") or d.get("panes") or []
want=sys.argv[1]
for p in panes:
    if (p.get("label") or "")==want:
        print(p.get("pane_id") or "")
        break
' "$want" 2>/dev/null || true
}

# First pane_id in workspace $1 (any label), else empty.
_hl_first_pane() {
  local wid="$1"
  herdr pane list --workspace "$wid" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(0)
d=json.loads(raw[s:e+1])
panes=(d.get("result") or {}).get("panes") or d.get("panes") or []
if panes:
    print(panes[0].get("pane_id") or "")
' 2>/dev/null || true
}

_hl_close_label() {
  local mid="$1" lab="$2" wid
  wid="$(_hl_ws_id "$mid" "$lab")"
  [ -n "$wid" ] || return 0
  herdr workspace close "$wid" >/dev/null 2>&1 || true
  note "herdr-layout: closed $lab"
}

cmd_herdr_layout() {
  local reset=0 keep=0 arg ans
  for arg in "${ARGS[@]+"${ARGS[@]}"}"; do
    case "$arg" in
      --reset|--replace|--wipe) reset=1 ;;
      --keep) keep=1 ;;
      -h|--help)
        cat <<'H'
herdr-layout — create the standard Herdr sidebar on this machine.

  bash dev.sh herdr-layout           with a TTY: ask whether to reset (default N = keep);
                                     non-TTY: keep existing, create what is missing
  bash dev.sh herdr-layout --keep    keep existing; create only missing panes/tabs
  bash dev.sh herdr-layout --reset   close Home/Editor/Development/Agents, then recreate

Layout: Home · Editor · Development (server | tests) · Agents (Agent 1..4)

Run it inside the container, or from the Mac (it docker-execs into the vscode service).
H
        return 0
        ;;
      *) die "herdr-layout: unknown flag '$arg' (use --reset or --keep)" ;;
    esac
  done
  if [ "$reset" -eq 1 ] && [ "$keep" -eq 1 ]; then
    die "herdr-layout: use either --reset or --keep"
  fi

  if [ "${HERDR_LAYOUT_INNER:-0}" != 1 ] && [ ! -f /.dockerenv ] && [ -z "${DOCKER_DEV_ENV:-}" ]; then
    write_override
    [ -n "$DC_SERVICE" ] || die "herdr-layout: no vscode service in this repository"
    if [ "$reset" -eq 0 ] && [ "$keep" -eq 0 ] && [ -t 0 ]; then
      printf 'Reset existing Home / Editor / Development / Agents panes? [y/N] '
      read -r ans || true
      case "$ans" in y|Y|yes|YES) reset=1 ;; esac
    fi
    local inner_flag="--keep"
    [ "$reset" -eq 1 ] && inner_flag="--reset"
    local script="${DC_WORKSPACE:-/workspace}/dev.sh"
    local -a opts=()
    [ -n "$DC_USER" ] && opts+=(--user "$DC_USER" -e "HOME=/home/$DC_USER" -e "USER=$DC_USER" -e "LOGNAME=$DC_USER")
    [ -n "$DC_WORKSPACE" ] && opts+=(-w "$DC_WORKSPACE")
    opts+=(-e HERDR_LAYOUT_INNER=1)
    note "herdr-layout: running inside $DC_SERVICE ($inner_flag)"
    dc exec ${opts[@]+"${opts[@]}"} "$DC_SERVICE" bash "$script" herdr-layout "$inner_flag"
    return $?
  fi

  command -v herdr >/dev/null 2>&1 || die "herdr is not on PATH inside this container"
  command -v python3 >/dev/null 2>&1 || die "python3 is required for herdr-layout"

  if [ "$reset" -eq 0 ] && [ "$keep" -eq 0 ] && [ -t 0 ]; then
    printf 'Reset existing Home / Editor / Development / Agents panes? [y/N] '
    read -r ans || true
    case "$ans" in y|Y|yes|YES) reset=1 ;; esac
  fi

  local cwd="${DC_WORKSPACE:-}"
  [ -n "$cwd" ] || cwd="$(pwd)"
  local mid=""

  note "herdr-layout: local machine  cwd $cwd"
  if [ "$reset" -eq 1 ]; then
    note "herdr-layout: resetting Home · Editor · Development · Agents"
    local lab
    # Only the four standard labels (+ legacy "Home (~)"). Do not close
    # undocumented labels like "~" or "app" — those may be real workspaces.
    for lab in Home "Home (~)" Editor Development Agents; do
      _hl_close_label "$mid" "$lab"
    done
  fi

  local home_ws editor_ws dev_ws agents_ws line pane tab_id tests_pane n

  home_ws="$(_hl_ws_id "$mid" Home)"
  if [ -z "$home_ws" ]; then
    line="$(_hl_ws_create "$mid" "$cwd" Home)"
    home_ws="$(printf '%s' "$line" | cut -f1)"
    pane="$(printf '%s' "$line" | cut -f2)"
    [ -n "$home_ws" ] || die "herdr-layout: could not create Home"
    [ -n "$pane" ] && herdr pane rename "$pane" home >/dev/null 2>&1 || true
    note "herdr-layout: created Home"
  else
    note "herdr-layout: Home already present"
  fi

  editor_ws="$(_hl_ws_id "$mid" Editor)"
  if [ -z "$editor_ws" ]; then
    line="$(_hl_ws_create "$mid" "$cwd" Editor)"
    editor_ws="$(printf '%s' "$line" | cut -f1)"
    pane="$(printf '%s' "$line" | cut -f2)"
    [ -n "$editor_ws" ] || die "herdr-layout: could not create Editor"
    [ -n "$pane" ] && herdr pane rename "$pane" editor >/dev/null 2>&1 || true
    note "herdr-layout: created Editor"
  else
    note "herdr-layout: Editor already present"
  fi

  dev_ws="$(_hl_ws_id "$mid" Development)"
  if [ -z "$dev_ws" ]; then
    line="$(_hl_ws_create "$mid" "$cwd" Development)"
    dev_ws="$(printf '%s' "$line" | cut -f1)"
    pane="$(printf '%s' "$line" | cut -f2)"
    tab_id="$(printf '%s' "$line" | cut -f3)"
    [ -n "$dev_ws" ] && [ -n "$pane" ] || die "herdr-layout: could not create Development"
    [ -n "$tab_id" ] && herdr tab rename "$tab_id" Development >/dev/null 2>&1 || true
    herdr pane rename "$pane" server >/dev/null 2>&1 || true
    tests_pane="$(_hl_pane_split "$mid" "$pane" "$cwd" right)"
    [ -n "$tests_pane" ] && herdr pane rename "$tests_pane" tests >/dev/null 2>&1 || true
    note "herdr-layout: created Development (server | tests)"
  else
    note "herdr-layout: Development already present"
    # Keep mode: fill a missing tests split without recreating the workspace.
    if [ -z "$(_hl_pane_id_by_label "$dev_ws" tests)" ]; then
      pane="$(_hl_pane_id_by_label "$dev_ws" server)"
      [ -n "$pane" ] || pane="$(_hl_first_pane "$dev_ws")"
      if [ -n "$pane" ]; then
        tests_pane="$(_hl_pane_split "$mid" "$pane" "$cwd" right)"
        if [ -n "$tests_pane" ]; then
          herdr pane rename "$tests_pane" tests >/dev/null 2>&1 || true
          note "herdr-layout: added Development / tests split"
        fi
      fi
    fi
  fi

  agents_ws="$(_hl_ws_id "$mid" Agents)"
  if [ -z "$agents_ws" ]; then
    line="$(_hl_ws_create "$mid" "$cwd" Agents)"
    agents_ws="$(printf '%s' "$line" | cut -f1)"
    pane="$(printf '%s' "$line" | cut -f2)"
    tab_id="$(printf '%s' "$line" | cut -f3)"
    [ -n "$agents_ws" ] && [ -n "$pane" ] || die "herdr-layout: could not create Agents"
    [ -n "$tab_id" ] && herdr tab rename "$tab_id" "Agent 1" >/dev/null 2>&1 || true
    note "herdr-layout: created Agents / Agent 1"
    for n in 2 3 4; do
      line="$(_hl_tab_create "$mid" "$agents_ws" "$cwd" "Agent ${n}")"
      tab_id="$(printf '%s' "$line" | cut -f1)"
      pane="$(printf '%s' "$line" | cut -f2)"
      [ -n "$tab_id" ] || die "herdr-layout: could not create Agent $n"
      note "herdr-layout: created Agents / Agent $n"
    done
  else
    note "herdr-layout: Agents already present"
    # Keep mode: create only the missing Agent N tabs (1..4).
    for n in 1 2 3 4; do
      if _hl_tab_has_label "$agents_ws" "Agent ${n}"; then
        continue
      fi
      line="$(_hl_tab_create "$mid" "$agents_ws" "$cwd" "Agent ${n}")"
      tab_id="$(printf '%s' "$line" | cut -f1)"
      pane="$(printf '%s' "$line" | cut -f2)"
      if [ -z "$tab_id" ]; then
        note "herdr-layout: could not create Agent $n (skipped)"
        continue
      fi
      note "herdr-layout: created Agents / Agent $n"
    done
  fi

  [ -n "$home_ws" ] && herdr workspace focus "$home_ws" >/dev/null 2>&1 || true
  note "herdr-layout: ready — Home · Editor · Development · Agents"
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
  rebuild [service]     rebuild images and recreate containers (cache on by
                        default; same idea as VS Code "Rebuild and Reopen")
  ls                    repositories this launcher can address, and their state
  config                resolved configuration; writes nothing
  doctor                environment diagnosis; writes nothing
  agents                live machines and agents, refreshed from the Mac catalog
                        same as: dbdev agents
  ask <#> "..."         send agent # a prompt plus your reply address
                        ask <id> <pane> "..." is the same, using the table columns
  herdr-layout          create Home · Editor · Development · Agents on this
                        machine. --keep leaves current panes and fills gaps;
                        --reset closes those four then recreates them.
                        Bare with a TTY asks whether to reset (default N).
  help                  this text

Flags
  --repo <name>         unambiguous repository target
  --all                 fan the verb out over every addressable repository
  --project <name>      override the compose project name
  --recreate            with up, recreate containers to apply compose changes
  --no-cache            with rebuild (or build), ignore Docker layer cache and
                        pull base images — full wipe, much slower
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
    rebuild) cmd_rebuild ;;
    config)  cmd_config ;;
    doctor)  cmd_doctor ;;
    agents) cmd_herdr_agents ;;
    ask)    cmd_herdr_ask "${ARGS[@]+"${ARGS[@]}"}" ;;
    herdr-layout) cmd_herdr_layout ;;
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
