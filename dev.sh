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

VERBS=" setup up down stop start restart ps logs shell exec build rebuild satellite ls config doctor ports agents ask reply check wait notify cancel lanes lead peers herdr-layout help "

# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

TARGET_REPO=""
VERB=""
ALL=0
WITH_VOLUMES=0
RECREATE=0
NO_CACHE=0
ASSUME_YES=0
SHOW_STATUS=0
REQ_WORKSPACE=""
ALLOW_OTHER_WS=0
PROJECT_OVERRIDE=""
ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all) ALL=1; shift ;;
    --volumes) WITH_VOLUMES=1; shift ;;
    --recreate) RECREATE=1; shift ;;
    --no-cache) NO_CACHE=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --status) SHOW_STATUS=1; shift ;;
    --workspace) [ $# -ge 2 ] || die "--workspace needs a workspace name"; REQ_WORKSPACE="$2"; shift 2 ;;
    --allow-other-workspace) ALLOW_OTHER_WS=1; shift ;;
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

# `project` in the [compose] table of .devcontainer/dck.toml, or empty. awk, not
# tomllib: the Mac's system python3 may predate it. A comment after the value is
# fine; a value that is not a quoted string is ignored.
dck_toml_project() {
  local toml="$1/.devcontainer/dck.toml"
  [ -f "$toml" ] || return 0
  awk '
    /^[[:space:]]*\[/ { in_compose = ($0 ~ /^[[:space:]]*\[compose\][[:space:]]*(#.*)?$/); next }
    in_compose && /^[[:space:]]*project[[:space:]]*=/ {
      v = $0; sub(/^[^=]*=[[:space:]]*/, "", v)
      if (match(v, /^"[^"]*"/) || match(v, /^\047[^\047]*\047/)) {
        print substr(v, 2, RLENGTH - 2); exit
      }
    }
  ' "$toml"
}

# Precedence: --project, DEVSH_PROJECT, dck.toml [compose] project (dck itself
# runs with that project, so compose must match it for every verb), then
# COMPOSE_PROJECT_NAME from the environment or docker/local/.env, then the
# compose file's top-level name:.
resolve_project() {
  PROJECT=""; PROJECT_FROM=""
  if [ -n "$PROJECT_OVERRIDE" ]; then
    PROJECT="$PROJECT_OVERRIDE"; PROJECT_FROM="--project flag"; return 0
  fi
  if [ -n "${DEVSH_PROJECT:-}" ]; then
    PROJECT="$DEVSH_PROJECT"; PROJECT_FROM="DEVSH_PROJECT in the environment"; return 0
  fi
  local t
  t="$(dck_toml_project "$REPO_ROOT")"
  if [ -n "$t" ]; then
    case "$t" in
      *[!a-z0-9_-]*|[_-]*) die "invalid [compose] project '$t' in .devcontainer/dck.toml (lowercase letters, digits, _ and -)" ;;
    esac
    PROJECT="$t"; PROJECT_FROM="[compose] project in .devcontainer/dck.toml"; return 0
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
  # Auto-created .env files ship SERVICE_PERMISSIONS= empty from the example;
  # up/rebuild must not leave that. Same stamp as setup, a no-op when current.
  stamp_env_permissions
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

# Stamp SERVICE_PERMISSIONS=<uid>:<gid> into every .env that declares the key.
# Matches the repositories' own utils.sh: files without the key are left alone,
# and a file already carrying the current value is not rewritten (up/rebuild
# call this on every run). Values are never printed.
stamp_env_permissions() {
  local f target perms
  perms="$(id -u):$(id -g)"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    target="${f%.example}"
    [ -f "$target" ] || continue
    grep -q '^[[:space:]]*SERVICE_PERMISSIONS=' "$target" 2>/dev/null || continue
    grep -qx "[[:space:]]*SERVICE_PERMISSIONS=$perms" "$target" 2>/dev/null && continue
    # Rewritten through a temp file in the same directory, never with
    # `sed -i.bak`: that leaves a backup of a .env — real values and all — next
    # to it, and `.env.<suffix>` is covered by none of these repositories'
    # gitignore rules. A failed run must not be able to strand secrets in a
    # trackable file.
    stamp_permissions "$target" "$perms" || die "could not update SERVICE_PERMISSIONS in $target"
  done < <(env_examples)
}

cmd_setup() {
  local created=0
  ensure_env_from_examples
  created=$((created + _ensure_created))

  stamp_env_permissions

  ensure_external_networks
  created=$((created + _ensure_created))

  # The folder can exist with only devcontainer-kit's tracked dck.toml in it, so
  # the test is the active file, not the folder. cp never replaces dck.toml:
  # the example folder does not carry one.
  if [ ! -f "$REPO_ROOT/.devcontainer/devcontainer.json" ] && [ -d "$REPO_ROOT/.devcontainer_example" ]; then
    mkdir -p "$REPO_ROOT/.devcontainer"
    cp -R "$REPO_ROOT/.devcontainer_example/." "$REPO_ROOT/.devcontainer/"
    note "created .devcontainer/devcontainer.json from .devcontainer_example/"
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

# --------------------------------------------------------------------------
# devcontainer-kit repositories
# --------------------------------------------------------------------------

# A repository whose container is rendered by devcontainer-kit carries
# .devcontainer/dck.toml. Its `up` and `rebuild` go through `dck`, which adds what
# plain compose cannot: the runtime overlay that shares the host's coding-agent
# accounts (ak), the host SSH agent socket, the dedicated key sshd authorizes,
# and the Herdr machine and mesh. Every other verb stays on compose, on the same
# project. DEVSH_DCK=0 forces compose; without dck installed, compose is used
# and the gap is said once.
DCK_BIN=""
use_dck() {
  [ "${DEVSH_DCK:-1}" != 0 ] || return 1
  [ -f "$REPO_ROOT/.devcontainer/dck.toml" ] || return 1
  if [ -z "$DCK_BIN" ]; then
    if command -v dck >/dev/null 2>&1; then
      DCK_BIN="$(command -v dck)"
    elif [ -x "${DCK_INSTALL_DIR:-$HOME/.local/share/dck}/bin/dck" ]; then
      DCK_BIN="${DCK_INSTALL_DIR:-$HOME/.local/share/dck}/bin/dck"
    else
      note "devcontainer-kit (dck) is not installed: using plain compose. The host's agent accounts and the Herdr machine need it — install it from https://github.com/DailybotHQ/devcontainer-kit (on a Dailybot Mac: /db-host-kit-onboard → update)."
      DEVSH_DCK=0
      return 1
    fi
  fi
  return 0
}

# dck on this repository and project. --project keeps the project dev.sh
# resolved (dck.toml [compose] project first, see resolve_project) even when
# docker/local/.env is missing or disagrees.
dck_run() {
  "$DCK_BIN" --repo "$REPO_ROOT" --project "$PROJECT" "$@"
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
  if use_dck; then
    note "starting ${svc[*]} (project $PROJECT) through devcontainer-kit"
    local -a up_args=()
    [ "$RECREATE" -eq 1 ] && up_args+=(--recreate)
    # Only the services named on the command line; dck itself starts runServices.
    if [ "${#ARGS[@]}" -gt 0 ]; then
      dck_run up ${up_args[@]+"${up_args[@]}"} "${ARGS[@]}"
    else
      dck_run up ${up_args[@]+"${up_args[@]}"}
    fi
    return
  fi
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
  if use_dck; then
    local -a rb_args=()
    [ "$NO_CACHE" -eq 1 ] && rb_args+=(--no-cache)
    note "rebuilding ${svc[*]} (project $PROJECT) through devcontainer-kit"
    dck_run rebuild ${rb_args[@]+"${rb_args[@]}"} "${svc[@]}"
    return
  fi
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

# --------------------------------------------------------------------------
# Workspace satellites
# --------------------------------------------------------------------------

# A satellite is a second instance of a dev service (<svc>satellite) in its own
# compose project, with its own files and ports, started for a Dailybot
# workspace by the repository's docker.sh satellite.*. In a repository with
# .devcontainer/dck.toml it goes through dck (v0.3.5+), which gives it every
# host step the main service gets: the authorized dck key (Herdr can attach),
# copied keys, host-profile accounts, git identity, HERDR_PEERS_SELF, its own
# Herdr machine and, with --seed-state, the gh / Dailybot login of the primary.
# Plain compose is the fallback only when the repository has no dck.toml or dck
# is not installed. The main service and its project are never touched.
#
#   bash dev.sh satellite <up|down|stop|ps|logs|shell|rebuild>
#     --project P --service S [--compose-file F]... [--seed-state |
#     --seed-state-from VOLUME] [--label TEXT] [--recreate] [--no-cache]
#
# Without --label, up and rebuild name the Herdr machine from
# DAILYBOT_WS_HERDR_LABEL (exported by `dbdev workspace`), else dck's default.
# Compose files are relative to the caller's directory (docker.sh runs from
# docker/local). --project here names the satellite's project; the primary's
# project is resolved as for every other verb.
SAT_PROJECT=""

# The state volume key in [compose] of .devcontainer/dck.toml ("state" when
# unset), same parsing rules as dck_toml_project.
dck_toml_state_volume() {
  local toml="$1/.devcontainer/dck.toml" v=""
  if [ -f "$toml" ]; then
    v="$(awk '
      /^[[:space:]]*\[/ { in_compose = ($0 ~ /^[[:space:]]*\[compose\][[:space:]]*(#.*)?$/); next }
      in_compose && /^[[:space:]]*state_volume[[:space:]]*=/ {
        v = $0; sub(/^[^=]*=[[:space:]]*/, "", v)
        if (match(v, /^"[^"]*"/) || match(v, /^\047[^\047]*\047/)) {
          print substr(v, 2, RLENGTH - 2); exit
        }
      }
    ' "$toml")"
  fi
  printf '%s' "${v:-state}"
}

cmd_satellite() {
  local action="${ARGS[0]:-}" service="" seed="" seed_primary=0 label=""
  local files=() rest=() f abs
  case "$action" in
    up|down|stop|ps|logs|shell|rebuild) ;;
    "") die "satellite needs an action: up, down, stop, ps, logs, shell or rebuild" ;;
    *) die "unknown satellite action '$action' (up, down, stop, ps, logs, shell, rebuild)" ;;
  esac
  set -- ${ARGS[@]+"${ARGS[@]:1}"}
  while [ $# -gt 0 ]; do
    case "$1" in
      --service) [ $# -ge 2 ] || die "--service needs a name"; service="$2"; shift 2 ;;
      --compose-file) [ $# -ge 2 ] || die "--compose-file needs a file"; files+=("$1" "$2"); shift 2 ;;
      --seed-state) seed_primary=1; shift ;;
      --seed-state-from) [ $# -ge 2 ] || die "--seed-state-from needs a volume name"; seed="$2"; shift 2 ;;
      --label) [ $# -ge 2 ] || die "--label needs a text"; label="$2"; shift 2 ;;
      *) rest+=("$1"); shift ;;
    esac
  done
  [ -n "$SAT_PROJECT" ] || die "satellite needs --project (a satellite runs in its own compose project, never $PROJECT)"
  [ "$SAT_PROJECT" != "$PROJECT" ] || die "satellite --project must differ from the primary project '$PROJECT'"
  case "$SAT_PROJECT" in
    *[!a-z0-9_-]*|[_-]*) die "invalid satellite project '$SAT_PROJECT' (lowercase letters, digits, _ and -)" ;;
  esac
  [ -n "$service" ] || die "satellite needs --service (the one service to act on, e.g. djangovscodesatellite)"
  safe_name "$service" || die "invalid satellite service '$service'"
  [ -z "$seed" ] || safe_name "$seed" || die "invalid --seed-state-from '$seed'"
  if [ "$action" != up ] && [ "$action" != rebuild ]; then
    [ -z "$seed$label" ] && [ "$seed_primary" -eq 0 ] || die "--seed-state, --seed-state-from and --label only apply to satellite up and rebuild"
  fi
  [ "${#rest[@]}" -eq 0 ] || [ "$action" = logs ] || die "unexpected argument '${rest[0]}' for satellite $action"
  # Compose files resolve against the caller's directory; absolute from here on.
  local file_args=() i
  for ((i = 0; i < ${#files[@]}; i += 2)); do
    f="${files[i+1]}"
    [ -f "$f" ] || die "satellite compose file not found: $f"
    abs="$(cd -P "$(dirname "$f")" && pwd)/$(basename "$f")"
    file_args+=(--compose-file "$abs")
  done

  if use_dck; then
    local -a base=("$DCK_BIN" --repo "$REPO_ROOT" --project "$SAT_PROJECT")
    base+=(${file_args[@]+"${file_args[@]}"} --service "$service")
    local -a up_args=()
    if [ "$seed_primary" -eq 1 ] && [ -z "$seed" ]; then
      seed="${PROJECT}_$(dck_toml_state_volume "$REPO_ROOT")"
      if ! docker volume inspect "$seed" >/dev/null 2>&1; then
        note "satellite: no primary state volume $seed yet; starting without a seeded login"
        seed=""
      fi
    fi
    [ -n "$seed" ] && up_args+=(--seed-state-from "$seed")
    # The Herdr label: --label, else the one `dbdev workspace` exports
    # ("<id> - API · WS <name>"), else dck's own (DCK_SATELLITE_LABEL, then
    # "<project> · <service>").
    if [ -z "$label" ] && { [ "$action" = up ] || [ "$action" = rebuild ]; }; then
      label="${DAILYBOT_WS_HERDR_LABEL:-}"
    fi
    [ -n "$label" ] && up_args+=(--label "$label")
    case "$action" in
      up)
        [ "$RECREATE" -eq 1 ] && up_args+=(--recreate)
        note "satellite $service (project $SAT_PROJECT) through devcontainer-kit"
        "${base[@]}" up ${up_args[@]+"${up_args[@]}"} ;;
      rebuild)
        # dck builds only the main service; the satellite's image is built with
        # compose on the same project and files, then dck recreates it.
        local -a build_args=()
        [ "$NO_CACHE" -eq 1 ] && build_args=(--no-cache --pull)
        note "satellite $service (project $SAT_PROJECT): building, then recreating through devcontainer-kit"
        sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- build ${build_args[@]+"${build_args[@]}"} "$service"
        "${base[@]}" up --recreate ${up_args[@]+"${up_args[@]}"} ;;
      down)  "${base[@]}" down ;;
      stop)  "${base[@]}" stop ;;
      ps)    "${base[@]}" ps ;;
      logs)  "${base[@]}" logs ${rest[@]+"${rest[@]}"} ;;
      shell) "${base[@]}" shell ;;
    esac
    return
  fi

  # Plain compose: no host steps (no authorized key, no accounts, empty state).
  [ -z "$seed" ] && [ "$seed_primary" -eq 0 ] || note "satellite: the login seed needs devcontainer-kit; starting without it"
  case "$action" in
    up)
      if [ "$RECREATE" -eq 1 ]; then
        sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- up -d --force-recreate --no-deps "$service"
      else
        sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- up -d --no-recreate --no-deps "$service"
      fi ;;
    rebuild)
      local -a build_args=()
      [ "$NO_CACHE" -eq 1 ] && build_args=(--no-cache --pull)
      sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- build ${build_args[@]+"${build_args[@]}"} "$service"
      sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- up -d --force-recreate --no-deps "$service" ;;
    down)  sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- rm -sf "$service" ;;
    stop)  sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- stop "$service" ;;
    ps)    sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- ps "$service" ;;
    logs)
      # Follow by default, like `dck … logs` (which takes only --no-follow).
      local follow=(-f) log_args=() a
      for a in ${rest[@]+"${rest[@]}"}; do
        if [ "$a" = --no-follow ]; then follow=(); else log_args+=("$a"); fi
      done
      sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- logs ${follow[@]+"${follow[@]}"} ${log_args[@]+"${log_args[@]}"} "$service" ;;
    shell)
      local -a opts=(-it)
      [ -n "$DC_USER" ] && opts+=(-u "$DC_USER")
      [ -n "$DC_WORKSPACE" ] && opts+=(-w "$DC_WORKSPACE")
      sat_dc "$service" ${file_args[@]+"${file_args[@]}"} -- exec "${opts[@]}" "$service" bash -l ;;
  esac
}

# sat_dc <service> [--compose-file F]... -- <compose args...>: compose on the
# satellite's project and files (the repository's compose file when none given).
sat_dc() {
  shift
  local -a fargs=()
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do
    [ "$1" = --compose-file ] && fargs+=(-f "$2")
    shift 2
  done
  [ $# -gt 0 ] && shift
  [ "${#fargs[@]}" -gt 0 ] || fargs=(-f "$DC_COMPOSE")
  resolve_compose_bin
  if [ -n "$COMPOSE_SUB" ]; then
    "$COMPOSE_BIN" "$COMPOSE_SUB" -p "$SAT_PROJECT" "${fargs[@]}" "$@"
  else
    "$COMPOSE_BIN" -p "$SAT_PROJECT" "${fargs[@]}" "$@"
  fi
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

# Show the repository's published ports from the host, or the workspace port
# contract plus live listeners when invoked inside a devcontainer. Satellite
# overlays inject DAILYBOT_EXPOSED_PORTS as comma-separated
# service:internal:direct:focus records; primary containers can still report
# their live listeners when that metadata is absent.
cmd_ports() {
  note "repository      $REPO_ROOT"
  note "compose project $PROJECT"
  local helper="$REPO_ROOT/scripts/workspace_ports_display.py"
  [ -f "$helper" ] || die "ports helper missing: $helper (run bash scripts/dev-stack-sync.sh from the hub)"
  # Every devcontainer (VS Code, Cursor, Herdr) has /.dockerenv; a stray
  # DAILYBOT_EXPOSED_PORTS in a host shell must not select this branch.
  if [ -f /.dockerenv ]; then
    note "context         container"
    python3 "$helper" container "${DAILYBOT_EXPOSED_PORTS:-}" "${DAILYBOT_WORKSPACE_ID:-}" "${DAILYBOT_WORKSPACES_ROOT:-/run/dailybot/workspaces}" "${DAILYBOT_PORT_REPO:-${DC_SERVICE:-}}"
    return $?
  fi
  local workspace_state="$REPO_ROOT/../workspace.json"
  if [ -f "$workspace_state" ]; then
    note "context         workspace host"
    python3 "$helper" workspace "$workspace_state" "$(basename "$REPO_ROOT")"
    return $?
  fi
  note "context         host"
  # Scoped to this repository's services like `ps`: the compose project is
  # shared, so an unscoped `compose ps` would list every repository.
  cmd_ps
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
      REPO_ROOT="$root"
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
  ' "${sources[@]}" | while read -r _ peer_port; do
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

# --------------------------------------------------------------------------
# Agent mesh — herdr-peers (the DeepWorkPlan herdr addon) over the Dailybot
# Herdr catalog.
#
# `agents`, `ask` and the verbs beside them are thin: herdr-peers owns the
# stamp, the one-reply grant, the loop guard, the depth and fan-out limits,
# the scope check, the delegation log and the lead record. dev.sh adds what
# is Dailybot's: the Mac catalog copy inside a container (herdr_prepare_mesh),
# the `#` shortcuts of the list, the workspace rule — an agent talks to the
# agents of its own workspace unless the human names another one — and a
# reply address that survives a pane older than its machine id. The same
# verbs exist on the Mac as `dbdev <verb>`.
#
# A received message that carries `[herdr-peers]` is handled with
# `bash dev.sh check -` (never answered by hand); the reply goes through
# `bash dev.sh reply <from> <id> "..."`, exactly once.
# --------------------------------------------------------------------------

mesh_require() {
  command -v herdr >/dev/null 2>&1 || die "herdr is not on PATH"
  command -v python3 >/dev/null 2>&1 || die "python3 is required"
  command -v herdr-peers >/dev/null 2>&1 || die "herdr-peers is not on PATH — devcontainer-kit images (v1.0.0+) and the host kit ship it; otherwise: npx --yes skills add https://github.com/DailybotHQ/herdr-peers/tree/v1.0.0 --skill herdr-peers -g -y"
}

# HERDR_PEERS_SELF names this machine as the Mac catalog knows it (dck pushes
# it at up). A pane opened before that push, or a state volume reused from an
# earlier workspace on the same SID, can still carry a machine that no longer
# exists, and a reply to that address goes nowhere. Keep the variable only
# when the catalog lists it; otherwise herdr-peers finds this server by its
# terminal id.
mesh_check_self() {
  local id="${HERDR_PEERS_SELF:-}"
  [ -n "$id" ] || return 0
  id="${id%%:*}"
  if herdr machine list --json 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
ids = {str(m.get("id")) for m in data if isinstance(m, dict)} if isinstance(data, list) else set()
sys.exit(0 if sys.argv[1] in ids else 1)
' "$id"; then
    return 0
  fi
  note "mesh: HERDR_PEERS_SELF=${id} is not a machine of this catalog (a pane older than its machine id?); this session's address is taken from its pane instead" >&2
  unset HERDR_PEERS_SELF
}

# The workspace rule as a herdr-peers scope. Inside a workspace satellite the
# allow-list is that workspace's machines plus the Mac; inside a primary it is
# the primaries plus the Mac; on the Mac, the human's console, everything.
# A scope the caller set (HERDR_PEERS_SCOPE), or --any-workspace, wins.
mesh_default_scope() {
  in_container || return 0
  herdr machine list --json 2>/dev/null | python3 -c '
import json, sys
ws = sys.argv[1]
try:
    machines = json.load(sys.stdin)
except Exception:
    machines = []
machines = [m for m in machines if isinstance(m, dict)] if isinstance(machines, list) else []
# A satellite without DAILYBOT_WORKSPACE_ID still names its workspace in its
# own Herdr label ("<sid> - <Repo> · WS <name>").
if not ws:
    me = sys.argv[2].split(":", 1)[0] if len(sys.argv) > 2 else ""
    for m in machines:
        label = str(m.get("label") or "")
        if me and str(m.get("id")) == me and " WS " in label:
            ws = label.rsplit(" WS ", 1)[1].strip()
keep = ["local"]
for m in machines:
    if not m.get("enabled") or not m.get("id"):
        continue
    label = str(m.get("label") or "")
    target = str(m.get("target") or "")
    if target in ("dailybot-mac", "dck-host") or label.strip() == "0 - Mac":
        keep.append(str(m["id"]))
    elif ws:
        if label.endswith(" WS " + ws):
            keep.append(str(m["id"]))
    elif " WS " not in label:
        keep.append(str(m["id"]))
print(",".join(keep))
' "${DAILYBOT_WORKSPACE_ID:-}" "${HERDR_PEERS_SELF:-}"
}

# The fleet as herdr-peers lists it, never narrowed by a scope, so the `#`
# of `agents` and the `#` that `ask` resolves come from the same numbering.
mesh_list_json() {
  env -u HERDR_PEERS_SCOPE herdr-peers list --json
}

# Live machines and the agents on them, one row per agent. The row marked
# `<- you` is this session. `#` is a shortcut for this listing only; ADDRESS
# (<machine>:<pane>) is the stable address.
cmd_herdr_agents() {
  mesh_require
  herdr_prepare_mesh
  mesh_check_self
  local listing scope
  listing="$(mesh_list_json)" || die "herdr-peers list failed"
  scope="$(mesh_default_scope)"
  MESH_LISTING="$listing" MESH_SCOPE="$scope" MESH_WS="${DAILYBOT_WORKSPACE_ID:-}" python3 - <<'PY'
import json, os, sys

data = json.loads(os.environ["MESH_LISTING"] or "{}")
rows = data.get("rows") if isinstance(data, dict) else None
rows = rows if isinstance(rows, list) else []
scope = [s for s in (os.environ.get("MESH_SCOPE") or "").split(",") if s]
ws = os.environ.get("MESH_WS") or ""

def paint(code, text):
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return "\033[%sm%s\033[0m" % (code, text)

state_color = {"idle": "32", "working": "33", "blocked": "31", "done": "36",
               "unreachable": "90", "no agents": "90", "no_agent": "90"}

you = None
shown = []
for row in rows:
    if not isinstance(row, dict):
        continue
    n = row.get("n")
    short = str(n) if n else "-"
    machine = str(row.get("machine") or "")
    label = str(row.get("label") or machine)
    if machine == "local":
        label = "this machine" if label == "local" else label
    addr = str(row.get("address") or "-")
    mine = bool(row.get("you"))
    if mine:
        you = short
    inside = (not scope) or machine in scope
    shown.append((short, label, addr, str(row.get("agent") or "-"),
                  str(row.get("state") or "-"),
                  str(row.get("title") or "").replace("\n", " ")[:36], mine, inside))

headers = ("#", "MACHINE", "ADDRESS", "AGENT", "STATE", "TITLE")
widths = [len(h) for h in headers]
for row in shown:
    for i, cell in enumerate(row[:6]):
        if i != 5:
            widths[i] = max(widths[i], len(cell))

def line(cells, state=None, mine=False, inside=True):
    parts = []
    for i, cell in enumerate(cells):
        text = cell.ljust(widths[i]) if i < 5 else cell
        if i == 4 and state:
            text = paint(state_color.get(state, "0"), text)
        parts.append(text)
    body = "  " + "  ".join(parts).rstrip()
    if mine:
        body = paint("1;32", body) + "  <- you"
    elif not inside:
        body = paint("90", body) + "  (outside your workspace)"
    return body

if you:
    print(paint("1;32", "  you are #%s. That row is this session." % you))
else:
    print("  this session is not a row in the list (not an agent pane).")
print()
print(paint("1", line(headers)))
print("  " + "  ".join("-" * w for w in widths))
if not shown:
    print("  (no enabled machines)")
for row in shown:
    print(line(row[:6], row[4], row[6], row[7]))

example = next((r for r in shown if r[0] != "-" and not r[6] and r[7]), None)
print()
print("  # is the short id from this listing; ADDRESS is the stable one.")
print("  bash dev.sh ask <#> \"Prompt...\"      (dbdev ask <#> \"Prompt...\" on the Mac)")
if example:
    print("  bash dev.sh ask %s \"Prompt...\"      -> %s" % (example[0], example[2]))
if ws:
    print("  workspace %s: ask stays inside it; add --any-workspace only when the human named another agent." % ws)
elif scope:
    print("  primary: ask stays with the primaries and the Mac; add --any-workspace only when the human named another agent.")
print("  Protocol: herdr-peers. A received [herdr-peers] message: bash dev.sh check -   then reply once: bash dev.sh reply <from> <id> \"...\"")
PY
}

# `#` from the current listing -> <machine>:<pane>.
mesh_resolve_number() {
  mesh_list_json 2>/dev/null | MESH_WANT="$1" python3 -c '
import json, os, sys
want = int(os.environ["MESH_WANT"])
try:
    rows = (json.load(sys.stdin) or {}).get("rows") or []
except Exception:
    rows = []
for row in rows:
    try:
        n = int(row.get("n")) if isinstance(row, dict) and row.get("n") is not None else None
    except (TypeError, ValueError):
        n = None
    if n == want and row.get("address"):
        print(row["address"]); sys.exit(0)
sys.exit(1)
'
}

# Send one prompt through herdr-peers. Targets: <#> from the listing,
# <machine-id>:<pane>, the older <machine-id> <pane> pair, or `lead`
# (--plan). The reply arrives in this pane as a [herdr-peers] message.
cmd_herdr_ask() {
  mesh_require
  herdr_prepare_mesh
  mesh_check_self
  local any=0 target="" number="" text="" rc
  local pass=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --any-workspace) any=1; shift ;;
      --from)
        [ $# -ge 2 ] || die "ask --from needs <machine-id>:<pane> (or <machine-id> <pane>)"
        if [ $# -ge 3 ] && [[ "$2" != *:* ]] && [[ "$3" == w*:p* ]]; then
          pass+=(--from "$2:$3"); shift 3
        else
          pass+=(--from "$2"); shift 2
        fi
        ;;
      --scope|--fanout|--reason|--task|--plan|--profile|--vendor|--worktree|--pane)
        [ $# -ge 2 ] || die "ask $1 needs a value"
        pass+=("$1" "$2"); shift 2 ;;
      --) shift; break ;;
      -) break ;;
      -*) die "unknown ask flag '$1' (bash dev.sh ask [--any-workspace] [--from <machine>:<pane>] [--scope|--fanout|--reason|--task|--plan|--profile|--vendor|--worktree|--pane <v>] <#>|<machine>:<pane>|<machine> <pane>|lead \"prompt\")" ;;
      *) break ;;
    esac
  done
  [ $# -ge 1 ] || die 'ask needs a target: <#> from `bash dev.sh agents`, <machine-id>:<pane>, <machine-id> <pane>, or lead'
  if [[ "$1" =~ ^[0-9]+$ ]]; then
    number="$1"; shift
    target="$(mesh_resolve_number "$number")" || die "no agent #${number} in the current listing; run: bash dev.sh agents"
  elif [ "$1" = lead ]; then
    target=lead; shift
  elif [[ "$1" == *:* ]]; then
    target="$1"; shift
  else
    case "$1" in
      *[!0-9a-fA-F]*) die "target must be <#>, <machine-id>:<pane>, <machine-id> <pane> or lead (machine ids are hex: bash dev.sh agents)" ;;
    esac
    [ $# -ge 2 ] || die "ask <machine-id> needs its <pane> (w5:p2) and a prompt"
    case "$2" in
      w*:p*) ;;
      *) die "pane must look like w5:p2 (the ADDRESS column from: bash dev.sh agents)" ;;
    esac
    target="$1:$2"; shift 2
  fi
  [ $# -ge 1 ] || die "ask needs a prompt (or - to read it from stdin)"
  if [ $# -eq 1 ] && [ "$1" = - ]; then
    text=-
  else
    text="$*"
  fi
  [ -n "$text" ] || die "ask needs a prompt"
  if [ "$any" -eq 1 ]; then
    export HERDR_PEERS_SCOPE='*'
  elif [ -z "${HERDR_PEERS_SCOPE:-}" ]; then
    local scope
    scope="$(mesh_default_scope)"
    [ -z "$scope" ] || export HERDR_PEERS_SCOPE="$scope"
  fi
  local errf id
  errf="$(mktemp "${TMPDIR:-/tmp}/devsh-ask.XXXXXX")"
  if id="$(herdr-peers ask ${pass[@]+"${pass[@]}"} "$target" "$text" 2>"$errf")"; then
    rc=0
  else
    rc=$?
  fi
  [ -s "$errf" ] && cat "$errf" >&2
  if [ $rc -ne 0 ]; then
    if grep -q 'out of scope' "$errf" 2>/dev/null; then
      note "mesh: ${target} is outside your workspace; an agent talks to its own workspace unless the human named that agent — then: bash dev.sh ask --any-workspace ..." >&2
    fi
    rm -f "$errf"
    exit $rc
  fi
  rm -f "$errf"
  [ -z "$id" ] || printf '%s\n' "$id"
  note "asked ${target}${number:+ (#${number})}"
  note "the reply lands in this pane as a [herdr-peers] message: run  bash dev.sh check -  on it before using it; or block for it: bash dev.sh wait ${id:-<id>}"
}

# The rest of the protocol, unchanged: reply, check, wait, notify, cancel,
# lanes, lead — and `peers <verb> ...` for anything else herdr-peers has.
cmd_herdr_peers() {
  local verb="$1"; shift
  mesh_require
  case "$verb" in
    peers) [ $# -ge 1 ] || die "peers needs a herdr-peers verb: bash dev.sh peers --help"; verb="$1"; shift ;;
  esac
  case "$verb" in
    check|cancel|log|--help|-h) ;;
    *) herdr_prepare_mesh ;;
  esac
  mesh_check_self
  # The workspace rule binds every outgoing message, not only `ask`.
  case "$verb" in
    ask|notify)
      if [ -z "${HERDR_PEERS_SCOPE:-}" ]; then
        local scope
        scope="$(mesh_default_scope)"
        [ -z "$scope" ] || export HERDR_PEERS_SCOPE="$scope"
      fi
      ;;
  esac
  exec herdr-peers "$verb" "$@"
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
try:
    d = json.loads(raw[start:end + 1])
except ValueError:
    raise SystemExit(0)
cur = d
for part in sys.argv[1].split("."):
    if not isinstance(cur, dict):
        cur = ""
        break
    cur = cur.get(part)
if cur is None or isinstance(cur, (dict, list)):
    cur = ""
print(cur)
' "$1" 2>/dev/null || true
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
  local wid="$1" want="$2" raw
  # Captured first: with pipefail, a non-zero herdr exit would otherwise mask
  # the parser's verdict (0 = present) as 1 = absent and duplicate the tab.
  raw="$(herdr tab list --workspace "$wid" 2>/dev/null)" || true
  printf '%s' "$raw" | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
# Exit 2 = unreadable output (unknown), 1 = readable and label absent.
if s<0: raise SystemExit(2)
try:
    d=json.loads(raw[s:e+1])
except ValueError:
    raise SystemExit(2)
tabs=(d.get("result") or {}).get("tabs") or d.get("tabs") or []
want=sys.argv[1]
for t in tabs:
    if (t.get("label") or "")==want:
        raise SystemExit(0)
raise SystemExit(1)
' "$want" 2>/dev/null
}

# Number of panes in workspace $1; prints 0 when the list is unreadable.
# Herdr `pane list` carries no label field (pane rename is not reflected in
# it), so a layout is judged by pane count, never by pane label.
_hl_pane_count() {
  local wid="$1" raw
  raw="$(herdr pane list --workspace "$wid" 2>/dev/null)" || true
  printf '%s' "$raw" | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0:
    print(0); raise SystemExit(0)
try:
    d=json.loads(raw[s:e+1])
except ValueError:
    print(0); raise SystemExit(0)
panes=(d.get("result") or {}).get("panes") or d.get("panes") or []
print(len(panes))
' 2>/dev/null || printf '0'
}

# First pane_id in workspace $1, else empty.
_hl_first_pane() {
  local wid="$1" raw
  raw="$(herdr pane list --workspace "$wid" 2>/dev/null)" || true
  printf '%s' "$raw" | python3 -c '
import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
if s<0: raise SystemExit(0)
try:
    d=json.loads(raw[s:e+1])
except ValueError:
    raise SystemExit(0)
panes=(d.get("result") or {}).get("panes") or d.get("panes") or []
if panes:
    print(panes[0].get("pane_id") or "")
' 2>/dev/null || true
}

_hl_close_label() {
  local mid="$1" lab="$2" wid left
  wid="$(_hl_ws_id "$mid" "$lab")"
  [ -n "$wid" ] || return 0
  if ! herdr workspace close "$wid" >/dev/null 2>&1; then
    note "herdr-layout: could not close $lab ($wid) — close failed"
    return 1
  fi
  # Confirm it is gone; a failed or async close must not look like success.
  # Herdr may finish the close shortly after the call returns, so poll briefly
  # instead of failing the whole --reset on the first look.

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    left="$(_hl_ws_id "$mid" "$lab")"
    [ -n "$left" ] || break
    sleep 0.2
  done
  if [ -n "$left" ]; then
    note "herdr-layout: $lab still present after close ($left)"
    return 1
  fi
  note "herdr-layout: closed $lab"
  return 0
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
  bash dev.sh herdr-layout --reset   close the standard workspaces (Home, legacy "Home (~)",
                                     Editor, Development, Agents), then recreate; aborts if
                                     any of them cannot be closed. Other workspaces are untouched.

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
    # Stack must be up — dc exec fails opaquely otherwise.
    if ! dc ps --status running --services 2>/dev/null | grep -qx "$DC_SERVICE"; then
      die "herdr-layout: $DC_SERVICE is not running — run: bash dev.sh up"
    fi
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
    local lab close_failed=0
    # Only the four standard labels (+ legacy "Home (~)"). Do not close
    # undocumented labels like "~" or "app" — those may be real workspaces.
    for lab in Home "Home (~)" Editor Development Agents; do
      _hl_close_label "$mid" "$lab" || close_failed=1
    done
    if [ "$close_failed" -ne 0 ]; then
      die "herdr-layout: --reset could not close every standard workspace; fix Herdr and retry"
    fi
  fi

  local home_ws editor_ws dev_ws agents_ws line pane tab_id tests_pane n rc

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
    if [ -n "$tests_pane" ]; then
      herdr pane rename "$tests_pane" tests >/dev/null 2>&1 || true
      note "herdr-layout: created Development (server | tests)"
    else
      note "herdr-layout: created Development without tests split (pane split returned no id)"
    fi
  else
    note "herdr-layout: Development already present"
    # Keep mode: a single pane means the tests split is missing; add it.
    # A count of 0 means the list was unreadable — never split on unknown,
    # and 2+ panes already carry the split (whatever they are labelled).
    if [ "$(_hl_pane_count "$dev_ws")" -eq 1 ]; then
      pane="$(_hl_first_pane "$dev_ws")"
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
      # rc 0 = present, 1 = absent, other = unreadable: never duplicate on unknown.
      rc=0; _hl_tab_has_label "$agents_ws" "Agent ${n}" || rc=$?
      if [ "$rc" -ne 1 ]; then
        [ "$rc" -eq 0 ] || note "herdr-layout: could not read tabs; skipping Agent $n"
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

# --------------------------------------------------------------------------
# rebuild from inside a container
#
# A container cannot run Docker, so `rebuild` here is a request to the Mac. The
# grammar is the one used outside: `dbdev <repo> rebuild` acts on <repo> in the
# CURRENT workspace — the one this container belongs to (DAILYBOT_WORKSPACE_ID),
# or `primary` for a primary-stack container. `dbdev rebuild` alone means this
# very container. The Mac validates the request and runs it detached, because
# rebuilding a container ends the session that asked for it.
# --------------------------------------------------------------------------

# Tested in the Core Hub, not in each repository (this file is identical in all of
# them): bash scripts/test_dev_rebuild_request.sh — DAILYBOT_ASSUME_CONTAINER=1 plus
# a fake ssh through DAILYBOT_HOST_SSH.
# DAILYBOT_ASSUME_CONTAINER=1 forces container mode and =0 host mode, so the
# tests of both paths run anywhere, including inside a container.
in_container() {
  case "${DAILYBOT_ASSUME_CONTAINER:-}" in
    1) return 0 ;;
    0) return 1 ;;
  esac
  [ -f /.dockerenv ]
}

# Short alias (api web chatbot discord site cli hub) for a repository name; empty
# when the name is not a Dailybot repository.
repo_alias() {
  case "$1" in
    api|api-services) printf 'api' ;;
    web|web-app) printf 'web' ;;
    chatbot|cf|chatbot-functions) printf 'chatbot' ;;
    discord|discord-gateway) printf 'discord' ;;
    site|www|dailybot.com|dailybot-com) printf 'site' ;;
    cli) printf 'cli' ;;
    hub|core|core-hub|dailybot-core) printf 'hub' ;;
  esac
}

# The repository this container runs: the workspace metadata when present,
# otherwise the git remote name, otherwise the checkout directory name.
self_repo_alias() {
  local cand a
  for cand in \
    "${DAILYBOT_PORT_REPO:-}" \
    "$(git -C "$SELF_DIR" remote get-url origin 2>/dev/null | sed 's#.*/##; s#\.git$##')" \
    "$(basename "$SELF_DIR")"; do
    [ -n "$cand" ] || continue
    a="$(repo_alias "$cand")"
    if [ -n "$a" ]; then printf '%s' "$a"; return 0; fi
  done
  return 1
}

# One request to the Mac. DAILYBOT_HOST_SSH is a test hook; the real command is
# ssh to the `dailybot-mac` alias the host kit publishes for containers.
# The Mac's alias inside this container. The host kit publishes `dailybot-mac`
# through the peers include; a devcontainer-kit container gets the host from
# `dck herdr mesh` as `dck-host` instead (a profile whose host listener is the
# host kit's). DAILYBOT_HOST_ALIAS wins over both.
host_alias() {
  if [ -n "${DAILYBOT_HOST_ALIAS:-}" ]; then printf '%s' "$DAILYBOT_HOST_ALIAS"; return 0; fi
  local a
  for a in dailybot-mac dck-host; do
    # `ssh -G` resolves without connecting; an alias nobody declared keeps its
    # own name as the host name.
    if [ "$(ssh -G "$a" 2>/dev/null | awk '$1 == "hostname" { print $2; exit }')" != "$a" ]; then
      printf '%s' "$a"; return 0
    fi
  done
  printf 'dailybot-mac'
}

host_request() {
  local verb="$1"; shift
  local from="${DAILYBOT_WORKSPACE_ID:-primary}"
  safe_name "$from" || die "invalid DAILYBOT_WORKSPACE_ID '$from'"
  safe_name "$verb" || die "invalid request '$verb'"
  # Every token is shell-quoted (printf %q), so a value can only ever be data on
  # the Mac, never extra commands. Only $HOME is left to expand there.
  local mac_cmd
  mac_cmd="\"\$HOME/.local/share/coding-agent-kit/bin/dailybot-dev\"$(printf ' %q' request "$verb" --from-workspace "$from" "$@")"
  local out rc=0 mac_alias
  mac_alias="$(host_alias)"
  # shellcheck disable=SC2086
  if out="$(${DAILYBOT_HOST_SSH:-ssh -o BatchMode=yes -o ConnectTimeout=10} "$mac_alias" "$mac_cmd" 2>&1)"; then rc=0; else rc=$?; fi
  [ -z "$out" ] || printf '%s\n' "$out"
  # ssh exits 255 when it cannot connect; any other status is the Mac's own
  # answer to the request, which is printed above.
  if [ "$rc" -eq 255 ]; then
    die "could not reach the Mac (alias $mac_alias). Run as the container's remoteUser, and make sure the Mac side is set up: bash scripts/host-kit-menu.sh organize, from the Dailybot hub on the Mac"
  elif [ "$rc" -ne 0 ]; then
    die "the Mac refused the request (exit $rc) — its message is above"
  fi
}

# A name is safe to put on the Mac command line only when it has no shell
# metacharacters and cannot be read as a flag.
safe_name() {
  case "$1" in
    ''|-*|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
  return 0
}

remote_rebuild() {
  local from ws self target args=()
  [ "$ALL" -eq 0 ] || die "--all only works on the Mac. Inside a container name one repository: dbdev <repo> rebuild"
  [ "${#ARGS[@]}" -eq 0 ] || die "unexpected argument '${ARGS[0]}'. Inside a container the form is: dbdev <repo> rebuild (for example: dbdev api rebuild)"
  from="${DAILYBOT_WORKSPACE_ID:-primary}"
  safe_name "$from" || die "invalid DAILYBOT_WORKSPACE_ID '$from'"
  ws="${REQ_WORKSPACE:-$from}"
  safe_name "$ws" || die "invalid workspace name '$ws'"
  # This gate stops mistakes, not abuse: DAILYBOT_WORKSPACE_ID is a claim any
  # process in the container can change. The Mac side (dailybot-dev request) is
  # the one that must validate and authorise; never treat this die as the
  # trust boundary.
  if [ "$ws" != "$from" ] && [ "$ALLOW_OTHER_WS" -ne 1 ]; then
    die "this container belongs to workspace '$from'. Acting on '$ws' needs --allow-other-workspace — only when the human asked for that workspace by name."
  fi
  self="$(self_repo_alias || true)"
  if [ -n "$TARGET_REPO" ]; then
    target="$(repo_alias "$TARGET_REPO")"
    [ -n "$target" ] || die "unknown repository '$TARGET_REPO' (use api, web, chatbot, discord, site, cli, hub)"
  else
    target="$self"
    [ -n "$target" ] || die "cannot tell which repository this container runs; name one: dbdev <repo> rebuild"
  fi
  # The hub runs only on the primary stack: no workspace has a hub satellite,
  # and the Mac refuses one. Say so here instead of sending the request.
  if [ "$target" = hub ] && [ "$ws" != primary ]; then
    die "the Core Hub has no container in workspace '$ws' (only the primary stack runs it). From a workspace, rebuild a product repository instead."
  fi
  args=(--workspace "$ws" --repo "$target")
  [ "$ws" = "$from" ] || args+=(--allow-other-workspace)
  if [ "$SHOW_STATUS" -eq 1 ]; then
    host_request status "${args[@]}"
    return
  fi
  if [ "$target" = "$self" ] && [ "$ws" = "$from" ] && [ "$ASSUME_YES" -ne 1 ]; then
    die "rebuilding $target in '$ws' recreates THIS container and ends your session. Re-run with --yes, or rebuild a sibling (dbdev <other repo> rebuild)."
  fi
  [ "$NO_CACHE" -eq 1 ] && args+=(--no-cache)
  host_request rebuild "${args[@]}"
  note "Follow it with: dbdev $target rebuild --status"
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
                        INSIDE A CONTAINER the form is different — a request to
                        the Mac for a repo of THIS container's workspace
                        (primary when it has none):
                          dbdev <repo> rebuild           e.g. dbdev api rebuild
                          dbdev rebuild --yes            this very container
                          dbdev <repo> rebuild --status  how the last one went
                        There, "rebuild <service>" and --all do not apply.
  satellite <up|down|stop|ps|logs|shell|rebuild> --project P --service S
            [--compose-file F]... [--seed-state | --seed-state-from VOL]
            [--label TEXT]
                        a workspace satellite (<svc>satellite in its own
                        project P), for docker.sh satellite.*. Through dck when
                        the repository has dck.toml (host keys, accounts, git
                        identity, Herdr machine; --seed-state copies the
                        primary's gh/Dailybot login once); plain compose only
                        without dck. On the Mac; never the hub
  ls                  repositories this launcher can address, and their state
  config                resolved configuration; writes nothing
  doctor                environment diagnosis; writes nothing
  ports                 host bindings, or workspace ports and live listeners
                        when run inside the container
  agents                live machines and agents (herdr-peers list over the
                        Mac catalog); same as: dbdev agents
  ask <#> "..."         ask agent # through herdr-peers: one stamped prompt,
                        one authorized reply back to this pane. Also
                        ask <machine>:<pane> "...", ask <machine> <pane> "..."
                        and ask lead "..." (--plan). Stays inside your
                        workspace unless --any-workspace; --from, --scope,
                        --fanout/--reason, --task, --plan pass through
  check -               classify a received [herdr-peers] message (stdin)
  reply <from> <id> "…" answer an ask exactly once (the command check prints)
  wait <id>             block until the reply to your ask arrives here
  notify <addr> "..."   one-way notice, never answered
  cancel <id>           close an open ask (yours, or one you decline)
  lanes · lead …        a lead's view of its lanes; the plan's lead record
  peers <verb> …        any other herdr-peers verb (log, status, --help)
  herdr-layout          create Home · Editor · Development · Agents on this
                        machine. --keep leaves current panes and fills gaps;
                        --reset closes those four (and legacy "Home (~)"), then
                        recreates them; it aborts if one cannot be closed.
                        Bare with a TTY asks whether to reset (default N).
  help                  this text

Flags
  --repo <name>         unambiguous repository target
  --all                 fan the verb out over every addressable repository
  --project <name>      override the compose project name (also DEVSH_PROJECT;
                        otherwise [compose] project in .devcontainer/dck.toml,
                        then COMPOSE_PROJECT_NAME)
  --recreate            with up, recreate containers to apply compose changes
  --no-cache            with rebuild (or build), ignore Docker layer cache and
                        pull base images — full wipe, much slower
  --yes                 inside a container, confirm rebuilding this very
                        container (it ends the session that asked)
  --status              inside a container, show the last rebuild requests
  --workspace <name>    inside a container, target another workspace; needs
                        --allow-other-workspace
  --allow-other-workspace
                        inside a container, permit --workspace <other>; only
                        when the human named that workspace
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
    satellite)
      [ ! -f "$REPO_ROOT/repositories/README.md" ] || die "the Core Hub has no satellite (only the primary stack runs it); name a product repository: bash dev.sh api satellite …"
      cmd_satellite ;;
    config)  cmd_config ;;
    doctor)  cmd_doctor ;;
    ports)   cmd_ports ;;
    agents) cmd_herdr_agents ;;
    ask)    cmd_herdr_ask "${ARGS[@]+"${ARGS[@]}"}" ;;
    reply|check|wait|notify|cancel|lanes|lead|peers)
            cmd_herdr_peers "$VERB" "${ARGS[@]+"${ARGS[@]}"}" ;;
    herdr-layout) cmd_herdr_layout ;;
    *)       die "unknown verb '$VERB' — run: bash dev.sh help" ;;
  esac
}

case "$VERB" in
  help) cmd_help; exit 0 ;;
  ls)   SELF_DIR="$SELF_DIR"; cmd_ls; exit 0 ;;
esac

# Inside a container there is no Docker: rebuild becomes a request to the Mac.
if [ "$VERB" = "rebuild" ] && in_container; then
  remote_rebuild
  exit 0
fi
# These flags only mean something for that in-container request. On the Mac they
# would be silently ignored, and `rebuild --status` would then run a real rebuild.
if [ "$SHOW_STATUS" -eq 1 ] || [ -n "$REQ_WORKSPACE" ] || [ "$ALLOW_OTHER_WS" -eq 1 ] || [ "$ASSUME_YES" -eq 1 ]; then
  die "--status, --workspace, --allow-other-workspace and --yes only apply to 'rebuild' inside a container"
fi

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

# A satellite's --project names the satellite's own compose project; the
# primary project still resolves as for every other verb (the login seed comes
# from its state volume). Satellites run on the Mac, never in the Core Hub.
if [ "$VERB" = "satellite" ]; then
  in_container && die "satellites start on the Mac (dbdev workspace …); inside a container ask for one: dbdev <repo> rebuild --workspace <name>"
  SAT_PROJECT="$PROJECT_OVERRIDE"; PROJECT_OVERRIDE=""
fi

# Resolved into a variable first, and the status checked. A failure inside
# `$(...)` only exits the SUBSHELL: written as run_one "$(resolve_repo_root …)"
# an unknown or ignored target printed its error and then ran the verb against
# an empty root, which falls back to this repository -- so `dev.sh typo down`
# reported the typo and took the hub's containers down anyway, exiting 0.
_resolved_root="$(resolve_repo_root "$TARGET_REPO")" || exit 1
[ -n "$_resolved_root" ] || die "could not resolve a target for '${TARGET_REPO:-.}'"
run_one "$_resolved_root"
