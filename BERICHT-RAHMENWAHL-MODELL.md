# Bericht: Rahmenwahl und Modellerkennung

Stand: 6. September 2026, Commits b74214c und f866a8a. Lokal committet,
nichts gepusht, kein Tag, kein Release.

## Geaendert

### Fehler 1, Rahmenwahl (`beacons.py`, `claude_rpc.py`)

- `arbeitet(eintrag)`: Arbeit heisst `state == working` **oder**
  `action == waiting_approval`. Die Rueckfrage an den Nutzer zaehlt als
  Arbeit, auch ohne Vorgeschichte.
- `aktive(eintraege, jetzt=None, gedaechtnis=None)`: merkt sich je Client,
  wann er zuletzt gearbeitet hat. Wer danach `waiting` meldet, bleibt fuer
  `NACHLAUF = 25` Sekunden in der Menge. Die Frist beginnt erst nach echter
  Arbeit, wird durch neue Arbeit verlaengert, laeuft ohne neues Ereignis ab
  und endet bei `idle` sofort. Eintraege verschwundener oder abgelaufener
  Clients werden bei jedem Aufruf aus dem Gedaechtnis entfernt; Tests
  bekommen ein eigenes Woerterbuch mit.
- Rueckgabe sind Kopien mit `aktiv=True`; `karten()` nimmt dieses Zeichen
  fuer Zaehler und Abzeichen, damit der Zaehler in der Nachlauffrist nicht
  fuer 25 Sekunden verschwindet und dann wiederkommt.
- `anzeigen()` in `claude_rpc.py` uebergibt die Uhrzeit des Durchlaufs.

Unveraendert: die Reihenfolge (nach Client-Namen), die volle Runde durch alle
offenen Clients, wenn niemand arbeitet, und die Verfallsleiter des Pools.

### Fehler 2, Modellerkennung

- `connectors/codex/codex_beacon.py`: `RE_MODELL` ist das Muster der
  Claude-Seite (`^[A-Za-z0-9][A-Za-z0-9 ._-]{1,39}$`). `model_label()` prueft
  erst das Muster, dann verschoenert `MODEL_LABELS` bekannte Namen, alles
  andere wird unveraendert durchgereicht. Ein gelieferter Modellwert gilt
  immer: `if "model" in payload: state["model"] = model_label(...)` -- ein
  verworfener Wert setzt `None`, der alte Wert bleibt nie stehen. Nur eine
  Nutzlast ganz ohne Modellfeld laesst den letzten Stand. `normalized_previous`
  prueft den gespeicherten Zustand mit derselben Funktion.
- `connectors/codex/watcher.py`: der Ruhe-Beacon und das Nachschreiben
  waehrend langer Zuege laufen ebenfalls durch `model_label`.
- `connectors/antigravity/watcher.py`: dieselbe Konstruktion stand dort
  (drei feste Namen, alter Wert blieb). `parse_modell_name` nimmt jetzt den
  Zielnamen nach ` to `, schneidet Denkstufe `(High)` und den Rahmen der
  Systemmeldung `<...>` ab und prueft gegen dasselbe Muster; kein Treffer
  setzt `aktuelles_modell` auf `None`. Der Fensterleser war schon vorher
  musterbasiert und blieb unveraendert.
- Doku: ARCHITEKTUR (Rahmen und Karten, Codex, Antigravity), README,
  beide Connector-READMEs.

## Tests

92 gruen, vorher 76. Sechzehn neue:

`tools/test_beacons.py` (Klasse Karussell):
- ein Arbeiter, ein Untaetiger -> nur der Arbeiter
- zwei Arbeiter -> beide, feste Reihenfolge (bestand, auf eigenes Gedaechtnis umgestellt)
- keiner arbeitet -> aktive Menge leer, `karten()` liefert alle offenen
- working -> waiting: bleibt bei `NACHLAUF` Sekunden, faellt bei `NACHLAUF + 1` heraus, Gedaechtnis ist danach leer
- Nachlauf beginnt erst nach echter Arbeit
- Leerlauf beendet den Nachlauf sofort
- neue Arbeit verlaengert den Nachlauf
- waiting_approval zaehlt als aktiv, Karte zeigt "waiting for approval" mit Zaehler
- Zaehler bleibt in der Nachlauffrist
- Wartender ohne Vorgeschichte zaehlt nicht; Wartender verdraengt keinen Arbeitenden (bestanden, umgestellt)

`connectors/codex/test_codex_beacon.py`:
- unbekanntes Modell ("Astra 6", "astra-6-preview") wird durchgereicht
- Tabelle verschoenert bekannte Modelle weiterhin
- Modellwert mit Sonderzeichen -> `None`, nicht der alte Wert; `None` in der Nutzlast -> `None`
- Ereignis ohne Modellfeld laesst das Modell stehen
- gespeicherter Zustand mit `<synthetic>` wird beim Einlesen zu `None`
- Musterregeln von `model_label` (Bindestrich am Anfang, 41 Zeichen, Ausrufezeichen, Zahl, `None`)

`connectors/antigravity/test_watcher.py`:
- Systemmeldung mit "Astra 6" und mit "(Max)." wird richtig gelesen, Pfad und 50 Zeichen verworfen
- unlesbare Modellwahl loescht den alten Wert

## Live-Nachweis

**Wiedergabe der Aufzeichnung vom 06.09. (18:41 bis 19:21)** durch die neue
`aktive()`, Zeile fuer Zeile mit den aufgezeichneten Zustaenden und Altern:
302 Zeilen, Karussell alt 173, neu 141. Alle zwoelf Karussell-Momente waehrend
der drei Codex-Aufgaben -- Genehmigungsfragen um 18:44:12, 18:45:26, 18:55:31
und die `waiting/idle`-Luecken nach dem Zugende -- bleiben jetzt bei `codex`.
Die uebrigen Abweichungen sind Claudes eigene Nachlauffrist nach seiner
Arbeitsphase (18:42:22 bis 18:42:37, 18:54:07 bis 18:54:22): 25 Sekunden,
dann laeuft sie ab. Genau der Ablauf, den 1.6.2 nicht hatte.

**Live um 19:05 bis 19:09**, alles ausserhalb des App-Containers ueber
geplante Aufgaben; Dienst und Waechter vorher mit dem neuen Code neu
gestartet. Claude Desktop stand die ganze Zeit auf `waiting/thinking`. Drei
`codex exec`-Aufgaben; die dritte mit `--approve-for-me` und einem Schreibziel
ausserhalb der Sandbox, damit Codex eine Freigabe verlangt (`hook:
PermissionRequest` in der Ausgabe). Parallel liefen zwei Aufzeichner: deiner
von 18:41 mit dem alten Code und meiner mit dem neuen, beide in dieselbe
Datei. Ausschnitt, entdoppelt:

```
19:08:58  RAHMEN=codex                claude=waiting/thinking  codex=working/thinking(1s)
19:09:04  RAHMEN=codex                claude=waiting/thinking  codex=working/thinking(7s)
19:09:06  RAHMEN=codex                claude=waiting/thinking  codex=waiting/waiting_approval(1s)   neuer Code
19:09:06  RAHMEN=(alle, Karussell)    claude=waiting/thinking  codex=waiting/waiting_approval(1s)   alter Code
19:09:09  RAHMEN=(alle, Karussell)    claude=waiting/thinking  codex=waiting/waiting_approval(4s)   alter Code
19:09:09  RAHMEN=codex                claude=waiting/thinking  codex=waiting/waiting_approval(4s)   neuer Code
19:09:10  RAHMEN=codex                claude=waiting/thinking  codex=working/thinking(1s)
19:09:13  RAHMEN=(alle, Karussell)    claude=waiting/thinking  codex=idle/idle(1s)                  Sitzungsende
```

Mit dem neuen Code blieb RAHMEN von der ersten Arbeit bis zum Sitzungsende
durchgehend `codex`, auch waehrend der Genehmigungsfrage; der alte Code sprang
genau dort ins Karussell. Nach `SessionEnd` (`idle`) endet die Frist sofort,
und die volle Runde ist richtig. Dasselbe Bild bei den Aufgaben 1 und 2.

**Modell:** `codex.json` (ueber `\\localhost\c$`) nennt seit dem Neustart
`gpt-6-astra`, den Modellnamen, den die CLI meldet -- statt wochenlang
"GPT-5.6 Sol". Die Tabelle kennt diesen Namen nicht und reicht ihn
unveraendert durch; wer "GPT-6 Astra" lesen will, traegt eine Zeile in
`MODEL_LABELS` ein, das ist jetzt reine Kosmetik.

**Grenze des Live-Tests:** `codex exec` beendet die Sitzung direkt nach
`Stop`, der Beacon springt also von `working` auf `idle` und nicht wie in der
App auf `waiting/idle`. Die Luecke nach dem Zugende liess sich deshalb nur in
der Wiedergabe zeigen, die Genehmigungsfrage live.

## Aufgeraeumt

`_aufzeichnung.py` und `_aufzeichnung.log` sind entfernt, ebenso die
Testdateien von Codex (`_codex_test.txt` im Arbeitsordner und unter
`C:\Users\Public`) und meine Hilfsskripte. Beide Aufzeichner sind beendet.
Dienst und Waechter laufen mit dem neuen Code ausserhalb des Containers.

## Offen

- `docs/SPEC-beacon-v1.md` und `tools/validate_beacon.py` erlauben fuer
  `model` weiterhin `^[A-Za-z0-9 ._()+-]{1,32}$`. Das neue Muster laesst 40
  Zeichen zu und keine Klammern. Fuer heutige Namen passt beides; ein Name
  zwischen 33 und 40 Zeichen bestuende den Validator nicht. Soll der Vertrag
  auf 40 nachziehen?
- `beacons.pruefen` im Sender prueft das Feld `model` gar nicht -- die
  Produzenten sind die einzige Schleuse. Eine Pruefung mit demselben Muster
  im Sender waere die zweite Schleuse, die der Vertrag beschreibt.
