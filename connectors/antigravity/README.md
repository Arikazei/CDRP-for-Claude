# Antigravity Discord Presence Beacon Connector

Produzent fuer Google Antigravity gemaess `SPEC-beacon-v1.md`.

Liest den aktuellen Arbeitszustand laufender Antigravity-Sitzungen aus dem lokalen Transkript (`~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript.jsonl`) und schreibt atomar den Beacon fuer den zentralen Discord-RP-Master.

## Voraussetzungen

- Python 3.8+ (nur Standardbibliothek, keine externen Packages noetig)
- Google Antigravity installiert und aktiv

## Installation & Start

### Manuell / Vordergrund:

```powershell
python connectors/antigravity/watcher.py
```

### Im Hintergrund (PowerShell / Autostart):

```powershell
Start-Process -FilePath "python" -ArgumentList "connectors/antigravity/watcher.py" -WindowStyle Hidden
```

### Selbsttest / Validierung:

```powershell
# Einzelpruefung
python tools/validate_beacon.py antigravity

# Langzeitpruefung (Atomizitaet & Herzschlag)
python tools/validate_beacon.py antigravity --watch 300

# Unit-Tests
python -m unittest connectors/antigravity/test_watcher.py
```

## Funktionsweise & Datenschutz

1. **Reine Positivliste:** Liest aus dem Transkript ausschliesslich `type`, `status`, `created_at` und Werkzeugnamen. `content`, `thinking` (Reasoning), Prompts und Antworten werden **vollstaendig ignoriert** und gelangen niemals in den Speicher oder den Beacon.
2. **Dateiendungs-Mapping (`file_kind`):** Pfade werden nur kurz gelesen, um die Dateiendung auf eine der 21 festen Marken abzubilden (`.py` -> `python`, etc.). Der Pfad wird unmittelbar danach verworfen.
3. **Atomares Schreiben:** Payloads werden in `.tmp`-Dateien geschrieben und via `os.replace` atomar platziert.
4. **Kein Netzzugriff:** Der Connector spricht weder mit Discord noch mit externen APIs.
