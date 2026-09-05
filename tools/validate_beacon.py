"""Prueft eine Beacon-Datei gegen SPEC-beacon-v1.md.

Aufruf:
    python validate_beacon.py codex
    python validate_beacon.py C:\\pfad\\zu\\codex.json
    python validate_beacon.py codex --watch 120

--watch liest 120 s lang viermal je Sekunde und prueft zusaetzlich:
Atomizitaet (nie eine halbe Datei), Herzschlag (<= 20 s), Verfall.

Rueckgabe 0 = OK, 1 = Regelverstoss. Ohne "OK" keine Abnahme.
"""
import json
import os
import re
import sys
import time

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
if WURZEL not in sys.path:
    sys.path.insert(0, WURZEL)
import beacons  # noqa: E402

AKTIONEN = {
    "thinking", "reading", "editing", "running_tests",
    "running_command", "web_search", "waiting_approval", "idle",
}
ZUSTAENDE = {"working", "waiting", "idle"}
DATEIARTEN = {
    "python", "javascript", "typescript", "markdown", "json",
    "yaml", "html", "css", "shell", "powershell",
    "csharp", "cpp", "rust", "go", "java",
    "sql", "text", "config", "image", "data", "other",
}
FELDER = {
    "v", "client", "display_name", "state", "action",
    "model", "session_start", "updated_at", "file_kind",
}
# Nachtrag 1.1: freiwillig -- aber wenn vorhanden, dann nach Regel.
ZUSATZFELDER = {"plan", "usage"}
RE_SLUG = re.compile(r"^[a-z0-9_-]{1,32}$")
RE_NAME = re.compile(r"^[A-Za-z0-9 .()+-]{1,32}$")
RE_MODELL = re.compile(r"^[A-Za-z0-9 ._()+-]{1,32}$")


def beacon_ordner():
    """Dieselbe Regel wie bei den Produzenten, siehe
    beacons.produzenten_datenordner: bewusst nicht ueber LOCALAPPDATA, das
    wird in App-Containern (MSIX/Store) still umgeleitet."""
    return str(beacons.produzenten_datenordner() / "beacons")


def pfad_aufloesen(arg):
    if os.sep in arg or arg.endswith(".json"):
        return arg
    return os.path.join(beacon_ordner(), arg + ".json")


def pruefe(daten, slug):
    """Gibt eine Liste von Verstoessen zurueck, leer heisst sauber."""
    f = []
    unbekannt = set(daten) - FELDER - ZUSATZFELDER
    if unbekannt:
        f.append("unbekannte Schluessel: %s" % ", ".join(sorted(unbekannt)))
    fehlt = FELDER - set(daten)
    if fehlt:
        f.append("fehlende Schluessel: %s" % ", ".join(sorted(fehlt)))
    if daten.get("v") != 1:
        f.append("v ist nicht 1: %r" % daten.get("v"))
    if not RE_SLUG.match(str(daten.get("client", ""))):
        f.append("client verletzt das Muster: %r" % daten.get("client"))
    elif slug and daten["client"] != slug:
        f.append("client %r passt nicht zum Dateinamen %r"
                 % (daten["client"], slug))
    return f


def pruefe_werte(daten):
    f = []
    if not RE_NAME.match(str(daten.get("display_name", ""))):
        f.append("display_name verletzt das Muster: %r"
                 % daten.get("display_name"))
    if daten.get("state") not in ZUSTAENDE:
        f.append("state unzulaessig: %r" % daten.get("state"))
    if daten.get("action") not in AKTIONEN:
        f.append("action unzulaessig: %r" % daten.get("action"))
    modell = daten.get("model")
    if modell is not None and not RE_MODELL.match(str(modell)):
        f.append("model verletzt das Muster: %r" % modell)
    art = daten.get("file_kind")
    if art is not None and art not in DATEIARTEN:
        f.append("file_kind unzulaessig: %r" % art)
    if art is not None and daten.get("action") not in ("reading", "editing"):
        f.append("file_kind gesetzt, obwohl action %r ist -- erlaubt nur "
                 "bei reading/editing" % daten.get("action"))
    for feld in ("updated_at", "session_start"):
        wert = daten.get(feld)
        if feld == "session_start" and wert is None:
            continue
        if not isinstance(wert, int) or isinstance(wert, bool):
            f.append("%s ist kein int: %r" % (feld, wert))
        elif wert > 10 ** 11:
            f.append("%s sieht nach Millisekunden aus: %r" % (feld, wert))
    jetzt = time.time()
    aktualisiert = daten.get("updated_at")
    if isinstance(aktualisiert, int) and aktualisiert > jetzt + 5:
        f.append("updated_at liegt in der Zukunft")
    # Zusatzfelder aus Nachtrag 1.1, geprueft mit denselben Regeln, die
    # der Sender anwendet -- sonst meldet der Pruefer OK, und der Sender
    # verwirft das Feld trotzdem.
    if "plan" in daten and beacons.plan_saeubern(daten["plan"]) is None:
        f.append("plan verletzt das Muster: %r" % daten.get("plan"))
    if "usage" in daten:
        nutzung = daten["usage"]
        if not isinstance(nutzung, dict):
            f.append("usage ist kein Objekt: %r" % nutzung)
        else:
            fremd = set(nutzung) - set(beacons.USAGE_SCHLUESSEL)
            if fremd:
                f.append("usage mit unbekannten Schluesseln: %s"
                         % ", ".join(sorted(fremd)))
            for schluessel in beacons.USAGE_SCHLUESSEL:
                if schluessel not in nutzung:
                    continue
                wert = nutzung[schluessel]
                if (isinstance(wert, bool) or not isinstance(wert, int)
                        or not 0 <= wert <= 100):
                    f.append("usage.%s ist keine ganze Zahl von 0 bis "
                             "100: %r" % (schluessel, wert))
    return f


def einmal(pfad):
    slug = os.path.splitext(os.path.basename(pfad))[0]
    if not os.path.exists(pfad):
        return ["Datei fehlt: %s" % pfad], None
    roh = open(pfad, "rb").read()
    if len(roh) > 4096:
        return ["Datei groesser als 4096 Byte: %d" % len(roh)], None
    if roh.startswith(b"\xef\xbb\xbf"):
        return ["Datei hat eine BOM"], None
    try:
        daten = json.loads(roh.decode("utf-8"))
    except Exception as exc:
        return ["kein gueltiges JSON (%s)" % exc], None
    if not isinstance(daten, dict):
        return ["oberste Ebene ist kein Objekt"], None
    return pruefe(daten, slug) + pruefe_werte(daten), daten


def beobachte(pfad, sekunden):
    """Liest oft und schnell -- deckt nicht-atomares Schreiben auf."""
    f = []
    ende = time.time() + sekunden
    letzte = None
    zeitpunkte = []
    lesungen = kaputt = 0
    while time.time() < ende:
        fehler, daten = einmal(pfad)
        lesungen += 1
        if fehler:
            kaputt += 1
            for e in fehler:
                if e not in f:
                    f.append("waehrend --watch: " + e)
        elif daten and daten.get("updated_at") != letzte:
            letzte = daten["updated_at"]
            zeitpunkte.append(letzte)
        time.sleep(0.25)
    return f, lesungen, kaputt, zeitpunkte


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pfad = pfad_aufloesen(sys.argv[1])
    print("Datei:", pfad)

    if "--watch" in sys.argv:
        dauer = int(sys.argv[sys.argv.index("--watch") + 1])
        f, lesungen, kaputt, zeitpunkte = beobachte(pfad, dauer)
        print("Lesungen: %d, davon fehlerhaft: %d" % (lesungen, kaputt))
        if kaputt:
            f.append("nicht atomar geschrieben oder zeitweise ungueltig "
                     "(%d von %d Lesungen)" % (kaputt, lesungen))
        if len(zeitpunkte) >= 2:
            luecken = [b - a for a, b in zip(zeitpunkte, zeitpunkte[1:])]
            print("Herzschlaege: %d, groesste Luecke: %d s"
                  % (len(zeitpunkte), max(luecken)))
            if max(luecken) > 20:
                f.append("Herzschlag-Luecke von %d s (erlaubt sind 20 s)"
                         % max(luecken))
        else:
            f.append("zu wenige Aktualisierungen in %d s gesehen" % dauer)
    else:
        f, daten = einmal(pfad)
        if daten:
            print("Inhalt:", json.dumps(daten, ensure_ascii=False))

    if f:
        print("\nFEHLER:")
        for e in f:
            print("  -", e)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
