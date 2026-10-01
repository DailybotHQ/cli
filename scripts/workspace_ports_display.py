#!/usr/bin/env python3
"""Render workspace service ports and the URL selected by the current focus."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def listeners() -> set[int]:
    ports: set[int] = set()
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(path).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            try:
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
            except (IndexError, ValueError):
                continue
    return ports


DEFAULT_RECORDS = {
    "web-app": (("web", "8090", "28090", "8090"), ("storybook", "6006", "26006", "6006")),
    "api-services": (("api", "8000", "28000", "8000"), ("flower", "5555", "25555", "5556")),
    "chatbot-functions": (("chatbot", "3000", "28300", "3000"),),
    "dailybot.com": (("site", "4700", "28470", "4700"),),
    "discord-gateway": (("discord", "3000", "28710", "7100"),),
}


# Main compose service of each repository's devcontainer (what dev.sh resolves as
# DC_SERVICE), including the stable satellite variants.
SERVICE_REPOS = {
    "djangovscode": "api-services",
    "djangovscodesatellite": "api-services",
    "vuevscode": "web-app",
    "vuevscodesatellite": "web-app",
    "functions_vscode": "chatbot-functions",
    "functions_vscodesatellite": "chatbot-functions",
    "dailybotcomvscode": "dailybot.com",
    "dailybotcomvscodesatellite": "dailybot.com",
    "discordgateway": "discord-gateway",
    "discordgatewaysatellite": "discord-gateway",
}


def infer_repo(hint: str) -> str:
    if hint in DEFAULT_RECORDS:
        return hint
    if hint in SERVICE_REPOS:
        return SERVICE_REPOS[hint]
    if hint.endswith("/code/js"):
        return "web-app"
    if hint.endswith("/home/node/app"):
        return "chatbot-functions"
    # A bare "/app" is ambiguous (api-services, dailybot.com and discord-gateway all use
    # it), so only the explicit repository folder or a known service name is trusted.
    if hint.endswith("/api-services"):
        return "api-services"
    return ""


def render_container(raw: str, workspace_id: str, state_root: str, hint: str) -> int:
    focus_id = read_json(Path(state_root) / "_focus.json").get("workspace_id") or "primary"
    focus_id = str(focus_id)
    current_id = workspace_id or "primary"
    focused = current_id == focus_id
    live = listeners()
    records: list[tuple[str, str, str, str, str]] = []
    for item in filter(None, raw.split(",")):
        parts = [part.strip() for part in item.split(":")]
        if len(parts) != 4:
            continue
        service, internal, direct, focus = parts
        listening = "yes" if to_int(internal, -1) in live else "no"
        records.append((service, internal, direct, focus, listening))

    if not records:
        records = [
            (service, internal, direct, focus,
             "yes" if to_int(internal, -1) in live else "no")
            for service, internal, direct, focus in DEFAULT_RECORDS.get(infer_repo(hint), ())
        ]

    if records:
        print("%-14s %-10s %-12s %-10s %s" %
              ("SERVICE", "INTERNAL", "HOST DIRECT", "FOCUS", "LISTENING"))
        for row in records:
            print("%-14s %-10s %-12s %-10s %s" % row)
        _render_urls(records, focus_id, focused)
    else:
        print("No workspace port metadata is attached to this container.")
    unmapped = sorted(port for port in live if not any(str(port) == row[1] for row in records))
    if unmapped:
        print("Live internal listeners: " + ", ".join(map(str, unmapped)))
    return 0


def render_workspace(state_path: str, repo: str) -> int:
    path = Path(state_path)
    data = read_json(path)
    workspace = str(data.get("id") or path.parent.name)
    focus_id = str(read_json(path.parent.parent / "_focus.json").get("workspace_id") or "primary")
    focused = workspace == focus_id
    print("workspace       %s%s" % (workspace, " (focus)" if focused else ""))
    print("%-14s %-10s %-12s %-10s %s" %
          ("SERVICE", "INTERNAL", "HOST DIRECT", "FOCUS", "STATE"))
    rows = []
    for name, service in sorted((data.get("services") or {}).items()):
        if not isinstance(service, dict) or service.get("repo") != repo:
            continue
        direct = to_int(service.get("external_port"))
        with socket.socket() as sock:
            sock.settimeout(0.2)
            state = "open" if direct and sock.connect_ex(("127.0.0.1", direct)) == 0 else "closed"
        rows.append((name, str(service.get("internal_port", "-")), str(direct or "-"),
                     str(service.get("focus_port", "-")), state, direct,
                     service.get("focus_port")))
        print("%-14s %-10s %-12s %-10s %s" % rows[-1][:5])
    if not rows:
        print("No services recorded for repository '%s' in this workspace." % repo)
    _render_urls([(row[0], row[1], row[2], row[3], row[4]) for row in rows], focus_id, focused)
    return 0


def _render_urls(records, focus_id: str, focused: bool) -> None:
    print("Focus          %s (%s)" % (focus_id, "focused" if focused else "direct"))
    print("Access URLs (focus-aware):")
    for service, _internal, direct, focus, _state in records:
        port = focus if focused else direct
        if port and port != "-":
            print(f"{service}: http://localhost:{port} ({'focus' if focused else 'direct'})")


USAGE = (
    "usage: workspace_ports_display.py container <ports> <workspace_id> <state_root> <repo_hint>\n"
    "       workspace_ports_display.py workspace <workspace.json> <repo>"
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) >= 2 and argv[1] == "container" and len(argv) == 6:
        return render_container(argv[2], argv[3], argv[4], argv[5])
    if len(argv) >= 2 and argv[1] == "workspace" and len(argv) == 4:
        return render_workspace(argv[2], argv[3])
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
