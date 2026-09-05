# Umzugsbericht: Connectoren ins Sender-Repo

Stand: 5. September 2026. Alles ist lokal committet (aab6bbc..a8a3682, elf
Commits), nichts gepusht, kein Tag, kein Release.

## 1. Was verschoben wurde

Aus dem Arbeitsordner DiscordRP (Commit dort: 4a021bb) nach claude-rpc:

| Von | Nach |
|---|---|
| `connectors/codex/` (Hook, Waechter, Fensterleser, Plugin, README, Test) | `connectors/codex/` |
| `connectors/antigravity/` (Waechter, Fensterleser, README, Test) | `connectors/antigravity/` |
| `connectors/gemeinsam/uia.py` | `connectors/gemeinsam/uia.py` |
| `SPEC-beacon-v1.md` | `docs/SPEC-beacon-v1.md` (nur der Pfad des Senders neutralisiert) |
| `tools/validate_beacon.py`, `tools/probe_codex_hook.py` | `tools/` |

Nicht mitgenommen, bleiben als Werkstatt in DiscordRP: BEFUND-*, REVIEW-*,
ARBEITSANWEISUNG-*, PLAN.md, SACKGASSE-*, discord_rpc_machbarkeit_antigravity.md,
alle `__pycache__`, die beiden `.gitkeep`. `BEFUND-codex-plugin.md` lag
innerhalb von `connectors/codex/plugin/` und wurde in DiscordRP ins
Wurzelverzeichnis gehoben. Die README dort erklaert jetzt den Umzug.

Die Kopie geschah ohne Historie. Die Rechnerpfade aus den beiden Hook-Dateien
sind vor dem ersten Commit durch Platzhalter ersetzt worden, sie stehen also
nirgends in der Historie von claude-rpc.

## 2. Welche Pfade konfigurierbar wurden

| Stelle | Vorher | Jetzt |
|---|---|---|
| `connectors/codex/hooks.json` | siebenmal Codex-Runtime-Python und DiscordRP-Pfad | Vorlage mit `{{PYTHON}}`, `{{BEACON}}`, `{{STARTER}}` |
| `connectors/codex/plugin/plugins/codex-discord-presence/hooks.json` | siebenmal der Starterpfad | `hooks.json.in` mit `{{STARTER}}`; die erzeugte `hooks.json` ist untracked (`.gitignore`) |
| Starter `beacon.cmd` | von Hand gepflegt, mit Debug-Zeile nach `ran.log` | wird von `connectors/codex/install_hooks.py` erzeugt; ohne Debug-Zeile; Ort waehlbar (`--starter`), Vorgabe `<Datenordner>/codex-hook.cmd` bzw. `.sh` |
| Watcher-Datenordner | drei eigene Fassungen derselben Regel in Codex-Hook, Antigravity-Waechter und Validator | `beacons.produzenten_datenordner()` (CLAUDE_RPC_DATA_DIR, sonst Profilpfad); die Waechter finden `beacons.py` relativ zum Repo |
| `datenordner_kandidaten` (Leseseite mit den umgeleiteten Ordnern) | – | unveraendert |
| `standalone/install.ps1` | nur der Dienst | Dienst plus beide Waechter (Autostart `DiscordRP-Codex.vbs`, `DiscordRP-Antigravity.vbs`, dieselbe Laufzeit), erzeugt die Codex-Hook-Dateien, Parameter `-CodexStarter`; Ausschluss von `WindowsApps` bleibt |
| `standalone/install.sh` | nur der Dienst | drei systemd-Benutzerdienste plus Codex-Hook-Dateien |
| `standalone/uninstall.*` | nur der Dienst | nimmt alle drei zurueck |
| `standalone/run_presence.py` | ueberschrieb `CLAUDE_RPC_DATA_DIR` und `CLAUDE_RPC_CONFIG` | respektiert beide, wenn gesetzt |
| `setup_venv.bat` | fester uv-Pfad eines Rechners | sucht Aufrufparameter, py-Launcher, PATH, uv; ueberspringt die Store-Fassung |

Auf diesem Rechner wurde der Starter mit `--starter` auf den bisherigen Ort
erzeugt, damit die sieben Hook-Definitionen byteweise dem Stand im
Codex-Cache gleichen und die gespeicherten Vertrauens-Hashes weiter gelten.
Geprueft: die erzeugte `hooks.json` ist mit
`~/.codex/plugins/cache/personal/codex-discord-presence/0.1.1/hooks.json`
identisch. Der Selbsttest des Starters braucht 0,2 s (Hook-Timeout 2 s).

Ausserhalb des Repos geaendert: `~/.codex/config.toml` zeigt fuer den
Marktplatz `personal` auf `claude-rpc/connectors/codex/plugin` statt auf
DiscordRP (Sicherung: `config.toml.vor-umzug.bak`). `codex plugin list` meldet
das Plugin danach als `installed, enabled`, Version 0.1.1, am neuen Ort.

### Weitere Aenderungen, die beim Umzug anfielen

- `tools/validate_beacon.py` kannte die Zusatzfelder `plan` und `usage` aus
  Nachtrag 1.1 nicht und meldete bei jedem echten Codex-Beacon „unbekannte
  Schluessel". Jetzt prueft er sie mit den Regeln des Senders.
- `tools/probe_codex_hook.py` schrieb in den echten Datenordner und hat dabei
  den Beacon des laufenden Codex ueberschrieben (heute einmal passiert, beim
  Baseline-Lauf). Jetzt Wegwerfordner.
- `tools/probe_rahmen.py` rief `beacons.arbeiter` auf, das es nicht mehr gibt;
  folgt jetzt `beacons.aktive`.
- Synthetische Testpfade auf Laufwerk P in `test_watcher.py` und
  `probe_codex_hook.py` liegen jetzt auf Laufwerk X, damit der Grep unter
  Punkt 5.2 sauber bleibt.

## 3. Personendaten

`UEBERGABE-NEUER-CHAT.md` und `RAMLEAK_REPORT_20260815.md` sind mit
`git rm --cached` aus dem Index genommen, liegen lokal weiter und stehen in
`.gitignore` (Commit e6bfff7). `Arikazei` bleibt in LICENSE, `mcpb/manifest.json`,
der Plugin-`plugin.json` und in der Klon-URL im README.

**Betroffene Historie:** beide Dateien kamen mit 5f96518 („Beacon-Pool: Codex und
Antigravity teilen sich die Presence") herein und liegen in allen 15 Commits
von 5f96518 bis aab6bbc, also im gesamten gepushten Stand seit diesem Commit.
`git log --oneline 5f96518^..aab6bbc` listet sie.

**Offene Frage:** Soll die Historie umgeschrieben werden (etwa mit
`git filter-repo --invert-paths --path UEBERGABE-NEUER-CHAT.md --path RAMLEAK_REPORT_20260815.md`
und anschliessendem Force-Push)? Das aendert alle 15 Commit-Hashes seit
5f96518; Klone anderer muessten neu aufgesetzt werden, und GitHub behaelt die
alten Objekte, bis der Support sie entfernt. Ich habe nichts umgeschrieben und
nichts gepusht.

## 4. Testergebnisse

| Lauf | Ergebnis |
|---|---|
| `tools/test_beacons.py` | 54 Tests, OK |
| `tools/test_stufe.py` | 15 Tests, OK |
| `connectors/antigravity/test_watcher.py` | 5 Tests, OK |
| `connectors/codex/test_codex_beacon.py` | 2 Tests, OK |
| `tools/probe_codex_hook.py` | 6 Faelle vertragskonform, kein Leck |

69 ist die Summe der beiden Sender-Testdateien, wie bisher. Dazu kommen die
7 Tests der Connectoren, die vorher in DiscordRP liefen: 76 gesamt.
Dieselben Laeufe im frischen Klon: identisch gruen.

## 5. Nachpruefung

### 5.1 Tests
Siehe oben, alles gruen.

### 5.2 Grep
`git grep -n -I -E 'marco|Marco|arikazei|C:\\Users|P:\\|codexrp|\.venv'`
trifft nur noch `.venv`: in `.gitignore`, README (Entwicklerbefehle),
`build_mcpb.ps1`, `setup_venv.bat`, `standalone/install.ps1` und
`start_claude_rpc.vbs`. Das ist der Name der virtuellen Umgebung im
Projektordner, kein Rechnerpfad. `Arikazei` (Grossschreibung, vom Muster nicht
erfasst) steht in LICENSE, `mcpb/manifest.json`, der Plugin-`plugin.json` und der
Klon-URL im README, wie beabsichtigt. Keine Treffer fuer Vornamen,
Rechnername, Laufwerkspfade oder den Starterordner.

### 5.3 Frischer Klon
Klon nach `%TEMP%\...\scratchpad\klon`, dort `setup_venv.bat` ohne Parameter.
Erster Befund: die Store-Pruefung in der Batch-Datei griff nicht, weil in
dieser Shell das GNU-`find` vor dem Windows-`find` liegt, und nahm das
Store-Python; behoben (ae8f446), zweiter Lauf fand das uv-Python, legte
`.venv` an, installierte `pypresence`, `uiautomation`, `jeepney` und kopierte
`config.example.json` nach `config.json`. `_check_env.py`: „OK: Pfade sichtbar."
Alle Tests im Klon gruen. `install_hooks.py` im Klon mit abgetrenntem
Datenordner: Starter, Hook-Datei und Plugin-`hooks.json` erzeugt, Selbsttest ok.
Waechter aus dem Klon mit abgetrenntem Datenordner: Beacons fuer Codex und
Antigravity erschienen dort binnen einer Minute. Dienst aus dem Klon mit
`CLAUDE_RPC_CONFIG` auf die Kopie von `config.example.json`: „claude_rpc
gestartet", „Mit Discord verbunden (Rohr 0)", `state.json` mit Claude-Karte.
Die Vorlage reicht.

Das `install.ps1` des Klons habe ich nicht laufen lassen, weil es die
Autostart-Eintraege auf den Wegwerfordner umgebogen haette; dasselbe Skript
lief stattdessen im echten Repo (5.4).

### 5.4 Neustart des laufenden Systems
`standalone/install.ps1 -CodexStarter <bisheriger Ort>` erzeugte die drei
Autostart-Dateien (Dienst, Codex-Waechter, Antigravity-Waechter, alle mit dem
venv-`pythonw.exe`), beendete die alten Instanzen mit den DiscordRP-Pfaden und
startete neu. `neustart.ps1` danach: beendet sechs Prozesse, startet drei
Verknuepfungen, listet sechs laufende Prozesse (je Programm Weiche plus
Interpreter).

Ergebnis, gelesen ausserhalb des App-Containers (siehe Abschnitt 6):

- genau ein Sender: `sender.standalone.json` frisch (PID des neuen Dienstes,
  Alter wenige Sekunden); die Extension wartet („Es sendet bereits ein
  standalone-Prozess (PID 42540) - dieser Prozess wartet.")
- beide Waechter melden: `codex.json` idle, GPT-5.6 Sol, Plan „Plus-Tarif";
  `antigravity.json` waiting/idle, „Gemini 3.8 Flash High"
- `claude.json` frisch vom Dienst
- `state.json`: „Google Antigravity · Abonnement: Google AI Pro · using code
  with Fable 5.1 · hoch · 5h 4% · Woche 18% · Fable 30% (vor 38 min)". Der
  Sender schreibt diese Datei nur, wenn Claude aktiv ist; bei inaktivem
  Claude sendet er die fremden Karten direkt an Discord, ohne
  `state.json` zu aktualisieren. Das war schon vor dem Umzug so.

### 5.5 Live-Probe
Antigravity war offen. Eine kurze Codex-Aufgabe lief ueber `codex exec` ausserhalb
des Containers; die CLI meldete „hook: Stop Completed", die Hooks feuern also
ueber das Plugin am neuen Ort. Der Beacon durchlief idle → waiting/idle →
working/thinking → working/running_command (mehrfach) → idle.

Rotation, nachgerechnet mit `tools/probe_rahmen.py` aus den echten Beacons,
alle sechs Sekunden waehrend der Aufgabe:

1. niemand arbeitet: volle Runde, sechs Karten – Claude (Sitzung, Auslastung,
   Abo), Antigravity („using Antigravity with Gemini 3.8 Flash High"), Codex
   („using Codex with GPT-5.6 Sol", „Abonnement: Plus-Tarif")
2. Codex arbeitet: nur Codex („OpenAI Codex · thinking")
3. waehrenddessen begann Antigravity zu arbeiten (du warst offenbar gerade
   dort taetig): nur Antigravity („Google Antigravity · searching the web")

**Nicht durchgefuehrt:** das Schliessen der beiden Programme. Du hast in
Antigravity gearbeitet, und die Codex-App ist deine laufende Sitzung; beide
zu beenden haette deine Arbeit unterbrochen. Das Verschwinden beim Schliessen
haengt an `beacon_entfernen()` in beiden Waechtern, das unveraendert
uebernommen wurde; live belegt ist es heute nicht.

### 5.6 Rueckfall
Dienst beendet (Waechter und Extension blieben): nach rund 40 Sekunden
„claude_rpc gestartet" und „Mit Discord verbunden" im Protokoll der Extension,
`sender.extension.json` frisch. Dienst wieder gestartet: Extension-Protokoll
„Ein standalone-Prozess (PID 42540) uebernimmt - dieser Prozess hoert auf zu
senden.", danach „Es sendet bereits ein standalone-Prozess ... wartet." An
dieser Stelle im Code steht kein `presence.clear()`; die Uebergabe war ohne
Leeren. Dazwischen lag ein Umweg, siehe Abschnitt 6.

## 6. Befund, der nicht im Auftrag stand: App-Container

Diese Claude-Code-Sitzung laeuft als Kind der Store-Fassung von Claude Desktop.
Jeder Prozess, den ich daraus starte, erbt den App-Container: alles unter
`AppData\Local` wird nach `Packages\Claude_*\LocalCache\Local` umgeleitet, und
beim Lesen ueberdecken die Kopien dort die echten Dateien.

Drei Folgen, alle heute gemessen:

1. Mein Vorbefund „drei Prozesse seit dem 2. September haengend" war falsch.
   Sie schrieben gesund in den echten Ordner; ich sah nur alte Kopien. Ich
   habe den gesunden Dienst deshalb einmal unnoetig beendet; er lief nach dem
   Neustart wieder.
2. Dienst und Waechter, die `neustart.ps1` aus so einer Sitzung startet,
   schreiben in den Paketordner. Der Sender liest beide Orte, das faellt ihm
   nicht auf – aber die Extension liest die veraltete Kopie von
   `sender.standalone.json` und weicht nie. Genau das ist beim Rueckfalltest
   passiert; erst nach dem Loeschen der Schattenkopien (von ausserhalb des
   Containers) hat sie uebergeben. Solche Kopien lagen dort schon vor heute,
   vom 1. September.
3. Das Store-Python im PATH hat noch einen eigenen Umleitungsordner; damit
   gelesen, sieht man Staende vom 21. August.

Ab dem Neustart ueber eine geplante Aufgabe laufen Dienst und Waechter
ausserhalb des Containers, so wie nach einer Anmeldung. Die Schattenkopien
`sender.standalone.json`, `codex.json`, `codex.state.json`, `antigravity.json`,
`codex.window.json` im Paketordner sind entfernt. Der Fallstrick steht jetzt in
ARCHITEKTUR.md. Empfehlung: `neustart.ps1` aus einem gewoehnlichen Terminal
starten, nicht aus Claude Code in Claude Desktop.

## 7. Nicht geprueft

- Linux: `install.sh`, `uninstall.sh` und der Linux-Zweig von
  `install_hooks.py` nur auf Syntax geprueft (`bash -n`), nicht ausgefuehrt.
- Die Codex-Desktop-App mit den Hooks am neuen Ort: die Live-Probe lief ueber
  die CLI, die dieselben Plugin-Hooks aus demselben Cache laedt. Ein Blick in
  `/hooks` in der App steht noch aus; erwartet werden sieben vertraute Hooks
  ohne neue Rueckfrage.
- Die Discord-Anzeige selbst. Belegt sind „Mit Discord verbunden" und die
  Kartenrechnung, nicht das Bild im Profil.
- Schliessen von Codex und Antigravity (siehe 5.5).
- `build_mcpb.ps1` nicht ausgefuehrt; die Erweiterung ist unveraendert.

## 8. Lokale Nebenwirkungen auf diesem Rechner

- `~/.codex/config.toml`: Marktplatzpfad umgestellt, Sicherung daneben.
- Starter `beacon.cmd` am bisherigen Ort: aus dem Repo neu erzeugt, ohne
  Debug-Zeile. `ran.log` (51 KB) und `codexcheck.py` liegen unveraendert dort.
- Autostart: drei `.vbs` neu erzeugt, zeigen auf `claude-rpc`.
- Extension einmal beendet; Claude Desktop hat sie ueber einen Werkzeugaufruf
  neu gestartet (PID 75020).
- Paketordner von Claude Desktop: fuenf Schattenkopien entfernt.
- Scratchpad: Klon und Testordner koennen weg.
