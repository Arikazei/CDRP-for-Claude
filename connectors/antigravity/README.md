# Antigravity-Connector

Produzent fuer Google Antigravity gemaess
[docs/SPEC-beacon-v1.md](../../docs/SPEC-beacon-v1.md). Ein Waechter
(`watcher.py`), der dauerhaft laeuft: er liest das Transkript der laufenden
Sitzung und schreibt `beacons/antigravity.json`. Er verbindet sich weder mit
Discord noch mit einer Google-Schnittstelle. Ohne ihn fehlt Antigravity in
der Presence ganz.

## Voraussetzungen

- Python 3.8 oder neuer, nur Standardbibliothek. Fuer Plan, Limits und
  Modell aus dem Fenster unter Windows zusaetzlich `uiautomation` (steht in
  `requirements.txt`); fehlt es, laeuft der Waechter ohne diese Angaben.
- Google Antigravity. Der Waechter findet das Transkript unter
  `~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript.jsonl`
  und nimmt das juengste nach Aenderungszeit.

## Start

`standalone/install.ps1` legt den Autostart-Eintrag
`DiscordRP-Antigravity.vbs` an, `standalone/install.sh` den Dienst
`claude-discord-presence-antigravity`. Von Hand:

```text
python connectors/antigravity/watcher.py
```

## Was der Waechter meldet

| Beobachtung | Beacon |
|---|---|
| Antigravity laeuft nicht | Beacon geloescht -- sofort weg, nicht erst nach 15 Minuten |
| `USER_INPUT` im Transkript | `working / thinking` |
| `view_file` | `working / reading`, Dateiart aus der Endung |
| `write_to_file`, `replace_file_content`, `multi_replace_file_content` | `working / editing`, Dateiart aus der Endung |
| `run_command` | `running_tests`, wenn der Befehl nach einem Testlauf aussieht, sonst `running_command` |
| `search_web`, `read_url_content` | `working / web_search` |
| `ask_question` | `waiting / waiting_approval` |
| Antwort ohne Werkzeug, oder 30 Sekunden Stille | `waiting / idle` |
| 3 Minuten Stille | `idle / idle`, Herzschlag alle 60 Sekunden |

Bei Arbeit schlaegt das Herz alle 5 Sekunden. Aus dem Fenster (nur Windows,
nur solange "Einstellungen -> Models & Usage" offen ist): Plan, Wochen- und
5-Stunden-Limit der Gemini-Modelle, umgerechnet auf *verbraucht*, und das
Modell aus der Beschriftung des Modellknopfs in der Eingabezeile. Die
Auslastung altert nach 3 Stunden aus dem Beacon, der Plan nach 30 Tagen.

## Datenschutz

1. **Positivliste.** Aus dem Transkript werden nur `type`, der Name des
   ersten Werkzeugaufrufs und die Endung seines Pfadarguments gelesen.
   `content`, `thinking`, Prompts und Antworten werden nicht angefasst.
   Einzige Ausnahme: Systemmeldungen zur Modellwahl, aus denen ein
   Modellname aus einer festen Liste uebernommen wird.
2. **Dateiart statt Dateiname.** Der Pfad wird nur auf seine Endung
   angesehen und sofort verworfen; nach aussen geht eine von 21 Marken.
3. **Fenster nur nach festem Muster.** Der Fensterbaum enthaelt den ganzen
   Editorinhalt; uebernommen wird nur, was auf `^\d{1,3}%$` oder die kurze
   Positivliste des Plannamens passt, und nur zwischen den bekannten
   Ueberschriften.
4. **Atomar geschrieben** (`.tmp` und `os.replace`), kein Netzzugriff.

## Kontrolle

```text
python tools/validate_beacon.py antigravity
python tools/validate_beacon.py antigravity --watch 300
python -m unittest connectors/antigravity/test_watcher.py
```
