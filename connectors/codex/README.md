# Codex-Connector

Zwei Teile, beide reine Beacon-Produzenten. Sie verbinden sich weder mit
Discord noch miteinander noch mit einer OpenAI-Schnittstelle.

- **Hook** (`codex_beacon.py`): Codex ruft ihn bei sieben Ereignissen auf
  (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
  `PermissionRequest`, `Stop`, `SessionEnd`). Er macht daraus Zustand,
  Taetigkeit, Modell und Dateiart und schreibt `beacons/codex.json`.
- **Waechter** (`watcher.py`): laeuft dauerhaft, prueft alle 15 Sekunden, ob
  die Codex-App offen ist, haelt den Beacon waehrend langer Denkzuege frisch,
  meldet "offen und untaetig", wenn keine Aufgabe laeuft, loescht den Beacon,
  wenn die App zu ist, und liest alle 20 Sekunden Abo und Wochenlimit aus dem
  Einstellungsfenster (nur Windows, nur solange es offen ist).

Ohne Hook zeigt die Presence Codex nur als offen. Ohne Waechter verschwindet
Codex eine Viertelstunde nach der letzten Aufgabe, und Abo und Auslastung
fehlen.

## Installation

Die Hook-Dateien im Repo sind Vorlagen mit Platzhaltern. Sie werden aus der
lokalen Installation erzeugt -- `standalone/install.ps1` und `install.sh` tun
das mit, von Hand geht es so:

```text
python connectors/codex/install_hooks.py
```

Das erzeugt im Datenordner einen **Starter** (`codex-hook.cmd`, unter Linux
`codex-hook.sh`), der Interpreter und `codex_beacon.py` dieser Kopie aufruft,
dazu `codex-hooks.json` und die `hooks.json` des Plugins. Der Starter ist
noetig, weil Codex unter Windows keine Befehlszeile mit Anfuehrungszeichen
startet: ein Interpreterpfad mit Leerzeichen laesst sich nicht direkt
eintragen, ein kurzer Pfad ohne Leerzeichen schon. Liegt der Datenordner
selbst unter einem Pfad mit Leerzeichen, verlangt das Skript `--starter` mit
einem passenden Ort. `--python` waehlt einen anderen Interpreter; ohne Angabe
gilt der, der das Skript ausfuehrt.

Der Starter wird bei jedem Lauf neu geschrieben. Nicht von Hand bearbeiten
und keine Kopie von `codex_beacon.py` anlegen: genau so eine Kopie ist hier
schon einmal still veraltet, und Aenderungen am Connector kamen beim Hook
nie an.

### Als Plugin (empfohlen)

```text
codex plugin marketplace add "<Repo>/connectors/codex/plugin"
codex plugin add codex-discord-presence@personal
```

Dann in der Codex-App `/hooks` oeffnen und alle sieben Hooks als
vertrauenswuerdig bestaetigen. Codex fuehrt nicht verwaltete Hooks erst nach
dieser Bestaetigung aus und speichert dafuer je Hook einen Hash in
`config.toml`. Aendert sich der Starterpfad, aendert sich der Hash, und die
Bestaetigung ist erneut faellig. Bereits laufende Codex-Aufgaben uebernehmen
neue Hooks nicht -- eine neue Aufgabe starten oder die App neu starten.

### Als globale Hook-Datei

Inhalt von `<Datenordner>/codex-hooks.json` nach `~/.codex/hooks.json`
uebernehmen (Windows: `%USERPROFILE%\.codex\hooks.json`). Existiert dort
schon eine Datei, die Eintraege unter `hooks` zusammenfuehren. Projektlokal
gilt dieselbe Datei unter `<Projekt>/.codex/hooks.json`, dann nur in einem
vertrauten Projekt.

Beide Wege gleichzeitig feuern doppelt. Einen waehlen.

## Waechter

Startet `install.ps1` (Autostart-Eintrag `DiscordRP-Codex.vbs`)
beziehungsweise `install.sh` (Dienst `claude-discord-presence-codex`). Von
Hand:

```text
python connectors/codex/watcher.py
```

Fuer Abo und Auslastung braucht er unter Windows das Paket `uiautomation`
(steht in `requirements.txt`). Fehlt es, laeuft er ohne diese Angaben.

## Kontrolle

```text
python tools/probe_codex_hook.py             # synthetische Ereignisse, Wegwerfordner
python tools/validate_beacon.py codex        # den echten Beacon gegen den Vertrag pruefen
python tools/validate_beacon.py codex --watch 300
```

Der Watch-Test muss waehrend einer echten Codex-Arbeit mit Werkzeugaufrufen
laufen. `SessionEnd` kann laut Codex-Lebenszyklus zeitversetzt eintreffen;
`Stop` setzt den Beacon schon am Ende des Zugs auf `waiting/idle`.

## Was gelesen wird, was nicht

Aus der Hook-Nutzlast: `hook_event_name`, `tool_name`, `model` (nur gegen
eine feste Tabelle bekannter Modelle), aus `tool_input` nur die Endung
expliziter Pfadfelder und bei `apply_patch` die Endung aus der Kopfzeile.
`prompt`, `cwd`, `session_id`, `transcript_path` und Befehle liegen in
derselben Nutzlast und werden verworfen; ein Befehl wird nur daraufhin
angesehen, ob er ein Testlauf ist.

Aus dem Fenster der App: der Abschnitt "Nutzung und Abrechnung" -- Tarifname
(Positivliste von Zeichen, hoechstens 32) und das Wochenlimit, und das nur,
wenn "uebrig", "left" oder "remaining" dransteht. Danach altern die Werte:
Auslastung nach 3 Stunden, Abo nach 30 Tagen.
