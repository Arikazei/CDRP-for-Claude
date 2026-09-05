# Architektur

## Überblick

Drei Coding-Agenten, eine Discord-Aktivität. Discord zeigt je Nutzer genau
eine Presence und wählt bei mehreren RPC-Verbindungen unzuverlässig aus.
Deshalb sendet genau **ein** Prozess, der Sender; alle anderen melden ihm
ihren Zustand über kleine Dateien, die Beacons. Der Vertrag dafür steht in
[docs/SPEC-beacon-v1.md](docs/SPEC-beacon-v1.md).

```
Produzenten                                  Datenordner                 Sender (genau einer sendet)
──────────────────────────────────────       ────────────────────────    ─────────────────────────────────────
Codex-Hook      codex/codex_beacon.py   ─┐                               standalone/run_presence.py   Rang 2
Codex-Wächter   codex/watcher.py        ─┼─→ beacons/codex.json     ──┐  mcpb/server/main.py          Rang 1
Antigravity-W.  antigravity/watcher.py  ──→ beacons/antigravity.json ─┼─→   claude_rpc.py + beacons.Pool
Claude-Daemon   beacons.eigenen_schreiben ─→ beacons/claude.json     ──┘        │
                                                                                 ├─→ Discord-IPC ─→ Rich Presence
Jeder Sender meldet sich:  sender.<rolle>.json  {rolle, pid, updated_at}         └─→ state.json ─→ presence_status
```

Der Sender selbst liest lokal, was Claude Desktop gerade tut:

```
Claude-Fenster (UI Automation / AT-SPI) ─┐
Desktop-Commander-Verlauf ───────────────┤
Sitzungs-/Nutzungsdateien der App ───────┼─→ claude_rpc.py ─→ Discord-IPC-Pipe ─→ Rich Presence
Fokus, Leerlauf, Prozessliste ───────────┤        │
Beacons der anderen Agenten ─────────────┘        └─→ LAST_STATE ─→ state.json, MCP-Werkzeug presence_status
```

Er läuft in einer von zwei Rollen: als eigenständiger Dienst
(`standalone/run_presence.py`, Autostart beziehungsweise systemd-Benutzerdienst)
oder als MCP-Server im `.mcpb`-Paket, das mit Claude Desktop startet und endet.
Beide führen denselben Code aus (`claude_rpc.main(rolle=…)`); wer sendet,
regelt das Vorrangprotokoll. Der Dienst hat einen Grund zu existieren: er
sendet auch, wenn Claude Desktop zu ist und nur Codex oder Antigravity
arbeiten.

## Vorrangprotokoll

Jeder Sender schreibt seine Kennung nach `<Datenordner>/sender.<rolle>.json`,
im Sendebetrieb bei jedem Durchlauf, im Wartezustand sekündlich:

```json
{"rolle": "standalone", "pid": 12345, "updated_at": 1788600000}
```

Die Regeln stehen in `beacons.py` (`ROLLEN_RANG`, `SENDER_FRISCH`,
`fremder_sender`):

1. **Rang.** `standalone` (2) schlägt `extension` (1). Innerhalb desselben
   Rangs entscheidet weiterhin der Einzelinstanz-Mutex.
2. **Frisch** heißt jünger als 60 Sekunden. Ein älterer Eintrag zählt nicht –
   ein abgestürzter Dienst blockiert niemanden, und niemand muss aufräumen.
3. **Jeder Durchlauf** der Hauptschleife: erst `sender_melden`, dann
   `fremder_sender`. Meldet sich ein Höherrangiger, ruft der Unterlegene
   `sender_abmelden`, gibt den Mutex frei und kehrt zurück – **ohne**
   `presence.clear()`. Der Übernehmende schreibt binnen eines Durchlaufs seine
   eigene Nutzlast darüber; ein Leeren dazwischen ließe die Anzeige sichtbar
   ausgehen. Genau das war das „blinkt und fehlt" früherer Fassungen.
4. **Weiter versuchen.** Der Unterlegene beantwortet nur noch Werkzeugaufrufe
   und versucht die Übernahme erneut: die Extension im Minutentakt, der Dienst
   alle 15 Sekunden bei sekündlicher Meldung. So sieht die Extension den
   wartenden Dienst zuverlässig und gibt frei – die Extension lässt den Mutex
   los und greift ihn drei Sekunden später zurück, wenn niemand schneller ist.
5. **Je Rolle eine Datei.** Eine gemeinsame `sender.json` hat nicht getragen:
   die Kandidatenordner unten zeigen auf dieselbe physische Datei, jeder
   Prozess las Millisekunden nach dem Schreiben seinen eigenen Eintrag zurück,
   und die Rangregel entschied nie etwas.

Die Folge: keine Startreihenfolge. Läuft der Dienst, weicht die Extension
binnen einer Minute. Fällt er aus, übernimmt sie binnen einer Minute. Kommt er
zurück, weicht sie wieder.

## Beacon-Pool

Gelesen wird aus **allen Kandidatenordnern** (`beacons.datenordner_kandidaten`):
dem eigenen, `%USERPROFILE%\AppData\Local\ClaudeDiscordPresence` und jedem
`Packages\Claude_*\LocalCache\Local\ClaudeDiscordPresence`. Der Grund ist die
Store-Umleitung von `%LOCALAPPDATA%`: die Extension in der Store-Fassung von
Claude Desktop landet im Paketordner, Hook und Wächter als gewöhnliche
Prozesse im echten. Beide glauben, denselben Pfad zu benutzen. Geschrieben wird
nur in den eigenen Ordner; Produzenten schreiben nach
`beacons.produzenten_datenordner` – `CLAUDE_RPC_DATA_DIR`, sonst der Profilpfad,
der nie umgeleitet wird. Liegt derselbe Client in mehreren Ordnern, gilt der
jüngste Eintrag.

**Prüfung** (`pruefen`): Pflichtfelder exakt, sonst wird die Datei verworfen
und das einmal je Prozess protokolliert. Die Zusatzfelder `plan` und `usage`
werden einzeln geprüft; ein unbrauchbares Zusatzfeld verwirft nur sich selbst.
Marken werden erst im Sender zu Text (`AKTIONSTEXT`, `DATEIART`) – ein
Produzent kann keine Formulierung in die Presence schreiben.

**Verfallsleiter** (`verfallen`): ein abgestürzter Produzent hinterlässt eine
alte Datei, die schrittweise zurückgestuft wird statt sofort geglaubt oder
sofort verworfen.

| Alter von `updated_at` | Wertung |
|---|---|
| < 45 s | wie geschrieben |
| 45 s bis 180 s | `working` wird zu `waiting` |
| 180 s bis 900 s | `idle` |
| > 900 s | ignoriert |

**Rahmen und Karten.** `aktive()` liefert alle Clients mit `state == working`,
sortiert nach Namen; `karten()` macht daraus vollständige Anzeigen (Zeile 1,
Zeile 2, Sitzungsbeginn), und `karte_waehlen()` wechselt alle 20 Sekunden –
nie unter 15, weil Discord bei häufigeren Aktualisierungen die Presence nicht
drosselt, sondern leert. Zeile 1 und 2 stammen immer vom selben Client. Ohne
Arbeitenden gilt `rahmen_waehlen()`: der jüngste `waiting`, sonst der jüngste
fremde `idle`; Claudes eigener Leerlauf hat den Leerlauftext aus der
Konfiguration. Zwei frühere Anläufe suchten einen Gewinner und waren beide
falsch: der jüngste Zeitstempel gehört dem, der am öftesten schreibt, und ein
Besitzervorrang ließ Claude während jeder Cowork-Sitzung den Rahmen behalten.

## Connectoren

### Codex

Zwei Teile, weil die Hooks nur bei Ereignissen feuern.

**Hook** (`connectors/codex/codex_beacon.py`): Codex ruft ihn bei
`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PermissionRequest`, `Stop` und `SessionEnd` mit einer JSON-Nutzlast auf. Aus
`hook_event_name` und `tool_name` werden `state` und `action`; das Modell nur
gegen die feste Tabelle `MODEL_LABELS`; `file_kind` nur aus der Endung
expliziter Pfadfelder (`PATH_KEYS`) oder der Kopfzeile eines `apply_patch`.
Zwischen den Aufrufen merkt sich der Hook seinen Stand in `codex.state.json`
(Punkt im Namen: der Pool überliest Beistelldateien). Geschrieben wird bei
Änderung oder als Herzschlag alle 20 Sekunden; die Antwort ist immer `{}` mit
Exitcode 0 – ein Presence-Fehler darf einen Codex-Zug nie beeinflussen.

**Wächter** (`connectors/codex/watcher.py`), alle 15 Sekunden:

- App zu (`tasklist`, Vergleich auf Bytes wegen der Konsolen-Codepage) → Beacon
  löschen, sofort, nicht nach 15 Minuten.
- App offen, letzter Stand `working` → denselben Stand alle 20 Sekunden mit
  frischer Uhrzeit nachschreiben, höchstens 10 Minuten. Die Hooks feuern je
  Werkzeugaufruf; ein langer Denkzug oder ein minutenlanger Befehl käme sonst
  nach 45 Sekunden als `waiting` an.
- App offen, Hook-Stand `waiting` → in Ruhe lassen, bis der Sender ihn ohnehin
  auf `idle` gestuft hätte (200 s); danach ein `idle`-Beacon alle 60 Sekunden.
  Das hält Codex in der Rotation, solange die App offen ist.
- Alle 20 Sekunden ein Blick ins Fenster (`fenster.py`): Tarifname und
  Wochenlimit aus „Nutzung und Abrechnung", abgelegt in `codex.window.json`
  mit Zeitstempel. Auslastung altert nach 3 Stunden, der Plan nach 30 Tagen.

**Starter.** Codex startet unter Windows keine Befehlszeile mit
Anführungszeichen; ein Interpreterpfad mit Leerzeichen lässt sich nicht
eintragen. `install_hooks.py` erzeugt deshalb eine winzige `.cmd` unter einem
Pfad ohne Leerzeichen, die Interpreter und `codex_beacon.py` des Repos aufruft,
und füllt damit die Vorlagen `hooks.json` (global) und `plugin/…/hooks.json.in`
(Plugin). Der Starter wird nie von Hand gepflegt – eine handgepflegte Kopie
lief hier still auseinander. Codex führt nicht verwaltete Hooks erst aus,
nachdem sie in `/hooks` bestätigt wurden, und speichert dafür einen Hash je
Hook in `config.toml`; ändert sich der Starterpfad, ist die Bestätigung erneut
fällig.

### Antigravity

Ein Wächter (`connectors/antigravity/watcher.py`), Takt eine Sekunde:

- Läuft `Antigravity.exe` nicht (zwischengespeichert für 15 s) → Beacon löschen.
- Jüngstes Transkript nach Änderungszeit:
  `~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript.jsonl`,
  angehängt gelesen; halbe Zeilen werden zurückgespult.
- Positivliste je Zeile: `USER_INPUT` → `thinking`; `view_file` → `reading`;
  `write_to_file`/`replace_file_content` → `editing`; `run_command` →
  `running_tests` oder `running_command`; `search_web`/`read_url_content` →
  `web_search`; `ask_question` → `waiting_approval`; Antwort ohne Werkzeug →
  `waiting/idle`. `content` und `thinking` werden nicht gelesen; nur aus
  Systemmeldungen zur Modellwahl kommt ein Modellname aus fester Liste.
- 30 Sekunden Stille → `waiting/idle` (keine Behauptung, worauf gewartet wird),
  3 Minuten → `idle`. Herzschlag alle 5 Sekunden bei Arbeit, alle 60 in Ruhe.
- Fenster (`fenster.py`): nur der Abschnitt „Models & Usage", nur Werte der
  Form `^\d{1,3}%$` und ein kurzer Planname, nur zwischen den bekannten
  Überschriften – derselbe Baum enthält den ganzen Editorinhalt. Das Modell
  kommt aus der Beschriftung des Modellknopfs („Select model, current: …"),
  nicht aus sichtbarem Text, weil auch Dokumenttext Modellnamen enthält.
  „Remaining" wird zu „verbraucht" umgerechnet.

### Gemeinsam

`connectors/gemeinsam/uia.py` findet Fenster nach Prozessnamen und liest den
Baum flach in Dokumentreihenfolge, gedeckelt (20 000 Knoten, 8 Sekunden).
Eigenes Modul, weil beide Connectoren eine `fenster.py` haben: importiert der
eine „fenster", bekommt er sich selbst, und der Fehler war lautlos.
`uiautomation` wird erst dort importiert, damit ein Wächter auch ohne COM
startet und dann nur auf die Fensterwerte verzichtet.

## Zustandsmaschine

Die Hauptschleife pollt alle 5 Sekunden (`poll_interval_seconds`):

| Zustand | Bedingung | Anzeige |
|---|---|---|
| AKTIV | Claude-Fenster im Vordergrund **und** letzte Eingabe < 90 s | Presence sichtbar, Timer läuft |
| OFFEN | Claude läuft, aber kein Fokus oder keine Eingabe | Presence bleibt bis zum Zeitablauf sichtbar |
| AUS | länger als `idle_timeout_minutes` (25) inaktiv, pausiert, oder `claude.exe` läuft nicht | Presence entfernt; Timer startet bei Rückkehr neu |

Fokus und Leerlauf kommen aus `GetForegroundWindow`, `GetWindowThreadProcessId`
und `GetLastInputInfo`. Die Prozessliste über `CreateToolhelp32Snapshot` und
`QueryFullProcessImageNameW` — bewusst ctypes statt psutil, damit das Paket
keine kompilierte Fremdbibliothek enthält.

## Die beiden Discord-Zeilen

Die Aufteilung folgt der Änderungsrate, nicht der Wichtigkeit.

**Erste Zeile — die schnelle.** Was Claude in diesem Moment tut: „Claude denkt
nach", „Desktop Commander: read_file", „Websuche wird verwendet". Das ändert
sich im Sekundentakt und wird deshalb nie rotiert — hier würde Rotation dazu
führen, dass man den halben Arbeitsablauf verpasst. Ohne laufende Tätigkeit
steht dort der Leerlauftext aus `texts.open`.

**Zweite Zeile — die langsame.** Rotiert bei `state_line.mode: "alternate"`
alle 20 Sekunden durch drei Segmente; `"join"` hängt sie stattdessen mit `·`
aneinander. Alle drei ändern sich im Minutentakt oder seltener, deshalb geht
durch die Rotation nichts verloren.

1. **Sitzung** — „using cowork with Opus 5"; das Modell wechselt nur beim
   Chatwechsel
2. **Auslastung** — Prozentwerte, die die App alle 5 Minuten fortschreibt
3. **Abo** — `plan_template` über `plan_override`, ergibt „Abonnement: Max 5x";
   praktisch statisch

## Plattformschicht

`hostplatform.py` bündelt alles, was pro Betriebssystem verschieden ist:
Prozessliste, Pfad und Befehlszeile einer PID, Vordergrundfenster,
Leerlaufzeit, Einzelinstanz-Sperre und der Datenordner der Claude-App.
`claude_rpc.py` enthält seither keinen einzigen `ctypes`-Aufruf mehr.

Zwei Zusagen sind ausdrücklich optional: `FOCUS_SUPPORTED` und
`IDLE_SUPPORTED`. Wo sie `False` sind, darf sich der Aufrufer nicht auf
Fokus und Leerlaufzeit verlassen — die Hauptschleife weicht dann auf
„läuft Claude überhaupt" aus und lässt die Presence sichtbar, solange die
App läuft. Das ist kein Schönheitsfehler: **Wayland gibt das aktive Fenster
und die systemweite Leerlaufzeit aus Sicherheitsgründen gar nicht heraus**,
und keine Bibliothek der Welt ändert daran etwas.

| | Windows | Linux (Stufe 1) |
|---|---|---|
| Prozessliste | Toolhelp32 | `/proc` |
| Pfad zur EXE | `QueryFullProcessImageNameW` | `/proc/<pid>/exe` |
| Befehlszeile | WMI über PowerShell | `/proc/<pid>/cmdline` |
| Einzelinstanz | benannter Mutex | `flock` auf einer Sperrdatei |
| Datenordner | `%APPDATA%\Claude` | `~/.config/Claude` |
| Fokus, Leerlauf | Win32 | offen (X11 wäre Stufe 2) |
| Fenster auslesen | UI Automation | offen (AT-SPI wäre Stufe 3) |

## Module

### UIWatcher — die einzige Quelle für Cloud-Sessions

Sucht unter den Top-Level-Fenstern eines mit `ClassName ~ Chrome_WidgetWin`
**und** `Name ~ Claude` und läuft dann genau diesen Fensterbaum ab, gedeckelt
auf `max_nodes` (3000), alle 8 Sekunden, rund 0,9 Sekunden pro Durchlauf.
Ein Durchlauf liefert drei Dinge:

- **Modell** aus dem Button `Modell: <Name>` über dem Eingabefeld
- **Busy** — der Button „Antwort stoppen" existiert nur, während Claude arbeitet
- **Status** — der Text direkt über dem Eingabefeld, z. B. „Desktop Commander
  wird verwendet…" oder „Claude denkt nach…"

Der Chat-Titel steht im Fenstertitel ebenfalls zur Verfügung und wird bewusst
**nicht** eingesammelt. Es gibt dafür auch keinen Schalter: was gar nicht erst
erhoben wird, kann niemand versehentlich veröffentlichen.

Der Status wird **am Eingabefeld verankert** gesucht: nur TextControls in den
letzten `status_lookback` (12) Knoten davor und den `status_lookahead` (8)
Knoten dahinter, nur wenn Busy gesetzt ist. Ohne diesen Anker passt auch Text
aus dem Chatverlauf — ein Chat, in dem „… wird verwendet" vorkommt,
beschriftet die Presence sonst dauerhaft falsch. Das ist real passiert. Der
Blick nach hinten reicht nur bis in die Knopfreihe des Eingabebereichs; der
Chatverlauf liegt davor und bleibt so oder so unerreichbar.

**Zwei Ansichten, zwei Benennungen.** Der Cloud-Chat und die Sitzungsansicht
von Claude Code beschriften dieselben Dinge verschieden. Geprüft wird immer
erst das Cloud-Muster, dann das der Sitzungsansicht:

| Sache | Cloud-Chat | Sitzungsansicht |
|---|---|---|
| Anker | `EditControl`, `composer_pattern` | Name gleich `composer_anchor_names` („Prompt") |
| Modell | `ButtonControl "Modell: <Name>"` | `ButtonControl "<Name>"`, `bare_model_pattern` |
| Busy | `"Antwort stoppen"` | `"Stop"` |
| Statusleiste | über dem Eingabefeld | darunter |

`stop_button_names` und `composer_anchor_names` werden gegen den **ganzen**
Namen verglichen, nie gegen ein Teilstück: im selben Fenster sitzt die Leiste
der Hintergrundaufgaben mit „Stop this task", und ein Teilstück-Vergleich
hätte die Presence bei jeder laufenden Hintergrundaufgabe auf „arbeitet
gerade" gestellt.

Vom Behälter „Prompt" wird ausschließlich der **Name** gelesen, nie sein
Inhalt — der ist die Eingabe des Nutzers.

Stammt das Modell vom blossen Knopf, ist die Ansicht sicher die von Claude
Code; die zweite Zeile beschriftet das dann über `code_template` als
„using code with …" statt „using cowork with …".

Beim ersten Zugriff wird einmalig ein `DocumentControl` angefordert; erst
dadurch baut Electron den Accessibility-Tree überhaupt auf.

Elektron-Statustexte enden auf „…". Findet sich in dem Fenster keine bekannte
Formulierung, gewinnt trotzdem die letzte Zeile über dem Eingabefeld — so
überleben auch Statustexte, die es heute noch nicht gibt.

### ToolHistoryWatcher

Liest `~/.claude-server-commander/tool-history.jsonl` und wertet
**ausschließlich das Feld `toolName`** aus. Dieselbe Datei enthält Argumente
und vollständige Ausgaben, also Dateipfade und Dateiinhalte — die dürfen nicht
in eine öffentlich sichtbare Presence geraten. Frischefenster 25 Sekunden,
Vorlage `Desktop Commander: {tool}`; alternativ `{action}` für ausformulierte
Texte aus `DEFAULT_LABELS`.

Meldet die Oberfläche Werkzeugnutzung **und** ist der Verlauf frisch, gewinnt
der Verlauf — nur er kennt den Werkzeugnamen.

### LocalSessionWatcher

`%APPDATA%\Claude\claude-code-sessions\<Konto>\<Gerät>\local_*.json` beschreibt
lokal laufende Cowork-Sessions: `model`, `title`, `cwd`, `lastActivityAt`.
Genommen wird die zuletzt aktive, sofern jünger als 30 Minuten. Ersetzt den
früheren Beacon-Umweg für Sessions, die auf dem eigenen Rechner laufen.

### LocalUsageWatcher

`%APPDATA%\Claude\plan-usage-history.json` schreibt die App alle 5 Minuten:
`fh` = 5-Stunden-Fenster, `sd` = 7-Tage-Fenster, `xu` = Nutzungsguthaben,
jeweils in Prozent. Beide erstgenannten sind immer aktuell und bilden die
Grundlage der Auslastungsanzeige.

**`xu` ist standardmäßig aus.** Der Wert entspricht dem Balken
*Nutzungsguthaben* im Nutzungsfenster — daneben steht dort der ausgegebene
Betrag in Euro. Eine Prozentzahl über das eigene Geld gehört nicht in ein
öffentliches Profil. Wer es trotzdem will, setzt `show_extra`.

Ein modellspezifisches Wochenlimit steht in dieser Datei **nicht**, siehe
`LimitStore`.

### LimitStore — das modellspezifische Limit

Es gibt keine lokale Datei mit diesem Wert. Geprüft wurde der gesamte
`%APPDATA%\Claude`-Baum: 34 Dateien enthalten die Feldnamen `five_hour`,
`seven_day_opus` und so weiter, aber alle davon sind Programmcode — der
V8-Bytecode-Cache des JS-Bundles und ein Plugin mit hartkodierten
Schwellwerten. Kontowerte stehen nirgends. Sie leben ausschließlich im
Arbeitsspeicher des Renderers.

Also wird abgelesen, was ohnehin auf dem Bildschirm steht. Im Nutzungsfenster
trägt jede Fortschrittsleiste den Namen ihres Limits, der Prozentwert steht im
nächsten Textknoten:

```
ProgressBar "Fable"  →  Text "99 % verwendet"
Text "Max (5x)"      →  Abo-Stufe
```

Der `UIWatcher` sammelt das im selben Durchlauf mit, den er ohnehin macht —
Mehrkosten also null. `LimitStore` legt die Werte mit Zeitstempel in
`ui_limits.json` ab und schreibt nur bei echter Änderung oder höchstens
minütlich.

**Positivliste statt Ausschluss.** Im selben Fenster stehen das
Nutzungsguthaben und der ausgegebene Betrag in Euro. Übernommen werden nur
Balken, die auf `Aktuelle Sitzung`, `Alle Modelle` oder einen Modellnamen
passen; alles andere fällt durch, auch künftige Balken. Geld gehört nicht in
eine öffentlich sichtbare Presence.

**Alterung.** Bis `age_marker_minutes` (30) wird der Wert nackt angezeigt,
danach mit Vermerk („Fable 99 % (vor 2 h)"), nach `max_age_minutes` (180)
verschwindet er. Eine falsche Zahl ist schlechter als keine.

Die Abo-Stufe wird nur übernommen, wenn im selben Durchlauf auch Limit-Balken
gefunden wurden — sonst genügt ein „Max" irgendwo im Chatverlauf als Treffer.
Das ist beim Testen tatsächlich passiert.

Ein früheres Modul hat diese Werte über `GET /api/oauth/usage` mit dem Token
aus `.credentials.json` geholt. Das ist ersatzlos entfernt: Anthropic
untersagt seit Februar 2026 die Verwendung von Abo-OAuth-Token in
Drittanwendungen, und die Formulierung unterscheidet nicht zwischen Lesen und
Schreiben — ein GET ist ebenso Verwendung.

### SessionInfo, CoworkBeacon, ActivityWatcher

Ältere Ebenen, weiterhin als Rückfall aktiv:

- **SessionInfo** — neueste JSONL unter `~/.claude/projects/`, Modell per Regex,
  nur wenn die Sitzung jünger als 10 Minuten ist
- **CoworkBeacon** — `cowork_status.json`, das eine Cowork-Session selbst
  schreiben kann; greift nur, wenn nichts anderes zieht
- **ActivityWatcher** — mtime der App-Logs; grobstes Signal, kennt nur den
  Servernamen, nicht das Werkzeug

**Priorität Info-Zeile:** SessionInfo → LocalSession → UIWatcher → Beacon → Fallback
**Priorität Aktivität:** Werkzeugverlauf (wenn UI Werkzeugnutzung meldet) → UI-Status → Werkzeugverlauf → Log-mtime

## MCP-Server

`mcpb/server/main.py` ist handgeschriebenes JSON-RPC über stdio. Kein SDK: das
offizielle `mcp`-Paket zieht `pydantic` nach, und das bringt eine kompilierte
Rust-Erweiterung mit.

Ablauf beim Start: Einstellungen aus dem Manifest (`user_config` →
Umgebungsvariablen) werden über `server/config.default.json` gelegt und als
`%LOCALAPPDATA%\ClaudeDiscordPresence\config.json` geschrieben. Erst danach
wird `claude_rpc` importiert und dessen Hauptschleife als Daemon-Thread
gestartet. Der Code-Ordner bleibt schreibgeschützt nutzbar, weil Konfiguration,
Log und Beacon über `CLAUDE_RPC_DATA_DIR` umgelenkt werden.

Methoden: `initialize`, `ping`, `tools/list`, `tools/call`.
Werkzeuge: `presence_status`, `presence_pause`, `presence_resume`.

## Paket

`build_mcpb.ps1` lädt Pythons offizielles Embeddable Package (`python.exe` von
der PSF signiert), installiert die Abhängigkeiten als reine Python-Pakete nach
`server/lib`, entfernt die von `uiautomation` mitgelieferten Typelib-DLLs
(`comtypes` erzeugt die Bindung genauso gut aus der systemeigenen
`UIAutomationCore.dll` — getestet) und **bricht ab, sobald eine `.pyd` oder
`.dll` im Bundle landet**. Ergebnis: rund 11 MB, keine unsignierte
Binärdatei, kein SmartScreen-Dialog, keine typischen Virenscanner-Fehlalarme.

Genau diese Prüfung hat gefunden, dass `requests` über `charset_normalizer`
zwei mypyc-kompilierte `.pyd` einschleppt — deshalb läuft HTTP jetzt über
`urllib`.

## Fallstricke

- **Microsoft-Store-Python macht das Projekt stumm.** Store-Apps bekommen ein
  umgeleitetes `%APPDATA%`; der Ordner `%APPDATA%\Claude` ist dann unsichtbar
  und sämtliche Datei-Leser liefern nichts, ohne Fehlermeldung. `_check_env.py`
  prüft das, `setup_venv.bat` nutzt bewusst ein anderes Python.
- **Der Usage-Endpunkt drosselt.** 5-Minuten-Intervall nicht verkürzen.
- **Ändert Claude die Fensterbeschriftung**, bricht die Modellerkennung. Regex
  `Modell?:` in `UIWatcher._scan` anpassen. Statuszeile und Busy-Flag hängen
  zusätzlich an `composer_pattern`, `composer_anchor_names`,
  `bare_model_pattern` und `stop_button_names` — alle in der Konfiguration
  änderbar, ohne den Code anzufassen. Dort gehören auch weitere Sprachen hin.
- **Cloud-Chats ohne offenes Fenster** liefern nichts; dafür existiert der
  Fallback-Text.
- **Zwei Prozesse sind normal.** Das venv-`pythonw.exe` ist nur eine Weiche auf
  den eigentlichen Interpreter.
- **Der Bildname ist ein Schlüssel, kein Dateiname.** `large_image_key` muss
  exakt dem Asset-Namen im Discord Developer Portal entsprechen; passt er
  nicht, erscheint die Presence stillschweigend ohne Bild. Discord leitet den
  Namen beim Hochladen aus dem Dateinamen ab (klein geschrieben, ohne Endung)
  und lässt ihn danach umbenennen.

## Linux im Einzelnen

Aus dem README hierher verschoben: fuer die Benutzung braucht man das nicht,
fuer die Fehlersuche schon.

### Leerlaufmessung, sechs Wege

Keiner dieser Wege ist ueberall vorhanden. `linuxdesktop.py` probiert sie der
Reihe nach durch und behaelt den ersten, der antwortet.

| Weg | wo er traegt |
|---|---|
| Wayland `ext-idle-notify-v1` | Plasma 6, GNOME 45+, Sway, Hyprland |
| GNOME Mutter `IdleMonitor` | GNOME unter X11 und Wayland |
| `org.freedesktop.ScreenSaver` | KDE unter X11, XFCE, MATE |
| X11 MIT-SCREEN-SAVER | jede reine X11-Sitzung |
| systemd-logind `IdleSinceHint` | wo die Sitzungsverwaltung ihn pflegt |
| Sperrbildschirm an/aus | grober Notnagel, nur zwei Zustaende |

Unter Plasma 6 traegt nur `ext-idle-notify-v1` in **Fassung 2**
(`get_input_idle_notification`). Fassung 1 meldet nie Leerlauf, sobald
irgendeine Anwendung eine Leerlaufsperre haelt -- VR-Laufzeiten und Browser
mit Ton tun das dauerhaft.

Das Wayland-Protokoll liefert **keine Zeit**, sondern meldet nur das Ueber-
und Unterschreiten einer angemeldeten Schwelle. `idle_configure()` muss
deshalb vor der ersten Messung kommen.

### Fokus ueber AT-SPI

Der Fokus laeuft ueber die Barrierefreiheitsschnittstelle, weil das der
einzige desktopuebergreifende Weg ist: KDE und GNOME geben das aktive Fenster
unter Wayland aus Sicherheitsgruenden nicht heraus, AT-SPI dagegen ist ein
freedesktop-Standard ueber D-Bus und damit unabhaengig vom Fenstersystem.

Kennt der Desktop den Zustand "aktiv" zwar, pflegt ihn aber nicht -- unter
Plasma 6 beobachtet --, meldet ihn kein einziges Fenster auf dem Bus. Dieser
Fall wird als unbrauchbares Signal gewertet, nicht als "Claude ist nie im
Vordergrund".

Eine **D-Bus-Fehlerantwort ist eine gueltige Nachricht**, keine Ausnahme. Wer
nur `try/except` schreibt, reicht den Fehlertext als Nutzdaten weiter; der
`message_type` muss geprueft werden.

### Fensterbaum und Bildschirmleser

Chromium veroeffentlicht Seiteninhalt nur, wenn ein Bildschirmleser angemeldet
ist (`org.a11y.Status.ScreenReaderEnabled`). `IsEnabled` genuegt ihm nicht,
weil ein vollstaendiger Baum Rechenzeit kostet. Ohne Anmeldung sieht der
UIWatcher genau vier Knoten -- das Fenstergeruest ohne Inhalt.

Der Daemon meldet beim Start selbst einen an
(`ui_watcher.announce_screen_reader`, Vorgabe an). Der Schalter wirkt erst
beim naechsten Start von Claude, weil Chromium ihn beim Hochfahren des
Renderers liest.
