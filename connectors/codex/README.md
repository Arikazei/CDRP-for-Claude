# Codex-Connector installieren

Der Connector ist nur ein Beacon-Produzent. Er verbindet sich weder mit
Discord noch mit einem anderen Connector.

## Windows auf diesem Rechner

1. `connectors/codex/hooks.json` nach `%USERPROFILE%\.codex\hooks.json`
   kopieren. Existiert dort bereits eine Hook-Datei, die Eintraege unter
   `hooks` zusammenfuehren statt die Datei zu ersetzen.
2. In `commandWindows` bei Bedarf Python- und Projektpfad anpassen. Die
   mitgelieferte Datei verweist auf den hier vorhandenen Codex-Python-Runtime
   und auf diesen Projektordner.
3. Codex neu starten und die neuen Hooks mit `/hooks` pruefen und vertrauen.
   Fuer automatisierte, bereits gepruefte Tests gibt es alternativ
   `--dangerously-bypass-hook-trust`; das ist nicht die normale Installation.

Projektlokal kann dieselbe Datei unter `<repo>/.codex/hooks.json` liegen. Sie
gilt dann nur fuer dieses Repository und wird nur in einem vertrauten Projekt
geladen. Eine globale Datei unter `%USERPROFILE%\.codex\hooks.json` gilt fuer
alle Codex-Projekte.

## Linux

Den Platzhalter `/path/to/DiscordRP` in jedem `command` ersetzen und die Datei
nach `~/.codex/hooks.json` kopieren. Der Connector nutzt zuerst
`CLAUDE_RPC_DATA_DIR`, danach `$XDG_DATA_HOME/ClaudeDiscordPresence` oder
`~/.local/share/ClaudeDiscordPresence`.

## Kontrolle

Im Projektstamm:

```text
python tools/validate_beacon.py codex
python tools/validate_beacon.py codex --watch 300
```

Der Watch-Test muss waehrend einer echten Codex-Arbeit mit Tool-Aufrufen
laufen. `SessionEnd` kann laut Codex-Lebenszyklus zeitversetzt eintreffen;
`Stop` setzt die Presence schon am Turn-Ende auf `waiting/idle`.
