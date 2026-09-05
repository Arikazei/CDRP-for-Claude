#!/usr/bin/env bash
# Richtet den Presence-Dienst und die beiden Connector-Waechter als
# systemd-Benutzerdienste ein und erzeugt die Codex-Hook-Dateien.
#
# Benutzerdienst, nicht Systemdienst: die Presence braucht die
# angemeldete Sitzung. Ohne sie gibt es weder einen Discord-Socket noch
# eine Barrierefreiheitsbruecke zum Fenster. Ein Systemdienst liefe zwar,
# haette aber nichts zu tun.
#
# Entfernen: ./uninstall.sh
set -euo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WURZEL="$(dirname "$HIER")"
EINHEITEN="$HOME/.config/systemd/user"

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 nicht gefunden." >&2; exit 1; }

if ! "$PY" -c "import pypresence" 2>/dev/null; then
    echo "Hinweis: pypresence fehlt. Installieren mit:"
    echo "    $PY -m pip install --user pypresence"
    echo "Ohne das Paket startet der Dienst, sendet aber nichts."
fi

for skript in "$HIER/run_presence.py" \
              "$WURZEL/connectors/codex/watcher.py" \
              "$WURZEL/connectors/antigravity/watcher.py"; do
    [ -f "$skript" ] || { echo "Fehlt: $skript" >&2; exit 1; }
done

mkdir -p "$EINHEITEN"

# Drei Dienste nach demselben Muster. Die Namen sind fest -- uninstall.sh
# kennt sie. Nicht an ein Programm gebunden: der Dienst soll auch senden,
# wenn nur Codex oder Antigravity offen sind, und die Waechter pruefen
# selbst, ob ihr Programm laeuft.
einheit() {
    cat > "$EINHEITEN/$1.service" <<EOF
[Unit]
Description=$2
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$PY "$3"
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
EOF
    echo "Eingerichtet: $EINHEITEN/$1.service"
}
einheit claude-discord-presence \
    "Discord Rich Presence fuer Claude Desktop, Codex und Antigravity" \
    "$HIER/run_presence.py"
einheit claude-discord-presence-codex \
    "Codex-Waechter der Discord-Presence" \
    "$WURZEL/connectors/codex/watcher.py"
einheit claude-discord-presence-antigravity \
    "Antigravity-Waechter der Discord-Presence" \
    "$WURZEL/connectors/antigravity/watcher.py"

# Codex-Hooks: Starter und Hook-Dateien aus dieser Installation erzeugen.
echo
"$PY" "$WURZEL/connectors/codex/install_hooks.py" || \
    echo "Hinweis: Codex-Hook-Dateien nicht erzeugt (siehe oben)."
echo

systemctl --user daemon-reload
systemctl --user enable --now claude-discord-presence.service \
    claude-discord-presence-codex.service \
    claude-discord-presence-antigravity.service

echo
systemctl --user --no-pager status claude-discord-presence.service || true
echo
echo "Protokoll ansehen:  journalctl --user -u claude-discord-presence -f"
echo "Die Extension in Claude Desktop weicht binnen einer Minute zurueck."
