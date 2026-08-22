#!/usr/bin/env bash
# Entfernt den systemd-Benutzerdienst.
#
# Danach sendet wieder die Extension in Claude Desktop; sie versucht die
# Uebernahme im Minutentakt und merkt von selbst, dass der Dienst weg
# ist.
set -euo pipefail

EINHEIT="$HOME/.config/systemd/user/claude-discord-presence.service"

systemctl --user disable --now claude-discord-presence.service 2>/dev/null || true
rm -f "$EINHEIT"
systemctl --user daemon-reload

echo "Dienst entfernt. Die Extension uebernimmt binnen einer Minute wieder."
