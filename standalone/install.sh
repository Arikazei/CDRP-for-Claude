#!/usr/bin/env bash
# Richtet den Presence-Dienst als systemd-Benutzerdienst ein.
#
# Benutzerdienst, nicht Systemdienst: die Presence braucht die
# angemeldete Sitzung. Ohne sie gibt es weder einen Discord-Socket noch
# eine Barrierefreiheitsbruecke zum Fenster. Ein Systemdienst liefe zwar,
# haette aber nichts zu tun.
#
# Entfernen: ./uninstall.sh
set -euo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKRIPT="$HIER/run_presence.py"
EINHEIT="$HOME/.config/systemd/user/claude-discord-presence.service"

[ -f "$SKRIPT" ] || { echo "run_presence.py fehlt neben diesem Skript." >&2; exit 1; }

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 nicht gefunden." >&2; exit 1; }

if ! "$PY" -c "import pypresence" 2>/dev/null; then
    echo "Hinweis: pypresence fehlt. Installieren mit:"
    echo "    $PY -m pip install --user pypresence"
    echo "Ohne das Paket startet der Dienst, sendet aber nichts."
fi

mkdir -p "$(dirname "$EINHEIT")"
cat > "$EINHEIT" <<EOF
[Unit]
Description=Discord Rich Presence fuer Claude Desktop, Codex und Antigravity
# Nicht an ein Programm gebunden: der Dienst soll auch senden, wenn nur
# Codex oder Antigravity offen sind.
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$PY $SKRIPT
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now claude-discord-presence.service

echo "Eingerichtet: $EINHEIT"
echo
systemctl --user --no-pager status claude-discord-presence.service || true
echo
echo "Protokoll ansehen:  journalctl --user -u claude-discord-presence -f"
echo "Die Extension in Claude Desktop weicht binnen einer Minute zurueck."
