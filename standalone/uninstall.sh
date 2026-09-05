#!/usr/bin/env bash
# Entfernt die systemd-Benutzerdienste von Presence und Waechtern.
#
# Danach sendet wieder die Extension in Claude Desktop; sie versucht die
# Uebernahme im Minutentakt und merkt von selbst, dass der Dienst weg
# ist.
set -euo pipefail

EINHEITEN="$HOME/.config/systemd/user"

for name in claude-discord-presence claude-discord-presence-codex \
            claude-discord-presence-antigravity; do
    systemctl --user disable --now "$name.service" 2>/dev/null || true
    rm -f "$EINHEITEN/$name.service"
done
systemctl --user daemon-reload

echo "Dienste entfernt. Die Extension uebernimmt binnen einer Minute wieder."
echo "Die Codex-Hooks bleiben registriert (~/.codex/hooks.json bzw. Plugin)."
