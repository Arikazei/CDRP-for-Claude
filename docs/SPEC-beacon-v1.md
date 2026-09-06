# SPEC: Beacon-Protokoll v1 (verbindlich)

Vertrag zwischen den **Produzenten** (Codex-Connector, Antigravity-Connector,
Claude-Daemon) und dem **Master** (dem Sender `claude_rpc.py` im Stamm
dieses Repos, der als einziger an Discord sendet).

Wer diesen Vertrag erfüllt, wird verdrahtet. Wer ihn nicht erfüllt, nicht.
`tools/validate_beacon.py` prüft ihn maschinell — Ergebnis `OK` ist
Abnahmebedingung.

---

## 1. Ablageort

Ein Beacon je Produzent, Dateiname = Client-Slug.

| System | Pfad |
|---|---|
| Windows | `%LOCALAPPDATA%\ClaudeDiscordPresence\beacons\<slug>.json` |
| Linux | `~/.local/share/ClaudeDiscordPresence/beacons/<slug>.json` |

Slugs v1: `codex`, `antigravity`, `claude`.
Regel: `^[a-z0-9_-]{1,32}$`, muss dem Feld `client` entsprechen.

Der Ordner `beacons/` wird vom Produzenten bei Bedarf angelegt
(`mkdir -p` / `os.makedirs(exist_ok=True)`).

### Achtung: `%LOCALAPPDATA%` ist unter Windows nicht verlaesslich

Gemessen auf diesem Rechner: ein Prozess, der in einem App-Container
laeuft (MSIX, Microsoft Store), bekommt `%LOCALAPPDATA%` still umgeleitet
nach `...\AppData\Local\Packages\<paket>\LocalCache\Local\`. Zwei
Produzenten koennen so in zwei verschiedenen Ordnern landen und einander
nie sehen — derselbe Fehler hat schon einmal Konfiguration und Protokoll
der bestehenden Erweiterung verschwinden lassen.

Verbindliche Aufloesung, in dieser Reihenfolge:

1. Umgebungsvariable `CLAUDE_RPC_DATA_DIR`, falls gesetzt
2. Windows: `%USERPROFILE%\AppData\Local\ClaudeDiscordPresence`
   — `USERPROFILE` wird **nicht** umgeleitet
3. Linux: `$XDG_DATA_HOME/ClaudeDiscordPresence`, sonst
   `~/.local/share/ClaudeDiscordPresence`

`%LOCALAPPDATA%` direkt zu benutzen ist ein Regelverstoss, auch wenn es
auf deinem Rechner zufaellig funktioniert.

## 2. Schreiben: ausschliesslich atomar

Nie in die Zieldatei hineinschreiben. Immer:

1. `<slug>.json.tmp` im **selben** Ordner schreiben, Datei schliessen
2. `os.replace(tmp, ziel)` bzw. `fs.renameSync(tmp, ziel)`

`os.replace` ist auf Windows und POSIX atomar. Ein anderer Weg wird
abgelehnt: der Master liest asynchron und wuerde sonst halbe Dateien sehen.

UTF-8 ohne BOM, `\n` als Zeilenende, Datei hoechstens 4096 Byte.

## 3. Schema

Genau diese Schluessel. Zusaetzliche Schluessel = ungueltig, der Master
verwirft die Datei (fail closed) und protokolliert das einmal.

```json
{
  "v": 1,
  "client": "codex",
  "display_name": "OpenAI Codex",
  "state": "working",
  "action": "editing",
  "model": "GPT-5.6 Sol",
  "session_start": 1786990000,
  "updated_at": 1786993157,
  "file_kind": "python"
}
```

| Feld | Typ | Regel |
|---|---|---|
| `v` | int | genau `1` |
| `client` | string | `^[a-z0-9_-]{1,32}$`, gleich dem Dateinamen |
| `display_name` | string | Muster `beacons.RE_NAME`: Buchstaben, Ziffern, Leerzeichen, `. ( ) + -`, hoechstens 32 Zeichen |
| `state` | string | `working` \| `waiting` \| `idle` |
| `action` | string | nur aus der Liste unten |
| `model` | string/null | Muster `beacons.RE_MODELL`: erstes Zeichen alphanumerisch, dann Buchstaben, Ziffern, Leerzeichen, `. _ ( ) + -`, hoechstens 40 Zeichen -- oder `null` |
| `session_start` | int/null | Unix-Sekunden, nicht Millisekunden |
| `updated_at` | int | Unix-Sekunden, hoechstens 5 s in der Zukunft |
| `file_kind` | string/null | nur aus der Liste unten, sonst `null` |

Alle Felder sind Pflicht.

Die Muster fuer `display_name` und `model` sind hier nur beschrieben, nicht
abgeschrieben: sie wohnen genau einmal in `beacons.py` (`RE_NAME`,
`RE_MODELL`), und Sender, Produzenten und `tools/validate_beacon.py`
importieren sie von dort. Wer das Muster aendert, aendert es an einer
Stelle. Nachtrag vom 06.09.2026: vorher standen fuenf Fassungen im Repo,
und Pruefer und Vertrag verwarfen Modelle, die die Produzenten gueltig
schreiben durften; seither gilt die Vereinigung (40 Zeichen, Klammern und
Plus erlaubt).

### Erlaubte `action`-Werte (abschliessend)

```
thinking          reading           editing
running_tests     running_command   web_search
waiting_approval  idle
```

Kein Freitext. Der Master uebersetzt diese Marken selbst in Anzeigetexte.
Ein Produzent, der eigene Formulierungen schickt, wird verworfen.

### Erlaubte `file_kind`-Werte (abschliessend)

```
python      javascript  typescript  markdown    json
yaml        html        css         shell       powershell
csharp      cpp         rust        go          java
sql         text        config      image       data
other
```

`file_kind` beschreibt die **Art** der bearbeiteten Datei, niemals ihren
Namen. Der Master macht daraus Zeile 1:

```
Google Antigravity · editing a Python file
OpenAI Codex · reading a Markdown file
```

Regeln:

- nur gesetzt, wenn `action` gleich `reading` oder `editing` ist,
  sonst zwingend `null`
- abgeleitet **ausschliesslich** aus der Dateiendung ueber eine feste
  Tabelle im Connector, nie aus dem Dateinamen oder Pfadanteilen
- unbekannte Endung -> `other`
- der Pfad darf dafuer im Connector kurz gelesen werden, muss aber sofort
  verworfen werden: er wird nicht gespeichert, nicht protokolliert und
  nicht weitergereicht. Was den Connector verlaesst, ist eine der 21 Marken
  oben -- mehr existiert an dieser Stelle nicht.

**Hier sitzt der Datenschutz.** Weil `action` und `file_kind` geschlossene
Listen sind, kann strukturell kein Pfad, kein Dateiname, kein Befehl, keine
Suchanfrage und kein Prompt in die Presence gelangen. Das ist kein Filter,
den man vergessen kann, sondern eine Typbeschraenkung.

## 4. Wann geschrieben wird

- bei **jedem** Wechsel von `state` oder `action`, sofort
- zusaetzlich als Herzschlag **mindestens alle 20 s**, solange
  `state != "idle"` -- auch wenn sich nichts geaendert hat
- beim Sitzungsende einmal mit `state: "idle"`, `action: "idle"`

Haeufiger als **einmal pro Sekunde** darf nicht geschrieben werden.
Der Master drosselt Discord selbst; die Beacon-Datei ist billig, aber ein
Schreibsturm macht das Lesen unnoetig fehleranfaellig.

## 5. Verfall (macht der Master, nicht der Produzent)

Ein Produzent, der abstuerzt, hinterlaesst eine alte Datei. Der Master
stuft sie schrittweise zurueck, statt sie sofort zu glauben oder sofort
zu verwerfen:

| Alter von `updated_at` | Wertung |
|---|---|
| < 45 s | wie geschrieben |
| 45 s bis 180 s | hoechstens `waiting` |
| 180 s bis 900 s | `idle` |
| > 900 s | ignoriert, Datei wird nicht geloescht |

Deshalb darf ein Produzent bei einem langen Denkzug ruhig 60 s schweigen:
er faellt dann auf `waiting` zurueck statt zu verschwinden. Ein eigener
Herzschlag-Prozess ist ausdruecklich **nicht** erwuenscht.

## 6. Was der Master daraus macht (zur Information)

- **Rahmenbesitzer**: der Client mit dem juengsten `updated_at` unter denen
  mit `state == working`. Gibt es keinen, der juengste mit `waiting`.
  Sonst Leerlauf-Rahmen.
- **Rahmensperre**: `details` und `state` stammen **immer** vom selben
  Client. Mischzustaende sind ausgeschlossen.
- Zeile 1 = `<display_name> · <Aktionstext>`
- Zeile 2 rotiert **nur** mit Fakten desselben Clients, Intervall >= 15 s
- **Kein Client-Karussell.** Der Rahmen wechselt nur, wenn die Aktivitaet
  wirklich wandert -- nicht im Takt.
- Discord wird hoechstens **alle 15 s** aktualisiert. Das ist die
  dokumentierte Grenze; wer sie unterschreitet, bekommt die Presence nicht
  gedrosselt, sondern **geleert**.

## 7. Ausdruecklich nicht in v1

- ~~**Kontingente/Quota fuer Codex und Antigravity.**~~ **Widerrufen am
  21.08.2026, siehe Abschnitt 8.** Der Satz "es gibt keine erlaubte
  lokale Quelle" war falsch. Er stuetzte sich darauf, dass in
  Zustandsdateien und Protokollen nichts steht -- was stimmt -- und
  uebersah die naheliegendste Quelle: das Fenster der Anwendung selbst.
  Antigravity zeigt Plan und Limits unter
  "Einstellungen -> Models & Usage", vollstaendig ueber die
  Barrierefreiheitsschnittstelle lesbar. Genau so liest Claude sein
  eigenes Nutzungsfenster seit jeher.
- **Dateinamen.** Entschieden: nie. Es gibt nur `file_kind`, die Art der
  Datei. Ein Name wie `kuendigung_mueller.docx` gehoert nicht in einen
  fremden Discord-Server.
- Symbole/Badges je Client. Kommt in v2, wenn v1 stabil laeuft.

## 8. Nachtrag 1.1: `plan` und `usage` (21.08.2026)

Zwei **freiwillige** Zusatzfelder. Ein Beacon ohne sie bleibt gueltig;
ein Produzent, der sie nicht liefern kann, liefert sie einfach nicht.

```json
{
  "plan": "Google AI Pro",
  "usage": { "five_hour": 8, "week": 3 }
}
```

### `plan`

Die nackte Abo-Bezeichnung, sonst nichts. Der Master setzt sie in seine
eigene Vorlage ("Abonnement: {plan}"); ein Produzent formuliert nie
selbst.

- hoechstens 32 Zeichen
- nur `A-Z a-z 0-9 Leerzeichen ( ) × . + / -`
- alles andere wird **verworfen** -- nicht gekuerzt, nicht ersetzt

Der Grund fuer die enge Positivliste: das ist die erste Stelle im
Protokoll, an der Text eines Produzenten in die Presence gelangen kann.
Ohne Zeilenumbrueche und Sonderzeichen laesst sich daraus kein zweiter
Satz bauen.

### `usage`

Keine Texte, sondern ganze Zahlen. Formuliert wird erst im Master.

- feste Schluessel `five_hour` und `week`, beide freiwillig
- ganze Zahlen von 0 bis 100
- **Semantik ist VERBRAUCHT, nicht verbleibend**

Der letzte Punkt ist der wichtigste. Antigravity zeigt "Weekly Limit
Remaining 97%", Claude zeigt den verbrauchten Anteil. Stuende in
derselben Presence-Zeile mal das eine, mal das andere, faellt es
niemandem auf, und beide Zahlen waeren wertlos. Der Produzent rechnet
um: `verbraucht = 100 - verbleibend`.

Ein unbrauchbares Zusatzfeld verwirft nur sich selbst, nicht den ganzen
Beacon. Ein Tippfehler im Abo-Namen soll nicht die gesamte Anzeige des
Clients kosten.

### Woher die Werte kommen duerfen

Aus dem **Fenster der eigenen Anwendung**, ueber die
Barrierefreiheitsschnittstelle des Systems -- und sonst nirgendwoher.
Weiterhin gesperrt bleiben: Anbieter-APIs, Netzzugriffe jeder Art,
Zugangstoken, Cookies, Schluesselbunde.

Beim Lesen des Fensters gilt eine harte Regel: **feste Positivliste,
nie freier Baumtext.** Der Fensterbaum von Antigravity enthaelt den
kompletten Editorinhalt -- gemessen 1313 Knoten mit ganzen Absaetzen
offener Dateien. Uebernommen werden nur Werte, die auf eine feste Form
passen (`^\d{1,3}%$` fuer Prozente, die Positivliste oben fuer den
Plan), und nur aus dem Abschnitt zwischen den bekannten Ueberschriften.

### Verfall

Beide Angaben stehen nur im Einstellungsfenster und altern, sobald es
zu ist. Der Produzent merkt sich, wann er sie gelesen hat, und laesst
sie nach einer einstellbaren Zeit wieder aus dem Beacon fallen
(Vorgabe 180 Minuten, wie `ui_limits.max_age_minutes` bei Claude).
Lieber keine Zahl als eine von gestern.
