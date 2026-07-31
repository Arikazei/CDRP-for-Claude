# Discord Presence für Claude Desktop

Zeigt in Discord an, woran du gerade mit Claude Desktop arbeitest: das Modell
des offenen Chats, was Claude gerade tut, deine Auslastung, dein Abonnement
und ein Timer. Die Presence verschwindet nach einstellbarer
Inaktivität und ist bei Fokus sofort wieder da.

Inoffizielles Projekt, nicht von Anthropic oder Discord. Windows und Linux.

## Linux

Läuft ab v1.2.0 auch unter Linux, mit Einschränkungen. Voraussetzung ist
[Claude Desktop für Linux](https://code.claude.com/docs/en/desktop-linux)
(Beta, Ubuntu 22.04+ oder Debian 12+) und ein `python3` ab 3.9 — beides
bringt eine übliche Installation ohnehin mit. Dasselbe Paket dient beiden
Systemen; unter Windows wird eine eigene Runtime mitgeliefert, unter Linux
das System-Python verwendet.

**Was funktioniert:** laufende Tätigkeit aus dem Werkzeugverlauf, Modell aus
den Sitzungsdateien, Auslastung aus der Nutzungsdatei, Abo aus der
Einstellung — also die zweite Zeile vollständig.

**Fokus und Leerlaufzeit** ab v1.3.0. Weil unter Linux keiner dieser Wege
überall vorhanden ist, probiert `linuxdesktop.py` der Reihe nach alle
gängigen durch und behält den ersten, der antwortet:

| Weg | wo er trägt |
|---|---|
| Wayland `ext-idle-notify-v1` | Plasma 6, GNOME 45+, Sway, Hyprland |
| GNOME Mutter `IdleMonitor` | GNOME unter X11 und Wayland |
| `org.freedesktop.ScreenSaver` | KDE unter X11, XFCE, MATE |
| X11 MIT-SCREEN-SAVER | jede reine X11-Sitzung |
| systemd-logind `IdleSinceHint` | wo die Sitzungsverwaltung ihn pflegt |
| Sperrbildschirm an/aus | grober Notnagel, nur zwei Zustände |

Der Fokus läuft über **AT-SPI**, die Barrierefreiheitsschnittstelle. Das ist
der einzige desktopübergreifende Weg: KDE und GNOME geben das aktive Fenster
aus Sicherheitsgründen nicht heraus, AT-SPI dagegen ist ein
freedesktop-Standard über D-Bus und damit unabhängig vom Fenstersystem.
Trägt keiner der Wege, bleibt die Presence sichtbar, solange Claude läuft —
sie schaltet dann nur nicht mehr auf „abwesend".

**Was noch fehlt:** Das Auslesen des Claude-Fensters gibt es nur unter
Windows. Damit fehlen unter Linux das Modell reiner Cloud-Chats, die
Live-Statuszeile und das modellspezifische Limit. Die Grundlage dafür steht
mit `atspi_knoten()` bereits; was fehlt, ist der Parser für die Knotennamen.

Was dein Rechner hergibt, sagt dir das Diagnoseprogramm aus dem Release:

```bash
chmod +x atspi-dump && ./atspi-dump
```

Erkannt wird der Prozess `claude-desktop`. Der nackte Name `claude` gehört
der Kommandozeilenfassung und ist bewusst ausgeschlossen. Heißt der
Hauptprozess bei dir anders, trägst du ihn unter `process_names` ein — das
Log nennt bei Nichterkennung stündlich alle gefundenen Kandidaten samt Pfad.

## Installation

Ein Doppelklick auf die `.mcpb` funktioniert **nicht** — Claude Desktop
meldet für diese Endung keine Dateizuordnung an. Installiert wird über das
Entwickler-Menü der App, und das muss einmalig freigeschaltet werden.

1. **`.mcpb` aus den [Releases](../../releases) herunterladen.**

2. **Entwickler-Menü freischalten.** Lege diese Datei an:

   | System | Pfad |
   |---|---|
   | Windows | `%APPDATA%\Claude\developer_settings.json` |
   | Linux | `~/.config/Claude/developer_settings.json` |

   Inhalt:

   ```json
   {"allowDevTools": true}
   ```

   **Ohne BOM speichern.** Schreibt der Editor eine Byte-Order-Mark an den
   Anfang, startet Claude mit „Entwicklereinstellungen konnten nicht geladen
   werden". Unter Windows also nicht mit PowerShells `Set-Content -Encoding
   UTF8` erzeugen, sondern etwa so:

   ```powershell
   [System.IO.File]::WriteAllText("$env:APPDATA\Claude\developer_settings.json",
     '{"allowDevTools": true}', (New-Object System.Text.UTF8Encoding $false))
   ```

3. **Claude Desktop komplett beenden** — unter Windows auch das Symbol im
   Infobereich neben der Uhr — und neu starten.

4. **Menüleiste öffnen** (Windows: einmal `Alt` drücken, sie ist
   ausgeblendet) und wählen:
   **Entwickler → Erweiterungen → Erweiterung installieren…**

5. Die heruntergeladene `.mcpb` auswählen und die Rückfrage bestätigen.

Die Presence startet ab jetzt zusammen mit Claude Desktop. Deinstallieren
geht über Einstellungen → Erweiterungen; falls die Oberfläche das verweigert,
hilft `tools/remove_extension.ps1` bei geschlossener App.

Ohne weitere Angaben läuft alles über die mitgelieferte Discord-Anwendung —
dann erscheinen deren Name und Bild in deinem Profil. Für einen eigenen Namen
und ein eigenes Bild: im [Developer Portal](https://discord.com/developers/applications)
*New Application* anlegen, unter *Rich Presence → Art Assets* ein Bild mit dem
Namen `logo` hochladen und die **Application ID** in den Einstellungen
eintragen. Der Asset-Name muss exakt mit `large_image_key` aus der
Konfiguration übereinstimmen, sonst zeigt Discord die Presence ohne Bild.
„Claude" ist als App-Name bei Discord gesperrt.

Es wird nichts kompiliert und nichts installiert: das Paket enthält Pythons
offizielles *Embeddable Package* (`python.exe` von der Python Software
Foundation signiert) und ausschließlich reine Python-Bibliotheken. Deshalb
gibt es weder eine SmartScreen-Warnung noch typische Virenscanner-Fehlalarme.

## Einstellungen

Nach der Installation als `.mcpb`: **Claude Desktop → Einstellungen →
Erweiterungen → „Discord Presence for Claude Desktop"**. Die Felder unten
erzeugt Claude Desktop selbst aus dem Manifest — eine eigene Oberfläche hat
das Projekt bewusst nicht. Die daraus erzeugte Konfiguration liegt unter
`%LOCALAPPDATA%\ClaudeDiscordPresence\config.json`.

Wer aus dem Quelltext läuft, bearbeitet stattdessen `config.json` im
Projektordner; dort gibt es deutlich mehr Stellschrauben als im Dialog.

Der laufende Dienst heißt im Task-Manager **ClaudeDiscordPresence.exe**.

| Feld | Bedeutung |
|---|---|
| Discord Application ID | optional — leer lassen für die mitgelieferte Anwendung |
| Presence ausblenden nach | Minuten ohne Eingabe, bis die Presence verschwindet |
| Modell-Limit ausblenden nach | Minuten, bis ein abgelesener Wert als veraltet gilt |
| Abo-Bezeichnung | Notnagel; normalerweise liest sich das selbst aus |
| Text im Leerlauf | erste Zeile, solange kein Chat im Vordergrund ist |

Discord zeigt zwei Zeilen, aufgeteilt nach Tempo. Die **erste** zeigt ohne
Verzögerung, was Claude gerade tut — „Claude denkt nach", „Desktop Commander:
read_file", „Websuche wird verwendet" — und im Leerlauf den festen Text. Die
**zweite** rotiert alle 20 Sekunden durch die Sitzung („using cowork with
Opus 5"), die Auslastung und das Abonnement; diese drei ändern sich ohnehin
nur im Minutentakt.

## Was gelesen wird

Alles lokal, nichts davon verlässt deinen Rechner außer den drei Feldern, die
an Discord gehen (Statustext, Modell/Aktivität, Auslastung in Prozent):

- **Claude-Fenster** über die Windows-UI-Automation: Modellname und die
  Statuszeile über dem Eingabefeld. Nur dieses eine Fenster wird gelesen, per
  Klassenname und Titel ausgewählt — kein globaler Hook, keine Tastatur- oder
  Mausaufzeichnung, kein Fokuswechsel.
- **Desktop Commander**: `~/.claude-server-commander/tool-history.jsonl`,
  ausschließlich das Feld `toolName`. Argumente und Ausgaben stehen in
  derselben Datei und werden bewusst ignoriert.
- **Claude Desktop**: Sitzungsdateien lokaler Cowork-Sessions und die
  Nutzungsdatei `plan-usage-history.json`. Aus dem Nutzungsfenster werden nur
  Sitzungs-, Wochen- und Modell-Limits übernommen — der Balken für das
  Nutzungsguthaben und der ausgegebene Betrag bleiben ausdrücklich außen vor.
- Systemweit nur: läuft `claude.exe`, ist es im Vordergrund, wann war die
  letzte Eingabe. Zeitstempel und Fenstername, keine Inhalte.

**Chat-Titel werden gar nicht erst erhoben** — nicht abschaltbar, weil es dafür
keinen Schalter braucht. Was nicht gelesen wird, kann auch nicht versehentlich
im Profil landen.

## Woher die Auslastung kommt

5-Stunden- und Wochenwert stehen in einer Datei, die Claude Desktop selbst
alle fünf Minuten fortschreibt — die sind immer aktuell.

Das modellspezifische Wochenlimit steht dort **nicht**. Es existiert lokal
nur, solange du das Nutzungsfenster von Claude geöffnet hast. Genau dann liest
das Programm es im Vorbeigehen mit und merkt es sich mit Zeitstempel: bis
30 Minuten ohne Vermerk, danach mit Altersangabe („Fable 99 % (vor 2 h)"),
nach drei Stunden verschwindet es. Lieber keine Zahl als eine falsche.

**Es wird kein Anmelde-Token gelesen und kein Anthropic-Endpunkt aufgerufen.**
Anthropic untersagt seit Februar 2026 die Verwendung von OAuth-Token aus
Free-, Pro- oder Max-Konten in anderen Produkten; dieses Projekt hält sich
davon vollständig fern und liest ausschließlich, was auf deinem Bildschirm
und auf deiner Platte ohnehin steht.

## Entwicklung

```bat
setup_venv.bat                   :: venv + config.json aus config.example.json
.venv\Scripts\python restart.py  :: Daemon neu starten
powershell -File build_mcpb.ps1  :: dist\*.mcpb bauen
```

Die eigene `config.json` bleibt bewusst untracked — Vorlage ist
`config.example.json`, die beim Build aus der neutralen Fassung erzeugt wird.

Der Daemon lässt sich auch ohne MCPB betreiben: `start_claude_rpc.vbs` startet
`claude_rpc.py` unsichtbar mit der Konfiguration aus `config.json`.

**Wichtig:** nicht das Microsoft-Store-Python verwenden. Store-Apps bekommen
ein umgeleitetes `%APPDATA%`, dadurch sieht das Skript den Ordner
`%APPDATA%\Claude` nicht und alle lokalen Leser bleiben stumm.
`_check_env.py` prüft das.

Der Build bricht ab, sobald eine Abhängigkeit eine `.pyd` oder `.dll`
mitbringt — das hält das Paket signaturfrei.

## Lizenz

MIT
