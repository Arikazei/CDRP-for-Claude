# Übergabe: Discord Rich Presence für Claude Desktop

Kontext für eine neue Sitzung. Alles Wesentliche steht hier; Details im Repo.

---

## Projekt

Ein Daemon zeigt in Discord an, woran gerade mit Claude Desktop gearbeitet
wird. Ausgeliefert als Claude-Desktop-Erweiterung (`.mcpb`), die einen
MCP-Server startet, der den Presence-Daemon im selben Prozess laufen lässt.

- Repo: <https://github.com/Arikazei/CDRP-for-Claude> (öffentlich)
- Lokal: `C:\Users\marco\source\claude-rpc`
- Aktuelle Fassung: **v1.4.1**, Windows und Linux
- GitHub-Konto: **Arikazei** (`gh` ist angemeldet). Klarnamen nicht verwenden.
- Discord-Anwendung: **„Vibecode maxxing"**, mitgelieferte
  `client_id` = `1529478569636659372`

Zwei Zeilen in Discord: Zeile 1 die laufende Tätigkeit (schnell), Zeile 2
Sitzung/Modell, Auslastung und Abo (langsam, rotierend).

---

## Regeln, die nicht verhandelbar sind

1. **Keine kompilierten Abhängigkeiten.** Alles reines Python. Der Build
   bricht ab, wenn eine `.so`, `.pyd` oder `.dll` ins Paket gerät. Deshalb
   `jeepney` statt `dbus-python`, deshalb ist das Wayland-Protokoll von Hand
   gesprochen.
2. **Keine Chatinhalte, keine Chattitel, keine Dateipfade** in der Presence.
   Auch nicht hinter einer Einstellung. An Discord gehen nur Statustext,
   Modell/Aktivität, Auslastung in Prozent und Abo-Bezeichnung.
3. **Keine Anfragen an die Anthropic-API, kein Auslesen von Tokens** — das
   ist nach Anthropics Bedingungen untersagt. Alle Werte kommen aus lokalen
   Dateien oder aus dem Fenster selbst.
4. **Quelltext in ASCII** (`ae`/`oe`/`ue`), Zeilenenden LF, Kommentare auf
   Deutsch. Kommentare erklären das *Warum*, nicht das Was.

---

## Aufbau

| Datei | Aufgabe |
|---|---|
| `claude_rpc.py` | Daemon: Beobachter-Module und Hauptschleife |
| `hostplatform.py` | alles Betriebssystemabhängige hinter einer Schnittstelle |
| `linuxdesktop.py` | Linux: Leerlauf, Fokus, AT-SPI, Barrierefreiheit |
| `mcpb/manifest.json` | Erweiterungsbeschreibung, Einstellungen, Startbefehl |
| `mcpb/server/main.py` | MCP-Server von Hand, startet den Daemon |
| `mcpb/make_default_config.py` | erzeugt die mitgelieferte Konfiguration **aus der lokalen `config.json`** |
| `build_mcpb.ps1` | baut das `.mcpb` (nur Windows) |
| `tools/atspi_dump.py` | Linux-Diagnose |
| `tools/build_atspi_dump.sh` | packt sie zur eigenständigen Datei |

Der Fensterleser (`UIWatcher`) liest unter Windows über UI Automation, unter
Linux über AT-SPI. Beide erzeugen dieselbe Liste `(Steuerelementtyp, Name)`,
die Auswertung danach ist gemeinsam; die Rollen werden an einer Stelle
übersetzt (`ATSPI_ROLLEN`).

---

## Stand

**Windows:** vollständig, im Betrieb geprüft.

**Linux:** vollständig implementiert, auf Plasma 6 mit Wayland entwickelt und
im Betrieb geprüft (Beitrag von GitHub-Nutzer **nerdrx**, PR #1, gemerged).

- Leerlauf über eine Kette von sechs Wegen, erster antwortender gewinnt.
  Unter Plasma 6 trägt nur Wayland `ext-idle-notify-v1` **Fassung 2**
  (`get_input_idle_notification`) — Fassung 1 meldet nie Leerlauf, sobald
  irgendeine Anwendung eine Leerlaufsperre hält (VR, Browser mit Ton).
- Fokus über AT-SPI, weil KDE und GNOME das aktive Fenster unter Wayland
  nicht herausgeben.
- Fensterleser braucht einen angemeldeten Bildschirmleser
  (`org.a11y.Status.ScreenReaderEnabled`); ohne ihn veröffentlicht Chromium
  nur das Fenstergerüst aus vier Knoten. Der Daemon meldet einen an
  (`ui_watcher.announce_screen_reader`, Vorgabe an, abschaltbar). Wirkt erst
  beim **nächsten Start von Claude**.

---

## Offene Punkte

1. **Marco hat v1.4.1 noch nicht installiert.** Nach der Neuinstallation von
   Claude Desktop ist die Erweiterung weg. Paket liegt unter
   `dist\claude-discord-presence-1.4.1.mcpb`, Installationsweg siehe README
   (Entwicklermenü, `developer_settings.json` **ohne BOM**).
2. **Die Schutzprüfung im Bauskript fehlt noch.** Ein `"_kommentar"` im
   Manifest hat die Installation von v1.2.0 bis v1.4.0 verhindert
   (*Invalid manifest: server: Unrecognized key(s)*), unbemerkt, weil in der
   Zeit niemand installiert hat. Das Manifest ist bereinigt, aber diese
   Prüfung ist noch nicht im Repo — gehört in `build_mcpb.ps1` unmittelbar
   vor `Write-Host "6/6  Paket schnueren"`:

   ```powershell
   $ManifestRoh = Get-Content (Join-Path $Build "manifest.json") -Raw
   if ($ManifestRoh -match '"_[a-zA-Z]') {
       throw "Manifest enthaelt einen Schluessel mit Unterstrich-Praefix - Claude Desktop lehnt das Paket damit ab."
   }
   ```

   Danach `$Manifest = $ManifestRoh | ConvertFrom-Json` statt des erneuten
   `Get-Content`. Erläuterungen gehören ab sofort ins Bauskript, nicht ins JSON.
3. **Backslashes als Pfadtrenner im Paket.** PowerShells `Compress-Archive`
   schreibt `server\main.py` statt `server/main.py`. Die ZIP-Spezifikation
   sieht das nicht vor; `unzip` warnt, entpackt aber korrekt, Windows
   ebenfalls. Unter Linux ungetestet — falls die Installation dort mit
   fehlenden Dateien scheitert, ist das der erste Verdacht. Fix: Archiv nach
   dem Bauen mit Python neu schreiben und die Namen normalisieren.
4. **Ende-zu-Ende-Test unter Linux steht aus.** nerdrx hat aus dem Quelltext
   gearbeitet, die `.mcpb` dort nie installiert.
5. **`UEBERGABE-LINUX.md` aus dem Repo entfernen**, falls noch nicht
   geschehen — Aufgaben erledigt, gehört nicht dorthin.

---

## Arbeitsumgebung

- Bauen läuft nur unter Windows: `powershell -ExecutionPolicy Bypass -File .\build_mcpb.ps1`.
  Venv liegt in `.venv`, Runtime wird beim Bauen geholt.
- **Achtung:** `make_default_config.py` erzeugt die mitgelieferte
  Konfiguration aus Marcos **lokaler `config.json`**. Neue Schlüssel dort
  eintragen, sonst fehlen sie im ausgelieferten Paket.
- Diagnoseprogramm bauen (Linux/Container): `bash tools/build_atspi_dump.sh`
- Daemon eigenständig testen:
  `CLAUDE_RPC_CONFIG=$PWD/config.json CLAUDE_RPC_LOG=/tmp/rpc.log python3 claude_rpc.py`
  — schreibt nichts auf die Konsole, alles ins Protokoll.
- Installiert liegen Konfiguration und Protokoll unter
  `%LOCALAPPDATA%\ClaudeDiscordPresence\`. Der Prozess heißt im Task-Manager
  `ClaudeDiscordPresence.exe`.
- PowerShell: keine Backtick-Zeilenfortsetzungen an Marco geben, die gehen
  beim Einfügen verloren und kleben Befehle zusammen. Ein Befehl, eine Zeile.

---

## Fallstricke, die schon Zeit gekostet haben

- Eine **D-Bus-Fehlerantwort ist eine gültige Nachricht**, keine Ausnahme.
  Wer nur `try/except` schreibt, reicht den Fehlertext als Nutzdaten weiter.
  `message_type` prüfen.
- Das **Wayland-Leerlaufprotokoll liefert keine Zeit**, es meldet das
  Über- und Unterschreiten einer angemeldeten Schwelle. `idle_configure()`
  muss vor der ersten Messung kommen.
- Der nackte Prozessname `claude` gehört der **Kommandozeilenfassung**
  (`/opt/claude-code/bin/claude`), nicht der Desktop-App. Bewusst
  ausgeschlossen.
- `developer_settings.json` **ohne BOM** schreiben, sonst startet Claude mit
  „Entwicklereinstellungen konnten nicht geladen werden".
- Die Statuszeile wird **am Eingabefeld verankert** gesucht (12 Knoten
  davor). Ohne diesen Anker passt auch Text aus dem Chatverlauf.
- Bei den Limits gilt eine **Positivliste**: im Nutzungsfenster steht neben
  den Balken ein Guthaben in Euro, das nie in die Presence darf.
- `dist/` ist in `.gitignore`. Gebaute Dateien gehören an den Release.

---

## Zur Sitzung selbst

Die vorige Sitzung verlor die Verbindung zum Rechner („The device this
session is bound to is not connected to the bridge"), nachdem Claude Desktop
neu installiert wurde — ein Neustart der App brachte sie nicht zurück.
Deshalb dieser Wechsel. Falls die Werkzeuge für den Rechner wieder fehlen:
`get_device_info` aufrufen, das sagt es eindeutig.
