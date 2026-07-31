# Architektur

## Überblick

Ein Python-Daemon liest lokal, was Claude Desktop gerade tut, und schickt drei
Textfelder an Discord. Der Daemon läuft entweder eigenständig
(`start_claude_rpc.vbs`) oder als MCP-Server im `.mcpb`-Paket, das mit der
Claude-Desktop-App startet und endet.

```
Claude-Fenster (UI Automation) ─┐
Desktop-Commander-Verlauf ──────┤
Sitzungs-/Nutzungsdateien ──────┼─→ claude_rpc.py ─→ Discord-IPC-Pipe ─→ Rich Presence
Win32 (Fokus, Idle, Prozesse) ──┘        │
                                          └─→ LAST_STATE ─→ MCP-Werkzeug presence_status
```

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
letzten `status_lookback` (12) Knoten davor, nur wenn Busy gesetzt ist. Ohne
diesen Anker passt auch Text aus dem Chatverlauf — ein Chat, in dem
„… wird verwendet" vorkommt, beschriftet die Presence sonst dauerhaft falsch.
Das ist real passiert.

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
  zusätzlich an `composer_pattern` und `stop_button_names` — beide in der
  Konfiguration änderbar, ohne den Code anzufassen.
- **Cloud-Chats ohne offenes Fenster** liefern nichts; dafür existiert der
  Fallback-Text.
- **Zwei Prozesse sind normal.** Das venv-`pythonw.exe` ist nur eine Weiche auf
  den eigentlichen Interpreter.
- **Der Bildname ist ein Schlüssel, kein Dateiname.** `large_image_key` muss
  exakt dem Asset-Namen im Discord Developer Portal entsprechen; passt er
  nicht, erscheint die Presence stillschweigend ohne Bild. Discord leitet den
  Namen beim Hochladen aus dem Dateinamen ab (klein geschrieben, ohne Endung)
  und lässt ihn danach umbenennen.
