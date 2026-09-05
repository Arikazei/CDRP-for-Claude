"""Liest Abo und Auslastung aus dem Fenster der ChatGPT-App.

Die App zeigt beides unter "Einstellungen -> Nutzung und Abrechnung":

    Dein Tarif
      Plus-Tarif
    Allgemeine Nutzungsgrenzen
      Woechentliches Nutzungslimit
      65 % uebrig

Gemessen am 21.08.2026: 99 Knoten, klare Dokumentreihenfolge. Ein
Fuenf-Stunden-Limit gibt es dort nicht, nur das Wochenlimit.

Zwei Dinge unterscheiden diesen Leser von dem fuer Antigravity:

Die Oberflaeche ist uebersetzt. Beschriftungen werden deshalb in
mehreren Sprachen gesucht -- wer nur die englischen kennt, liest auf
einem deutschen System nichts und meldet trotzdem Erfolg.

Der Wert steht als "65 % uebrig" da, also VERBLEIBEND. Uebernommen
wird er nur, wenn das auch dransteht. Fehlt das Wort, wird nichts
gemeldet: eine Zahl, bei der unklar ist, ob sie verbraucht oder uebrig
bedeutet, ist schlimmer als keine.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gemeinsam"))
import uia  # noqa: E402

ANKER = ("Nutzung und Abrechnung", "Usage and billing", "Usage & billing",
         "Billing", "Abrechnung")
LABEL_PLAN = ("Dein Tarif", "Your plan", "Your Plan", "Tarif", "Plan")
LABEL_WOCHE = ("Wöchentliches Nutzungslimit", "Weekly usage limit",
               "Weekly limit", "Wochenlimit")
GRENZEN = ("Allgemeine Nutzungsgrenzen", "General usage limits",
           "Usage limits", "Nutzungsgrenzen")

# "65 % uebrig", "65% left", "65 % remaining". Das Wort ist Pflicht.
RE_UEBRIG = re.compile(
    r"^(\d{1,3})\s?%\s*(übrig|uebrig|left|remaining|verbleibend)$", re.I)
RE_PLAN = re.compile(r"^[A-Za-zÄÖÜäöüß0-9 ()×.+/-]{1,32}$")


def lies(fenster):
    """Gibt {"plan": str, "usage": {"week": int}} zurueck."""
    flach = uia.flach(fenster)
    _index = uia.erste_stelle
    anker = _index(flach, ANKER)
    if anker is None:
        return {}
    ergebnis = {}

    stelle = _index(flach, LABEL_PLAN, anker)
    if stelle is not None:
        for i in range(stelle + 1, min(stelle + 5, len(flach))):
            text = flach[i][1]
            if text and text not in LABEL_PLAN and RE_PLAN.match(text):
                ergebnis["plan"] = text
                break

    # Erst ab dem Abschnitt mit den Nutzungsgrenzen suchen. Darueber
    # steht Werbetext wie "Bis zu 40 % Rabatt" -- eine Prozentzahl, die
    # mit Auslastung nichts zu tun hat.
    start = _index(flach, GRENZEN, anker)
    if start is None:
        return ergebnis
    stelle = _index(flach, LABEL_WOCHE, start)
    if stelle is None:
        return ergebnis
    for i in range(stelle + 1, min(stelle + 8, len(flach))):
        treffer = RE_UEBRIG.match(flach[i][1])
        if treffer:
            uebrig = int(treffer.group(1))
            if 0 <= uebrig <= 100:
                # Vertrag will verbraucht, die App zeigt uebrig.
                ergebnis["usage"] = {"week": 100 - uebrig}
            break
    return ergebnis


def lies_alle(prozessnamen=("ChatGPT.exe",)):
    """Ueber alle Fenster der App hinweg lesen."""
    gesamt = {}
    for fenster in uia.fenster_von(prozessnamen):
        try:
            teil = lies(fenster)
        except Exception:
            continue
        for schluessel, wert in teil.items():
            gesamt.setdefault(schluessel, wert)
    return gesamt


if __name__ == "__main__":
    import json
    print(json.dumps(lies_alle(), ensure_ascii=False, indent=2))
