# Übergabe: Linux-Fassung fertigstellen

Hallo — du bekommst hier ein Projekt, das unter Windows fertig läuft und
unter Linux zu etwa drei Vierteln. Dieses Dokument sagt dir, was gemessen
ist, was fehlt, und woran du erkennst, dass du fertig bist. Ziel ist, dass
du in einem Rutsch arbeiten kannst, ohne für jede Kleinigkeit nachfragen
zu müssen.

Repo: <https://github.com/Arikazei/CDRP-for-Claude>

---

## 1. Worum es geht

Ein Daemon zeigt in Discord an, woran in Claude Desktop gerade gearbeitet
wird — als „Rich Presence". Zwei Zeilen:

| Zeile | Inhalt | Taktung |
|---|---|---|
| 1 | laufende Tätigkeit („bearbeitet Code", „führt Befehle aus") | schnell |
| 2 | Sitzung/Modell, Auslastung, Abo | langsam, rotierend |

Ausgeliefert wird das als Claude-Desktop-Erweiterung (`.mcpb`). Claude
Desktop startet darin einen MCP-Server, der wiederum den Presence-Daemon
im selben Prozess laufen lässt.

**Was bewusst nicht passiert:** Chatinhalte, Chattitel und Dateipfade
werden nirgends erhoben. Es gibt keinen Schalter dafür — was nicht erhoben
wird, kann auch nicht versehentlich in einer öffentlichen Presence landen.
Ebenso wird die Anthropic-API **nicht** angefragt; das Auslesen des
OAuth-Tokens ist nach Anthropics Bedingungen untersagt. Alle Werte kommen
aus lokalen Dateien oder aus dem Fenster selbst.

---

## 2. Stand unter Linux — was gemessen ist

Auf deinem Rechner (Plasma 6, Wayland) wurde mit `atspi-dump` Folgendes
festgestellt:

| Sache | Stand |
|---|---|
| Prozesserkennung `claude-desktop` | läuft |
| Zeile 2 (Modell, Auslastung, Abo aus lokalen Dateien) | läuft |
| Leerlaufmessung | läuft, über Wayland `ext-idle-notify-v1` **Fassung 2** |
| Barrierefreiheitsbrücke einschaltbar | ja, `org.a11y.Status.IsEnabled` |
| Claude im AT-SPI-Baum | ja, aber **nur 4 Knoten** = Fenstergerüst ohne Inhalt |
| Fokuserkennung über AT-SPI | ungeprüft (siehe Aufgabe 3) |
| Zeile 1 aus dem Fenster (Live-Status, Modell in Cloud-Chats, Limits) | **fehlt** |

Zwei Befunde, die du kennen musst, weil sie viel Zeit gekostet haben:

1. **`org.freedesktop.ScreenSaver.GetSessionIdleTime` ist unter Plasma mit
   Wayland tot** („is not supported on this platform"). Deshalb die Kette in
   `linuxdesktop.py`, die sechs Wege durchprobiert.
2. **`get_idle_notification` meldet bei dir nie Leerlauf**, weil eine
   Anwendung dauerhaft eine Leerlaufsperre hält (VR-Kram, Browser mit Ton).
   Fassung 2 des Protokolls kennt `get_input_idle_notification`, das solche
   Sperren ignoriert und nur echte Eingaben zählt. Das ist eingebaut und
   nachgewiesen: `nur Eingaben: 8,2 s` gegen `mit Sperren: keine Meldung`.

---

## 3. Aufbau des Projekts

| Datei | Aufgabe |
|---|---|
| `claude_rpc.py` | der Daemon: alle Beobachter-Module und die Hauptschleife |
| `hostplatform.py` | alles Betriebssystemabhängige, eine Schnittstelle für beide |
| `linuxdesktop.py` | Linux-Desktop: Leerlauf, Fokus, AT-SPI, Barrierefreiheit |
| `mcpb/manifest.json` | Erweiterungsbeschreibung, Einstellungen, Startbefehl |
| `mcpb/server/main.py` | MCP-Server von Hand, startet den Daemon |
| `build_mcpb.ps1` | baut das `.mcpb` (läuft nur unter Windows) |
| `tools/atspi_dump.py` | das Diagnoseprogramm, das du schon kennst |
| `tools/build_atspi_dump.sh` | packt es zur eigenständigen Datei |

Die Beobachter in `claude_rpc.py` sind bewusst voneinander unabhängig:
fällt einer aus, liefern die anderen weiter. `UIWatcher` ist derjenige, der
unter Linux noch fehlt.

---

## 4. Entwicklungsaufbau

Zum Entwickeln brauchst du **kein** `.mcpb`. Der Daemon läuft eigenständig:

```bash
git clone https://github.com/Arikazei/CDRP-for-Claude
cd CDRP-for-Claude
python3 -m venv .venv && . .venv/bin/activate
pip install pypresence jeepney

cp config.example.json config.json
# client_id eintragen (fragt Marco, oder eigene Discord-Anwendung anlegen)

CLAUDE_RPC_CONFIG=$PWD/config.json CLAUDE_RPC_LOG=/tmp/rpc.log python3 claude_rpc.py
```

Das Protokoll steht in `/tmp/rpc.log` und ist die wichtigste Rückmeldung —
der Daemon schreibt nichts auf die Konsole.

Für eine eigene Discord-Anwendung: <https://discord.com/developers> →
neue Anwendung → die Anwendungs-ID ist die `client_id`. Der Name der
Anwendung erscheint bei allen als „Spielt …".

Diagnoseprogramm neu bauen, wenn du daran etwas änderst:

```bash
bash tools/build_atspi_dump.sh     # Ergebnis: dist/atspi-dump
```

---

## 5. Deine Aufgaben

### Aufgabe 1 — Renderer-Barrierefreiheit zuverlässig anschalten

**Problem:** Claude taucht im AT-SPI-Baum auf, aber nur mit vier Knoten.
Chromium veröffentlicht das Fenstergerüst, den Seiteninhalt aber erst, wenn
es einen Grund dafür sieht. Ohne Inhalt gibt es nichts zu parsen, also
hängt alles Weitere daran.

Die aktuelle Fassung von `atspi-dump` probiert schon einen Weg
(`ScreenReaderEnabled` setzen). Lauf ihn einmal und schau, ob die Knotenzahl
steigt.

**Zu klären:**

- Reicht `ScreenReaderEnabled=true` zur Laufzeit, oder muss Claude neu
  starten, nachdem der Schalter an ist?
- Falls Neustart nötig: reicht ein normaler Neustart bei aktivem Schalter,
  oder braucht es `claude-desktop --force-renderer-accessibility`?
- Falls das Flag nötig ist: schreib eine kurze Anleitung, wie man es
  dauerhaft setzt (`.desktop`-Datei nach `~/.local/share/applications/`
  kopieren und `Exec=` ergänzen) — als Abschnitt in `README.md`.

**Fertig, wenn:** ein Aufruf von `ld.atspi_knoten("claude")` mehrere hundert
bis tausend Knoten liefert und darunter ein Knoten mit Rolle `document web`
oder ähnlich ist.

---

### Aufgabe 2 — Linux-UIWatcher (das Hauptstück)

Gegenstück zu `UIWatcher` in `claude_rpc.py`, der unter Windows über UI
Automation liest. Deine Fassung liest über AT-SPI. Das Rohmaterial liefert
`linuxdesktop.atspi_knoten()` bereits als flache Liste `(tiefe, rolle, name)`.

**Was der Windows-Watcher tut** — dein Pendant soll dasselbe liefern:

Er läuft den Baum ab, sammelt `(Steuerelementtyp, Name)` und wertet aus:

| gesucht | Windows-Erkennung | Ergebnisfeld |
|---|---|---|
| Stopp-Knopf sichtbar | `ButtonControl`, Name in `["antwort stoppen", "stop response", …]` | `busy` |
| Modell | `ButtonControl`, Name beginnt mit `Modell:` / `Model:`, darin `(Fable\|Opus\|Sonnet\|Haiku)` | `model` |
| Eingabefeld | `EditControl`, Name passt auf `(Anfrage an Claude\|Nachricht\|Message Claude\|Reply to Claude)` | Anker |
| Statuszeile | `TextControl` **oberhalb des Eingabefeldes**, höchstens 12 Knoten davor, ≤ 80 Zeichen, endet auf `…` | `status` |
| Limits | siehe `_read_limits`, Positivliste von Beschriftungen | `limits` |

**Der Anker ist wichtig, nicht optional.** Ohne ihn passt auch Text aus dem
Chatverlauf: ein Chat, in dem jemand „Desktop Commander wird verwendet"
geschrieben hat, hat die Presence dauerhaft falsch beschriftet. Deshalb wird
nur zwischen „12 Knoten vor dem Eingabefeld" und dem Eingabefeld gesucht,
und nur solange `busy` gilt.

**Bei den Limits gilt eine Positivliste, keine Negativliste.** Im
Nutzungsfenster steht neben den Limitbalken auch ein Guthaben in Euro. Das
darf unter keinen Umständen in die Presence geraten. Es werden deshalb nur
ausdrücklich bekannte Beschriftungen übernommen — schau dir `_read_limits`
an, bevor du dort etwas änderst.

**Schnittstelle, die du erfüllen musst.** `claude_rpc.py` ruft auf dem
Watcher auf:

```python
ui.refresh()   -> dict; wird alle refresh_seconds neu erhoben, sonst gecacht
ui.status()    -> str oder None   # Live-Statuszeile, z. B. "bearbeitet Code"
ui.info()      -> str oder None   # Text aus template, z. B. "using cowork with Opus 4.8"
ui.busy        # bzw. data["busy"]
```

Der Rückgabewert von `refresh()` geht zusätzlich an `limits.update(...)`.

**Vorgehensvorschlag:** bau keinen zweiten Watcher. Erweitere `UIWatcher` so,
dass `_scan()` je nach System entweder den Windows- oder den Linux-Weg
nimmt und **dieselbe Liste `nodes` als `(rolle, name)`** erzeugt. Die
gesamte Auswertung danach bleibt dann gemeinsam. Rollen heißen unter AT-SPI
anders (`push button` statt `ButtonControl`, `text`/`label` statt
`TextControl`, `entry` statt `EditControl`) — eine Übersetzungstabelle an
einer Stelle reicht.

**Fertig, wenn:** bei laufender Antwort in Claude eine sinnvolle Statuszeile
im Protokoll steht und in Discord in Zeile 1 erscheint; und wenn ein
geöffnetes Nutzungsfenster die Limits in Zeile 2 bringt.

---

### Aufgabe 3 — Fokuserkennung bestätigen

`linuxdesktop.claude_im_vordergrund()` fragt über AT-SPI, ob eines von
Claudes Fenstern den Zustand `active` hat. Ungeprüft ist, ob KDE diesen
Zustand überhaupt pflegt.

Der Dump hat dafür eine Gegenprobe: er beobachtet 15 Sekunden lang jede
Sekunde und gibt `...JJJJJ....` aus. Klick währenddessen ins Claude-Fenster
und wieder weg.

- Kommt kein einziges `J`, obwohl du geklickt hast, stimmt entweder die
  Zustandsmaske nicht (`STATE_ACTIVE`, Bit 1 im ersten Wort — nachrechnen)
  oder KDE meldet den Zustand nur auf dem Fenster selbst statt auf der
  Anwendung. Dann eine Ebene tiefer suchen.
- Trägt es gar nicht, dann `FOCUS_SUPPORTED` unter Linux auf `False` und
  einen Satz ins README, warum.

Gemeint ist übrigens der **Tastaturfokus**, nicht die Sichtbarkeit. Wenn du
den Dump im Terminal startest, ist das Terminal fokussiert — „nein" ist
dann richtig.

---

### Aufgabe 4 — Ende-zu-Ende, mit der echten Erweiterung

Bisher hat unter Linux niemand die fertige Erweiterung installiert.

1. `claude-discord-presence-*.mcpb` aus dem neuesten Release laden.
2. In Claude Desktop: `~/.config/Claude/developer_settings.json` anlegen mit
   `{"allowDevTools": true}` — **ohne BOM**, sonst weigert sich Claude
   wortlos. Danach Menü *Hilfe → Entwickler → Erweiterung installieren*.
3. Client-ID in den Einstellungen der Erweiterung eintragen.
4. Prüfen: erscheint die Presence in Discord? Steht im Protokoll unter
   `~/.local/share/ClaudeDiscordPresence/` etwas Auffälliges?

Wenn der Weg unter Linux anders aussieht als beschrieben: **README
korrigieren**. Das ist ausdrücklich Teil der Aufgabe, nicht Beiwerk.

---

## 6. Hausregeln

Diese vier Punkte sind nicht verhandelbar, alles andere ist Geschmackssache:

1. **Keine kompilierten Abhängigkeiten.** Alles muss reines Python sein.
   Der Build bricht ab, wenn eine `.so`, `.pyd` oder `.dll` ins Paket
   gerät. Deshalb `jeepney` statt `dbus-python`, deshalb ist das
   Wayland-Protokoll von Hand gesprochen. Wenn du eine Bibliothek brauchst,
   die kompiliert werden muss, such einen anderen Weg oder frag vorher.
2. **Keine Chatinhalte, keine Chattitel, keine Dateipfade** in der Presence.
   Auch nicht abschaltbar hinter einer Einstellung.
3. **Keine Anfragen an die Anthropic-API**, kein Auslesen von Tokens.
4. **Quelltext in ASCII**, Umlaute als `ae`/`oe`/`ue`. Zeilenenden LF
   (`.gitattributes` erzwingt das für `*.sh` und `atspi_dump.py`).
   Kommentare auf Deutsch, wie im Rest des Projekts.

Kommentare erklären das **Warum**, nicht das Was. Wenn du eine halbe Stunde
gebraucht hast, um herauszufinden, dass ein D-Bus-Fehler eine gültige
Nachricht und keine Ausnahme ist, dann gehört genau dieser Satz als
Kommentar dorthin.

---

## 7. Wie du zurückgibst

Fork und Pull Request, damit Marco die Kontrolle behält:

```bash
gh repo fork Arikazei/CDRP-for-Claude --clone
git switch -c linux-uiwatcher
# arbeiten, in sinnvollen Schritten committen
gh pr create --fill
```

In die Beschreibung des Pull Requests gehören:

- die vollständige Ausgabe von `./atspi-dump` nach deinen Änderungen,
- ein Auszug aus `/tmp/rpc.log` mit einer echten Statuszeile,
- was du **nicht** hinbekommen hast, mit Begründung — das ist genauso
  wertvoll wie das, was läuft.

Falls dir ein Fork zu umständlich ist, kann Marco dich stattdessen als
Mitarbeiter am Repo eintragen; sag ihm einfach Bescheid.

---

## 8. Fallstricke, die schon Zeit gekostet haben

- Eine **D-Bus-Fehlerantwort ist eine gültige Nachricht**, keine Ausnahme.
  Wer nur `try/except` schreibt, reicht den Fehlertext als Nutzdaten weiter
  — im Diagnoseprogramm stand deshalb einmal `IsEnabled = h`, das zweite
  Zeichen von „The name org.a11y.Bus …". Prüf `message_type`.
- Der nackte Prozessname `claude` gehört der **Kommandozeilenfassung**
  (`/opt/claude-code/bin/claude`), nicht der Desktop-App. Er ist bewusst
  aus der Erkennung ausgeschlossen.
- Das Wayland-Leerlaufprotokoll **liefert keine Zeit**. Man meldet eine
  Schwelle an und wird benachrichtigt. Deshalb muss `idle_configure()`
  aufgerufen werden, bevor zum ersten Mal gemessen wird.
- `dist/` ist in `.gitignore`. Gebaute Dateien gehören an den Release, nicht
  in die Historie.

---

## 9. Wenn du nicht weiterkommst

Schreib die Frage so auf, dass sie ohne Rückfrage beantwortbar ist: was du
versucht hast, was herauskam, was du erwartet hättest. Am hilfreichsten ist
immer die vollständige Ausgabe von `./atspi-dump` plus der passende
Ausschnitt aus dem Protokoll.

Viel Erfolg — der schwierige Teil (Leerlauf unter Wayland) liegt hinter
uns, der Rest ist Fleißarbeit am Baum.
