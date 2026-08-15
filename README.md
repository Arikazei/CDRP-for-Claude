# Discord Presence für Claude Desktop

Zeigt in Discord an, woran du gerade mit Claude Desktop arbeitest: das Modell
des offenen Chats, was Claude gerade tut, deine Auslastung, dein Abonnement und
ein Timer. Die Presence verschwindet nach einstellbarer Inaktivität und ist bei
Fokus sofort wieder da.

Inoffizielles Projekt, nicht von Anthropic oder Discord. Windows und Linux.

## Installation

Ein Doppelklick auf die `.mcpb` funktioniert **nicht** — Claude Desktop meldet
für diese Endung keine Dateizuordnung an. Installiert wird über das
Entwickler-Menü, und das muss einmalig freigeschaltet werden.

1. **`.mcpb` aus den [Releases](../../releases) herunterladen.**

2. **Entwickler-Menü freischalten** mit dem Inhalt `{"allowDevTools": true}`:

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

3. **Claude Desktop komplett beenden** — unter Windows auch das Symbol im
   Infobereich neben der Uhr — und neu starten.

4. **Menüleiste öffnen** (Windows: einmal `Alt` drücken, sie ist ausgeblendet):
   **Entwickler → Erweiterungen → Erweiterung installieren…**

5. Die heruntergeladene `.mcpb` auswählen und die Rückfrage bestätigen.

Die Presence startet ab jetzt zusammen mit Claude Desktop. Deinstallieren geht
über Einstellungen → Erweiterungen; verweigert die Oberfläche das, hilft
`tools/remove_extension.ps1` bei geschlossener App.

Unter Linux werden zusätzlich
[Claude Desktop für Linux](https://code.claude.com/docs/en/desktop-linux)
(Beta, Ubuntu 22.04+ oder Debian 12+) und ein `python3` ab 3.9 vorausgesetzt —
beides bringt eine übliche Installation ohnehin mit. Dasselbe Paket dient
beiden Systemen.

Es wird nichts kompiliert und nichts installiert: das Paket enthält Pythons
offizielles *Embeddable Package* und ausschließlich reine Python-Bibliotheken.
Deshalb gibt es weder eine SmartScreen-Warnung noch typische
Virenscanner-Fehlalarme.

## Eigene Discord-Anwendung (optional)

Ohne weitere Angaben läuft alles über die mitgelieferte Anwendung — dann
erscheinen deren Name und Bild in deinem Profil. Für einen eigenen Namen und
ein eigenes Bild: im
[Developer Portal](https://discord.com/developers/applications)
*New Application* anlegen, unter *Rich Presence → Art Assets* ein Bild mit dem
Namen `logo` hochladen und die **Application ID** in den Einstellungen
eintragen. Der Asset-Name muss exakt mit `large_image_key` aus der
Konfiguration übereinstimmen, sonst zeigt Discord die Presence ohne Bild.
„Claude" ist als App-Name bei Discord gesperrt.

## Einstellungen

**Claude Desktop → Einstellungen → Erweiterungen → „Discord Presence for
Claude Desktop"**. Die Felder erzeugt Claude Desktop selbst aus dem Manifest —
eine eigene Oberfläche hat das Projekt bewusst nicht.

| Feld | Bedeutung |
|---|---|
| Discord Application ID | optional — leer lassen für die mitgelieferte Anwendung |
| Presence ausblenden nach | Minuten ohne Eingabe, bis die Presence verschwindet |
| Modell-Limit ausblenden nach | Minuten, bis ein abgelesener Wert als veraltet gilt |
| Abo-Bezeichnung | Notnagel; normalerweise liest sich das selbst aus |
| Text im Leerlauf | erste Zeile, solange kein Chat im Vordergrund ist |

Wer aus dem Quelltext läuft, bearbeitet stattdessen `config.json` im
Projektordner; dort gibt es deutlich mehr Stellschrauben als im Dialog.

Discord zeigt zwei Zeilen, aufgeteilt nach Tempo. Die **erste** zeigt ohne
Verzögerung, was Claude gerade tut — „Claude denkt nach", „Desktop Commander:
read_file" — und im Leerlauf den festen Text. Die **zweite** rotiert alle
20 Sekunden durch Sitzung, Auslastung und Abonnement; diese drei ändern sich
ohnehin nur im Minutentakt.

### Wo Konfiguration und Protokoll liegen

Normalerweise unter `%LOCALAPPDATA%\ClaudeDiscordPresence\` beziehungsweise
`~/.local/share/ClaudeDiscordPresence/`.

**Ausnahme Windows:** Claude Desktop startet Erweiterungen mit
`server.type: "python"` nicht mit der mitgelieferten Runtime, sondern mit dem
`python3` aus dem PATH. Ist das das Microsoft-Store-Python, bekommt es ein
umgeleitetes `%LOCALAPPDATA%` und die Dateien landen unter
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.12_*\LocalCache\Local\ClaudeDiscordPresence\`.
Wer dort ein Protokoll sucht, findet es eine Ebene tiefer. Der Prozess heißt
dann im Task-Manager `python3.12.exe` statt `ClaudeDiscordPresence.exe`.

## Was gelesen wird

Alles lokal. An Discord gehen nur Statustext, Modell beziehungsweise
Aktivität, Auslastung in Prozent und die Abo-Bezeichnung.

- **Claude-Fenster** über die Barrierefreiheitsschnittstelle des Systems
  (Windows UI Automation, Linux AT-SPI): Modellname und die Statuszeile am
  Eingabefeld. Nur dieses eine Fenster — kein globaler Hook, keine Tastatur-
  oder Mausaufzeichnung, kein Fokuswechsel.
- **Desktop Commander**: `~/.claude-server-commander/tool-history.jsonl`,
  ausschließlich das Feld `toolName`. Argumente und Ausgaben stehen in
  derselben Datei und werden bewusst ignoriert.
- **Claude Desktop**: Sitzungsdateien lokaler Cowork-Sessions und die
  Nutzungsdatei `plan-usage-history.json`. Übernommen werden nur Sitzungs-,
  Wochen- und Modell-Limits — der Balken für das Nutzungsguthaben und der
  ausgegebene Betrag bleiben ausdrücklich außen vor.
- Systemweit nur: läuft Claude, ist es im Vordergrund, wann war die letzte
  Eingabe. Zeitstempel und Fenstername, keine Inhalte.

**Chat-Titel werden gar nicht erst erhoben** — nicht abschaltbar, weil es dafür
keinen Schalter braucht. Was nicht gelesen wird, kann auch nicht versehentlich
im Profil landen.

**Es wird kein Anmelde-Token gelesen und kein Anthropic-Endpunkt aufgerufen.**
Anthropic untersagt seit Februar 2026 die Verwendung von OAuth-Token aus Free-,
Pro- oder Max-Konten in anderen Produkten; dieses Projekt hält sich davon
vollständig fern.

Zur Auslastung: 5-Stunden- und Wochenwert stehen in einer Datei, die Claude
Desktop selbst alle fünf Minuten fortschreibt. Das modellspezifische Wochenlimit
steht dort **nicht** — es wird nur abgelesen, während du das Nutzungsfenster
offen hast, altert danach sichtbar („Fable 99 % (vor 2 h)") und verschwindet
nach drei Stunden. Lieber keine Zahl als eine falsche.

## Linux

Vollständig unterstützt ab v1.4.0. Weil kein Weg zu Fokus und Leerlaufzeit
überall vorhanden ist, probiert `linuxdesktop.py` sechs gängige der Reihe nach
durch und behält den ersten, der antwortet; welche das sind und warum, steht in
[ARCHITEKTUR.md](ARCHITEKTUR.md#linux-im-einzelnen). Trägt keiner, bleibt die
Presence sichtbar, solange Claude läuft — sie schaltet dann nur nicht mehr auf
„abwesend".

Eine Bedingung stellt Chromium: Seiteninhalt veröffentlicht es nur, wenn ein
Bildschirmleser angemeldet ist. Der Daemon meldet deshalb beim Start einen an
(`ui_watcher.announce_screen_reader`) — das wirkt erst beim **nächsten Start
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
dir anders, trägst du ihn unter `process_names` ein — das Protokoll nennt bei
Nichterkennung stündlich alle gefundenen Kandidaten samt Pfad.

## Entwicklung

```bat
setup_venv.bat                   :: venv + config.json aus config.example.json
.venv\Scripts\python restart.py  :: Daemon neu starten
powershell -File build_mcpb.ps1  :: dist\*.mcpb bauen
```

Die eigene `config.json` bleibt bewusst untracked; Vorlage ist
`config.example.json`. **Achtung:** `make_default_config.py` erzeugt die
ausgelieferte Konfiguration aus der *lokalen* `config.json`. Neue Schlüssel
gehören dort eingetragen, sonst wirft der nächste Bau sie still wieder aus dem
Paket.

Der Daemon lässt sich auch ohne MCPB betreiben: `start_claude_rpc.vbs` startet
`claude_rpc.py` unsichtbar mit der Konfiguration aus `config.json`.

**Für den Betrieb aus dem Quelltext nicht das Microsoft-Store-Python
verwenden.** Store-Apps bekommen ein umgeleitetes `%APPDATA%`, dadurch sieht
das Skript den Ordner `%APPDATA%\Claude` nicht und alle lokalen Leser bleiben
stumm. `_check_env.py` prüft das. Als installierte Erweiterung entscheidet
Claude Desktop das leider selbst — siehe „Wo Konfiguration und Protokoll
liegen".

Der Build bricht ab, sobald eine Abhängigkeit eine `.pyd` oder `.dll`
mitbringt — das hält das Paket signaturfrei.

## Lizenz

MIT
