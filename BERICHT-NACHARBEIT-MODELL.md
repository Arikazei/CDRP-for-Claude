# Bericht: Nacharbeit Modellnamen und ein Muster

Stand: 6. September 2026, Commits 1e1daa1 und c67e0a5. Zusammen mit
b74214c, f866a8a und b4e4ed2 sind fuenf Commits nicht gepusht. Kein Tag,
kein Release.

## Nacharbeit 1: Modelle nach Regel

`beacons.modell_aus_slug(wert)` ist das Gegenstueck zur Claude-Regel: aus
`familie-version(-beiname)*` wird `FAMILIE-version Beiname`, die Familie
gross bei bis zu drei Buchstaben (GPT), sonst nur mit grossem Anfang;
Beinamen mit grossem Anfang; ein reiner Zahlenblock am Ende (Datumsstempel)
faellt weg.

| Bezeichner | Anzeige |
|---|---|
| `gpt-6-astra` | GPT-6 Astra |
| `gpt-5.6-sol` | GPT-5.6 Sol |
| `gpt-5.1-codex-max` | GPT-5.1 Codex Max |
| `gpt-5.6-sol-20260801` | GPT-5.6 Sol |
| `Astra 6`, `Gemini 3.7 Flash`, `GPT-5 (Preview)` | unveraendert (kein Bezeichner) |
| `o3`, `o4-mini` | unveraendert, ueber die Ausnahmeliste |

Ein Wert, der das Muster nicht besteht, bleibt `None`; daran hat sich
nichts geaendert.

**Entfallene Tabelleneintraege** in `codex_beacon.MODEL_LABELS`, weil die
Regel sie ohnehin richtig schreibt: gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna,
gpt-5.5, gpt-5.4, gpt-5.3-codex, gpt-5.2-codex, gpt-5.2, gpt-5.1-codex-max,
gpt-5.1-codex-mini, gpt-5.1-codex, gpt-5.1, gpt-5-codex-mini, gpt-5-codex,
gpt-5 -- fuenfzehn von siebzehn. Geblieben sind `o4-mini` und `o3`: die
schreiben sich klein, die Regel schriebe sie gross. Die Tabelle ist jetzt eine
Ausnahmeliste, und `model_label` prueft erst das Muster, dann die Ausnahmen,
dann die Regel.

**Antigravity, nachgesehen:** dort steht keine Tabelle mehr, und die Quellen
liefern lesbare Namen ("Gemini 3.8 Flash High" aus dem Modellknopf,
"Gemini 3 Pro" aus der Systemmeldung). Beide Wege laufen trotzdem durch
`modell_aus_slug`, das lesbare Namen unveraendert laesst -- kaeme dort einmal
ein Bezeichner an, gilt dieselbe Regel wie bei Codex.

## Nacharbeit 2: ein Muster, nicht fuenf

Die Muster wohnen jetzt genau einmal, in `beacons.py` neben `RE_SLUG`:

```
RE_NAME   = ^[A-Za-z0-9 .()+-]{1,32}$
RE_MODELL = ^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,39}$
```

`RE_MODELL` ist die Vereinigung der drei frueheren Fassungen: 40 Zeichen,
erstes Zeichen alphanumerisch, Klammern und Plus erlaubt. Was die drei
Produzenten real schreiben koennen, habe ich vorher nachgesehen: Claude
nimmt Modellnamen aus dem Fenster und aus Sitzungsdateien (`Fable 5.1`,
rohe Bezeichner nach demselben Muster), Codex das Ergebnis von
`model_label`, Antigravity Knopfbeschriftungen wie "Gemini 3.8 Flash High",
deren Fenstermuster bisher Klammern und 40 Zeichen zuliess. Nichts davon
faellt durch die Vereinigung; mit dem Schnitt (32 Zeichen, keine Klammern)
waere "GPT-5 (Preview)" beim Pruefer durchgefallen.

Importiert wird das Muster von:

- `claude_rpc.py` (`RE_MODELL_ROH = beacons.RE_MODELL`)
- `connectors/codex/codex_beacon.py` (ueber `beacons.modell_saeubern`)
- `connectors/antigravity/watcher.py`
- `connectors/antigravity/fenster.py` (`RE_MODELLNAME`, dazu `RE_PLAN`)
- `tools/validate_beacon.py` (`RE_SLUG`, `RE_NAME`, `RE_MODELL`)

`docs/SPEC-beacon-v1.md` beschreibt die beiden Muster in Worten und sagt, wo
sie wohnen, statt sie ein sechstes Mal abzuschreiben. Ein neuer Test
(`EinMusterNichtFuenf`) durchsucht alle Quelldateien nach `[A-Za-z0-9]`,
`A-Za-z0-9 .` und `A-Za-z0-9 _` und laesst nur `beacons.py` durch.

**display_name:** `beacons.py` hatte gar kein Muster, Pruefer und Vertrag
32 Zeichen. Jetzt `RE_NAME` in `beacons.py`; `pruefen` verwirft einen Beacon
mit unpassendem Namen (Pflichtfeld, fail closed), und `eigenen_schreiben`
faellt auf "Claude Desktop" zurueck, wenn der Name aus der Konfiguration das
Muster nicht besteht -- sonst verwuerfe der Pool den eigenen Beacon.

**Zweite Schleuse:** `pruefen` prueft jetzt auch `model`. Ein unbrauchbares
Modell kostet nur das Modell (`None`), nicht den Beacon. Vorher war der
Produzent die einzige Schleuse, obwohl der Vertrag den Master als zweite
beschreibt.

Nicht angefasst: `connectors/codex/fenster.py` hat ein eigenes Muster fuer
den Tarifnamen mit Umlauten (`Ä Ö Ü ä ö ü ß`), damit "Plus-Tarif" auf einem
deutschen System gelesen wird; `beacons.RE_PLAN` kennt keine Umlaute. Das
ist dieselbe Sorte Kopie, betrifft aber `plan`, nicht `model` oder
`display_name`, und war nicht Teil des Auftrags.

## Tests

100 gruen, vorher 92. Acht neue in `tools/test_beacons.py`:

- Modell mit Klammern besteht Sender (`pruefen`) und Pruefer (`pruefe_werte`)
- Modell mit 41 Zeichen faellt bei Sender, `modell_saeubern` und Pruefer weg; 40 besteht
- Modell mit Satzzeichen kostet nur das Modell, nicht den Beacon
- Anzeigename: Zeilenumbruch und 33 Zeichen verworfen, Klammern erlaubt
- eigener Beacon faellt bei unpassendem Konfigurationsnamen auf die Vorgabe zurueck
- Regel: gpt-6-astra, gpt-5.6-sol, gpt-5.1-codex-max, gpt-5, Grossschreibung, Datumsstempel
- kein Bezeichner bleibt unveraendert (Astra 6, Gemini 3.7 Flash, o3, GPT-5 (Preview))
- ein Muster, nicht fuenf (Suche ueber die Quelldateien)

Erweitert in `connectors/codex/test_codex_beacon.py`: `model_label` fuer
gpt-6-astra, gpt-5.1-codex-max, o3, o4-mini, o3 mit Datumsstempel, Klammern,
41 Zeichen.

Aufruf wie verlangt: `unittest discover -s tools` (85), Codex direkt (8),
`python -m unittest connectors.antigravity.test_watcher` (7).

**Nebenbefund, behoben (c67e0a5):** der Antigravity-Test war nicht
hermetisch. `AntigravityWatcher()` schreibt bei jeder verarbeiteten Zeile
einen Beacon in den echten Datenordner; nach meinem Testlauf um 23:20 lag
"Google Antigravity - running tests" als Beacon da -- aus dieser Sitzung im
Paketordner von Claude Desktop, ausserhalb des Containers waere es der echte
gewesen. Jetzt schreibt der Test wie der Codex-Test in einen Wegwerfordner;
die Schattenkopie ist entfernt.

## Nachpruefung

3. `tools/validate_beacon.py` gegen die echten Beacons, ausserhalb des
   Containers: `codex.json` OK, `claude.json` OK. `antigravity.json` gibt es
   nicht -- Antigravity lief nicht, und der Waechter loescht den Beacon beim
   Schliessen. Zwei von zwei vorhandenen gueltig.
4. Dienst und Waechter ueber eine geplante Aufgabe neu gestartet (23:21).
   Danach `codex.json`: `"model": "GPT-6 Astra"` (vorher `gpt-6-astra`), vom
   Waechter beim ersten Ruhe-Beacon durch `model_label` geschrieben.
   `tools/probe_rahmen.py` aus den echten Beacons, Karte 5:

   ```
   [codex] OpenAI Codex
           using Codex with GPT-6 Astra
   ```

   Das ist Zeile 2, wie der Sender sie baut. In Discord selbst habe ich nicht
   nachgesehen -- dazu fehlt mir der Blick auf dein Profil.

## Zwei Beobachtungen

a) `state.json` bewegt sich nicht: vor dem Neustart 21:58, 75 Sekunden nach
   dem Neustart immer noch 21:58, waehrend `sender.standalone.json` und
   `claude.json` sekuendlich frisch waren. Ursache, nachgelesen, nicht
   umgebaut: `publish_state()` wird nur am Ende des Zweigs aufgerufen, in
   dem Claude aktiv ist (Fenster im Vordergrund und Eingabe juenger als 90
   Sekunden). In den Zweigen "Claude laeuft nicht" und "Claude inaktiv"
   sendet `anzeigen()` die fremden Karten direkt und die Schleife springt
   mit `continue` vor `publish_state()` zurueck. Seit 21:58 warst du fuer den
   Sender nicht mehr aktiv an Claude, also blieb die Momentaufnahme stehen.
   Sendeweg und Beacons sind davon unberuehrt; `presence_status` zeigt
   solange den Stand von 21:58.
b) `sender.json` (30.08.) und `beacons\_probe.txt` (21.08.) sind entfernt,
   ausserhalb des Containers, ohne Codeaenderung.
