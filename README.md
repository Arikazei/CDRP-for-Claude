# Discord Presence für Claude Desktop

Zeigt in Discord an, woran du gerade mit Claude Desktop arbeitest: das Modell
des offenen Chats, was Claude gerade tut, deine Auslastung, dein Abonnement
und ein Timer. Die Presence verschwindet nach einstellbarer
Inaktivität und ist bei Fokus sofort wieder da.

Inoffizielles Projekt, nicht von Anthropic oder Discord. Windows only.

## Installation

1. **`.mcpb` aus den [Releases](../../releases) herunterladen** und per
   Doppelklick installieren.
2. Fertig. Die Presence startet ab jetzt zusammen mit Claude Desktop.

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
