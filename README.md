# Discord Presence für Claude Desktop, Codex und Antigravity

Eine Discord-Aktivität für drei Coding-Agenten. Zeigt, womit du gerade
arbeitest – Claude Desktop, OpenAI Codex oder Google Antigravity – mit Modell,
Tätigkeit, Auslastung, Abonnement und Timer. Arbeiten mehrere gleichzeitig,
wechselt die Anzeige alle 20 Sekunden zwischen ihnen. Wer nur offen ist und
wartet, bleibt draußen.

Inoffizielles Projekt, weder von Anthropic noch von OpenAI, Google oder
Discord. Windows und Linux.

## Nur Claude Desktop?

Diese Fassung führt Claude Desktop, OpenAI Codex und Google
Antigravity in einer Aktivität zusammen. Wer allein mit Claude Desktop
arbeitet und nichts weiter einrichten möchte, nimmt
[v1.4.4](https://github.com/Arikazei/CDRP-for-Claude/releases/tag/v1.4.4):
die letzte Fassung vor dem Beacon-Pool, eine reine
Claude-Desktop-Erweiterung, Installation durch Doppelklick auf die
`.mcpb`-Datei. Sie wird nicht mehr weiterentwickelt, läuft aber
unverändert weiter.

Ab Fassung 1.5.0 kommen die beiden anderen Agenten dazu. Seither sendet
ein eigenständiger Dienst an Discord statt der Erweiterung, und die
Connectoren für Codex und Antigravity liegen in `connectors/` im
selben Klon.

## Was in Discord steht

Discord zeigt zwei Zeilen. Die **erste** sagt ohne Verzögerung, was gerade
passiert: „Claude denkt nach", „OpenAI Codex · editing a Python file",
„Google Antigravity · running tests". Die **zweite** rotiert durch das, was
sich nur langsam ändert: Modell, Auslastung, Abonnement. Beide Zeilen stammen
immer vom selben Agenten – die Tätigkeit des einen steht nie über dem Modell
des anderen.

Was **nie** dort steht: Chatinhalte, Chattitel, Dateinamen, Pfade, Befehle,
Suchanfragen. Die Art der bearbeiteten Datei („a Python file") kommt aus einer
geschlossenen Liste von 21 Marken, in der sich ein Name gar nicht ausdrücken
lässt. Dafür gibt es keinen Schalter, weil es keinen braucht: was nicht
erhoben wird, kann nicht versehentlich im Profil landen.

## Wie es zusammenspielt

Genau **ein** Prozess sendet an Discord, der Sender. Codex und Antigravity
melden ihm ihren Zustand über kleine JSON-Dateien im Datenordner, die
Beacons; das Format steht in [docs/SPEC-beacon-v1.md](docs/SPEC-beacon-v1.md).
Der Sender läuft als eigenständiger Dienst (`standalone/`) oder als
Erweiterung in Claude Desktop (`mcpb/`). Laufen beide, hat der Dienst
Vorrang, und die Erweiterung weicht binnen einer Minute – fällt der Dienst
aus, übernimmt sie wieder. Wie das funktioniert, steht in
[ARCHITEKTUR.md](ARCHITEKTUR.md).

| Teil | Woher die Werte kommen | Was ohne ihn fehlt |
|---|---|---|
| **Sender** (`claude_rpc.py`) | Claude-Fenster über die Barrierefreiheitsschnittstelle, Sitzungs- und Nutzungsdateien der Claude-App, Werkzeugverlauf von Desktop Commander, Beacons der anderen | alles – ohne Sender sendet niemand |
| **Codex-Hooks** (`connectors/codex/codex_beacon.py`) | Lebenszyklus-Ereignisse von Codex: Ereignisname, Werkzeugname, Dateiendung | Tätigkeit und Modell von Codex; Codex erscheint nur als „offen" |
| **Codex-Wächter** (`connectors/codex/watcher.py`) | ob die App läuft; Abo und Wochenlimit aus dem Einstellungsfenster | Codex verschwindet 15 Minuten nach der letzten Aufgabe; Abo und Auslastung fehlen |
| **Antigravity-Wächter** (`connectors/antigravity/watcher.py`) | Transkript der laufenden Sitzung (nur Ereignistyp, Werkzeugname, Dateiendung); Plan, Limits und Modell aus dem Fenster | Antigravity fehlt ganz |

Kein Teil ruft eine Anbieter-Schnittstelle auf, liest ein Token, ein Cookie
oder einen Schlüsselbund. Alles kommt aus lokalen Dateien oder aus dem
Fenster der jeweiligen Anwendung.

## Installation

### Windows

Voraussetzung: Python 3.9 oder neuer von python.org – **nicht** aus dem
Microsoft Store. Store-Apps bekommen einen umgeleiteten Datenordner; damit
schreiben Sender und Connectoren an verschiedene Stellen und sehen einander
nie. `setup_venv.bat` und `standalone\install.ps1` prüfen das.

```bat
git clone https://github.com/Arikazei/CDRP-for-Claude.git
cd CDRP-for-Claude
setup_venv.bat
powershell -ExecutionPolicy Bypass -File standalone\install.ps1
```

`setup_venv.bat` legt `.venv` an, installiert die Abhängigkeiten und kopiert
`config.example.json` nach `config.json`. `install.ps1` richtet drei
Autostart-Einträge ein (Dienst, Codex-Wächter, Antigravity-Wächter), erzeugt
die Codex-Hook-Dateien und startet alles sofort. Im Task-Manager stehen die
drei Einträge unter „Autostart" und lassen sich dort abschalten.

Dann Codex einmalig anbinden, in einem Terminal, in dem `codex` erreichbar
ist (die Desktop-App bringt es mit):

```bat
codex plugin marketplace add "<Repo>\connectors\codex\plugin"
codex plugin add codex-discord-presence@personal
```

Danach in der Codex-App `/hooks` öffnen und die sieben Hooks als
vertrauenswürdig bestätigen. Ohne diese Bestätigung werden sie nicht
ausgeführt, und die App zeigt sie bis dahin unter Umständen gar nicht an.
Bereits laufende Codex-Aufgaben übernehmen neue Hooks nicht; eine neue
Aufgabe starten. Einzelheiten und der Weg ohne Plugin:
[connectors/codex/README.md](connectors/codex/README.md).

Antigravity braucht nichts weiter: der Wächter findet das Transkript unter
`~\.gemini\antigravity` von selbst.

### Linux

Voraussetzung: `python3` ab 3.9, dazu `pypresence` und `jeepney`:

```bash
git clone https://github.com/Arikazei/CDRP-for-Claude.git
cd CDRP-for-Claude
python3 -m pip install --user pypresence jeepney
cp config.example.json config.json
standalone/install.sh
```

`install.sh` legt drei systemd-Benutzerdienste an
(`claude-discord-presence`, `-codex`, `-antigravity`), erzeugt die
Codex-Hook-Dateien und startet alles. Codex wird wie unter Windows angebunden;
alternativ genügt es, den Inhalt von
`~/.local/share/ClaudeDiscordPresence/codex-hooks.json` nach
`~/.codex/hooks.json` zu übernehmen.

Abo und Auslastung von Codex und Antigravity werden unter Linux nicht
gelesen – dafür fehlt die Fensterschnittstelle, UI Automation gibt es nur
unter Windows. Tätigkeit und Modell funktionieren. Fokus, Leerlauf und
Bildschirmleser: siehe [Linux](#linux-1).

### Nur die Claude-Erweiterung

Wer keinen Dienst will, installiert nur die `.mcpb` aus den
[Releases](../../releases) in Claude Desktop. Dann läuft die Presence, solange
Claude Desktop läuft; Codex und Antigravity erscheinen trotzdem, sofern ihre
Wächter und Hooks eingerichtet sind (siehe oben).

Ein Doppelklick auf die `.mcpb` funktioniert **nicht** – Claude Desktop meldet
für diese Endung keine Dateizuordnung an. Installiert wird über das
Entwickler-Menü:

1. **Entwickler-Menü freischalten** mit dem Inhalt `{"allowDevTools": true}`:

   | System | Pfad |
   |---|---|
   | Windows | `%APPDATA%\Claude\developer_settings.json` |
   | Linux | `~/.config/Claude/developer_settings.json` |

   **Ohne BOM speichern.** Schreibt der Editor eine Byte-Order-Mark an den
   Anfang, startet Claude mit „Entwicklereinstellungen konnten nicht geladen
   werden". Unter Windows also nicht mit `Set-Content -Encoding UTF8`, sondern:

   ```powershell
   [System.IO.File]::WriteAllText("$env:APPDATA\Claude\developer_settings.json",
     '{"allowDevTools": true}', (New-Object System.Text.UTF8Encoding $false))
   ```

2. **Claude Desktop komplett beenden** – unter Windows auch das Symbol im
   Infobereich neben der Uhr – und neu starten.

3. **Menüleiste öffnen** (Windows: einmal `Alt` drücken, sie ist ausgeblendet):
   **Entwickler → Erweiterungen → Erweiterung installieren…**, die `.mcpb`
   auswählen, Rückfrage bestätigen.

Deinstallieren geht über Einstellungen → Erweiterungen; verweigert die
Oberfläche das, hilft `tools/remove_extension.ps1` bei geschlossener App.
Unter Linux werden zusätzlich
[Claude Desktop für Linux](https://code.claude.com/docs/en/desktop-linux)
(Beta, Ubuntu 22.04+ oder Debian 12+) und ein `python3` ab 3.9 vorausgesetzt;
dasselbe Paket dient beiden Systemen. Es wird nichts kompiliert: das Paket
enthält Pythons offizielles *Embeddable Package* und ausschließlich reine
Python-Bibliotheken – keine SmartScreen-Warnung, keine typischen
Virenscanner-Fehlalarme.

### Entfernen

`standalone\uninstall.ps1` beziehungsweise `standalone/uninstall.sh` nimmt
Autostart-Einträge beziehungsweise Dienste zurück und beendet die Prozesse.
Die Codex-Hooks bleiben registriert; abschalten lassen sie sich in Codex über
das Plugin.

## Eigene Discord-Anwendung (optional)

Ohne weitere Angaben läuft alles über die mitgelieferte Anwendung – dann
erscheinen deren Name und Bild in deinem Profil. Für einen eigenen Namen und
ein eigenes Bild: im
[Developer Portal](https://discord.com/developers/applications)
*New Application* anlegen, unter *Rich Presence → Art Assets* ein Bild mit dem
Namen `logo` hochladen und die **Application ID** in den Einstellungen
eintragen. Der Asset-Name muss exakt mit `large_image_key` aus der
Konfiguration übereinstimmen, sonst zeigt Discord die Presence ohne Bild.
„Claude" ist als App-Name bei Discord gesperrt.

## Einstellungen

Läuft die Erweiterung, kommen die Einstellungen aus **Claude Desktop →
Einstellungen → Erweiterungen → „Discord Presence for Claude Desktop"**. Die
Felder erzeugt Claude Desktop selbst aus dem Manifest – eine eigene
Oberfläche hat das Projekt bewusst nicht.

| Feld | Bedeutung |
|---|---|
| Discord Application ID | optional – leer lassen für die mitgelieferte Anwendung |
| Presence ausblenden nach | Minuten ohne Eingabe, bis die Presence verschwindet |
| Modell-Limit ausblenden nach | Minuten, bis ein abgelesener Wert als veraltet gilt |
| Abo-Bezeichnung | Notnagel; normalerweise liest sich das selbst aus |
| Text im Leerlauf | erste Zeile, solange kein Chat im Vordergrund ist |

Der Dienst liest dieselben Werte: er nimmt die jüngste `config.json` aus allen
Datenordner-Kandidaten (siehe unten), damit Dialog und Dienst nie
auseinanderlaufen. Wer aus dem Quelltext läuft und keine Erweiterung hat,
bearbeitet `config.json` im Projektordner. Dort gibt es mehr Stellschrauben
als im Dialog, etwa `client_plans` (Abo-Text für Codex und Antigravity, falls
das Fenster nicht gelesen werden kann) und `state_line` (Rotation oder
Verkettung der zweiten Zeile).

### Wo Konfiguration, Protokoll und Beacons liegen

| System | Datenordner |
|---|---|
| Windows | `%USERPROFILE%\AppData\Local\ClaudeDiscordPresence\` |
| Linux | `~/.local/share/ClaudeDiscordPresence/` |

Darin liegen `config.json`, `standalone.log` (Dienst), `claude_rpc.log`
(Erweiterung), `state.json` (was gerade gesendet wird), `sender.<rolle>.json`
(wer gerade sendet), `beacons/<slug>.json` (ein Beacon je Agent) und die
erzeugten Codex-Dateien `codex-hook.cmd` beziehungsweise `.sh` und
`codex-hooks.json`. Die Umgebungsvariable `CLAUDE_RPC_DATA_DIR` lenkt alles
um.

Unter Windows kennt das Projekt bewusst mehrere Kandidatenordner: Anwendungen
aus dem Microsoft Store – die Store-Fassung von Claude Desktop ebenso wie das
Store-Python – bekommen `%LOCALAPPDATA%` still nach
`%LOCALAPPDATA%\Packages\<Paket>\LocalCache\Local\` umgeleitet. Der Sender
liest deshalb aus seinem eigenen Ordner, aus dem Profilpfad oben und aus jedem
`Packages\Claude_*`-Ordner; die Produzenten schreiben immer in den Profilpfad,
denn `%USERPROFILE%` wird nie umgeleitet.

Im Task-Manager heißen Dienst und Wächter `pythonw.exe`, die Erweiterung
`ClaudeDiscordPresence.exe`; unter Linux ist alles `python3`.

**Bei Fassungen der Erweiterung bis einschließlich 1.4.2 lag der Datenordner
woanders.** Das Manifest meldete damals `server.type: "python"`, und Claude
Desktop startete die Erweiterung mit dem `python3` aus dem PATH – war das das
Store-Python, landeten die Dateien unter
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.12_*\LocalCache\Local\ClaudeDiscordPresence\`.
Ab 1.4.3 meldet das Manifest `"binary"`. Wer von einer älteren Fassung kommt,
darf den alten Ordner löschen – er wird nicht mehr gelesen.

## Was gelesen wird

Alles lokal. An Discord gehen nur Statustext, Modell beziehungsweise
Tätigkeit, Dateiart, Auslastung in Prozent und die Abo-Bezeichnung.

- **Claude-Fenster** über die Barrierefreiheitsschnittstelle des Systems
  (Windows UI Automation, Linux AT-SPI): Modellname und die Statuszeile am
  Eingabefeld. Nur dieses eine Fenster – kein globaler Hook, keine Tastatur-
  oder Mausaufzeichnung, kein Fokuswechsel.
- **Desktop Commander**: `~/.claude-server-commander/tool-history.jsonl`,
  ausschließlich das Feld `toolName`. Argumente und Ausgaben stehen in
  derselben Datei und werden bewusst ignoriert.
- **Claude Desktop**: Sitzungsdateien lokaler Cowork-Sessions und die
  Nutzungsdatei `plan-usage-history.json`. Übernommen werden nur Sitzungs-,
  Wochen- und Modell-Limits – der Balken für das Nutzungsguthaben und der
  ausgegebene Betrag bleiben ausdrücklich außen vor.
- **Codex-Hooks**: die Nutzlast, die Codex jedem Hook übergibt. Ausgewertet
  werden `hook_event_name`, `tool_name`, `model` (nur gegen eine feste Tabelle
  bekannter Modelle) und die Endung expliziter Pfadfelder. Prompt,
  Arbeitsverzeichnis, Sitzungskennung und Transkriptpfad liegen in derselben
  Nutzlast und werden verworfen.
- **Antigravity**: `~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript.jsonl`.
  Ausgewertet werden `type`, der Name des ersten Werkzeugaufrufs und die
  Endung seines Pfadarguments. `content` und `thinking` werden nicht gelesen.
- **Fenster von Codex und Antigravity** (nur Windows, nur solange die
  Einstellungen offen sind): Abo-Name und Prozentwerte, und nur, was auf ein
  festes Muster passt. Der Fensterbaum enthält den ganzen Editorinhalt;
  frei gelesen wird darin nichts.
- Systemweit nur: läuft das Programm, ist Claude im Vordergrund, wann war die
  letzte Eingabe. Zeitstempel und Prozessnamen, keine Inhalte.

**Chat-Titel werden gar nicht erst erhoben** – nicht abschaltbar, weil es dafür
keinen Schalter braucht.

**Es wird kein Anmelde-Token gelesen und kein Anbieter-Endpunkt aufgerufen.**
Anthropic untersagt seit Februar 2026 die Verwendung von OAuth-Token aus Free-,
Pro- oder Max-Konten in anderen Produkten; dieses Projekt hält sich davon
vollständig fern, und für Codex und Antigravity gilt dieselbe Regel.

Zur Auslastung: 5-Stunden- und Wochenwert von Claude stehen in einer Datei,
die Claude Desktop selbst alle fünf Minuten fortschreibt. Alles andere –
das modellspezifische Wochenlimit bei Claude, Abo und Limits bei Codex und
Antigravity – wird nur abgelesen, während das jeweilige Nutzungsfenster offen
ist, altert danach sichtbar („Fable 99 % (vor 2 h)") und verschwindet nach
drei Stunden. Lieber keine Zahl als eine falsche.

## Linux

Vollständig unterstützt ab v1.4.0. Weil kein Weg zu Fokus und Leerlaufzeit
überall vorhanden ist, probiert `linuxdesktop.py` sechs gängige der Reihe nach
durch und behält den ersten, der antwortet; welche das sind und warum, steht in
[ARCHITEKTUR.md](ARCHITEKTUR.md#linux-im-einzelnen). Trägt keiner, bleibt die
Presence sichtbar, solange Claude läuft – sie schaltet dann nur nicht mehr auf
„abwesend".

Eine Bedingung stellt Chromium: Seiteninhalt veröffentlicht es nur, wenn ein
Bildschirmleser angemeldet ist. Der Daemon meldet deshalb beim Start einen an
(`ui_watcher.announce_screen_reader`) – das wirkt erst beim **nächsten Start
von Claude**. Bleibt der Baum danach beim Fenstergerüst aus vier Knoten (das
Protokoll sagt es), hilft `--force-renderer-accessibility`:

```bash
cp /usr/share/applications/com.anthropic.Claude.desktop ~/.local/share/applications/
sed -i 's|^Exec=claude-desktop|Exec=claude-desktop --force-renderer-accessibility|' \
  ~/.local/share/applications/com.anthropic.Claude.desktop
```

Was dein Rechner hergibt, sagt das Diagnoseprogramm:

```bash
python3 tools/atspi_dump.py
```

Erkannt wird der Prozess `claude-desktop`. Der nackte Name `claude` gehört der
Kommandozeilenfassung und ist bewusst ausgeschlossen. Heißt der Hauptprozess bei
dir anders, trägst du ihn unter `process_names` ein – das Protokoll nennt bei
Nichterkennung stündlich alle gefundenen Kandidaten samt Pfad. Die Wächter
erkennen `codex`/`chatgpt` und `antigravity` über `/proc`.

## Entwicklung

```bat
setup_venv.bat                                     :: venv + config.json aus config.example.json
.venv\Scripts\python -m unittest tools.test_beacons tools.test_stufe connectors/antigravity/test_watcher.py
cd connectors\codex && ..\..\.venv\Scripts\python -m unittest test_codex_beacon
.venv\Scripts\python tools\probe_codex_hook.py     :: Codex-Hook mit synthetischen Ereignissen, Wegwerfordner
.venv\Scripts\python tools\validate_beacon.py codex :: einen echten Beacon gegen den Vertrag pruefen
powershell -File standalone\neustart.ps1           :: Dienst, Waechter und Erweiterung neu starten
powershell -File build_mcpb.ps1                    :: dist\*.mcpb bauen
```

Die eigene `config.json` bleibt bewusst untracked; Vorlage ist
`config.example.json`. Diese Vorlage ist zugleich die Quelle, aus der
`make_default_config.py` die ausgelieferte `config.default.json` erzeugt –
**neue Schlüssel gehören also nach `config.example.json`**, sonst fehlen sie
im Paket. Sie wird von Hand gepflegt und darf nichts Persönliches enthalten;
App-ID, Knöpfe, Prozessnamen und Abo-Text werden beim Bauen zusätzlich
zurückgesetzt.

Die Hook-Dateien unter `connectors/codex/` sind Vorlagen mit Platzhaltern;
`connectors/codex/install_hooks.py` füllt sie aus. Die erzeugte
`plugin/.../hooks.json` ist untracked, damit nie ein Rechnerpfad ins Repo
gerät.

**Für den Betrieb aus dem Quelltext nicht das Microsoft-Store-Python
verwenden.** Store-Apps bekommen ein umgeleitetes `%APPDATA%` und
`%LOCALAPPDATA%`; das Skript sieht dann weder `%APPDATA%\Claude` noch den
Datenordner der anderen. `_check_env.py` prüft das. Als installierte
Erweiterung entscheidet Claude Desktop das leider selbst – siehe „Wo
Konfiguration, Protokoll und Beacons liegen".

Der Build bricht ab, sobald eine Abhängigkeit eine `.pyd` oder `.dll`
mitbringt – das hält das Paket signaturfrei.

## Lizenz

MIT
