"""Liest Abo und Auslastung aus dem Antigravity-Fenster.

Antigravity zeigt beides in "Einstellungen -> Models & Usage":

    Plan
      Your Plan:  Google AI Pro
    Gemini Models
      Weekly Limit Remaining        97%
      Five Hour Limit Remaining     92%
    Claude and GPT models
      Weekly Limit Remaining       100%
      Five Hour Limit Remaining    100%

Gelesen wird ausschliesslich dieser Abschnitt und ausschliesslich
Werte, die auf eine feste Form passen. Das ist kein Uebermass an
Vorsicht: derselbe Fensterbaum enthaelt den kompletten Editorinhalt --
gemessen 1313 Knoten mit ganzen Absaetzen offener Dateien. Nichts
davon darf in einen Prozess geraten, der nach Discord schreibt.

Deshalb hier drei harte Regeln:

1. Ohne den Knoten "Models & Usage" wird gar nicht erst gesucht.
2. Uebernommen werden nur Prozentzahlen der Form "97%" und ein
   Planname aus einer kurzen Positivliste von Zeichen.
3. Zwischen Ueberschrift und Wert wird in Dokumentreihenfolge
   gesucht, nicht im ganzen Baum. Die Werte von "Gemini Models" und
   "Claude and GPT models" sehen sonst gleich aus.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gemeinsam"))
import uia  # noqa: E402

ANKER = "Models & Usage"
ABSCHNITT_GEMINI = "Gemini Models"
ABSCHNITT_ANDERE = "Claude and GPT models"
LABEL_WOCHE = "Weekly Limit Remaining"
LABEL_5H = "Five Hour Limit Remaining"
LABEL_PLAN = "Your Plan:"

RE_PROZENT = re.compile(r"^(\d{1,3})\s?%$")
RE_PLAN = re.compile(r"^[A-Za-z0-9 ()×.+/-]{1,32}$")
# Das Modell steht in der Eingabezeile. Der Knopf dort traegt eine
# Beschriftung fuer Bildschirmleser, und die ist die beste Quelle, die
# es gibt: "Select model, current: Gemini 3.7 Flash High".
#
# Der sichtbare Text daneben ("Gemini 3.7 Flash") waere verlockender,
# steht aber als gewoehnlicher Textknoten im Baum -- und im selben Baum
# stehen auch Fliesstexte offener Dateien, in denen Modellnamen
# vorkommen. Gemessen: 'Gemini 3 Pro' und '"Gemini Advanced"' als
# Dokumenttext, beide vor der Eingabezeile. Ueber den Knopf kann das
# nicht passieren.
RE_MODELLKNOPF = re.compile(
    r"^(?:Select model, current|Modell auswählen, aktuell)\s*:\s*(.+)$")
RE_MODELLNAME = re.compile(r"^[A-Za-z0-9 .()-]{1,40}$")


def _wert_nach(flach, von, bis, label):
    """Erste Prozentzahl nach `label` innerhalb von [von, bis)."""
    try:
        stelle = next(i for i in range(von, bis) if flach[i][1] == label)
    except StopIteration:
        return None
    for i in range(stelle + 1, bis):
        treffer = RE_PROZENT.match(flach[i][1])
        if treffer:
            zahl = int(treffer.group(1))
            return zahl if 0 <= zahl <= 100 else None
    return None


def _index(flach, name, ab=0):
    return uia.erste_stelle(flach, (name,), ab)


def lies(fenster):
    """Gibt {"plan": str, "usage": {...}, "model": str} zurueck.

    Fehlende Angaben fehlen einfach. Ein leeres Ergebnis heisst: das
    Einstellungsfenster ist gerade nicht offen -- kein Fehler, nur
    nichts Neues.
    """
    flach = uia.flach(fenster)
    ergebnis = {}

    # Modell aus der Eingabezeile. Geht auch ohne offene Einstellungen.
    for art, name in flach:
        if art != "ButtonControl":
            continue
        treffer = RE_MODELLKNOPF.match(name)
        if treffer:
            wert = treffer.group(1).strip()
            if RE_MODELLNAME.match(wert):
                ergebnis["model"] = wert
            break

    anker = _index(flach, ANKER)
    if anker is None:
        return ergebnis

    # Plan: der erste kurze Text nach "Your Plan:", der wie ein Name
    # aussieht. Der Satz darunter ("You can upgrade to ...") faellt
    # durch die Laengengrenze der Positivliste.
    stelle = _index(flach, LABEL_PLAN, anker)
    if stelle is not None:
        for i in range(stelle + 1, min(stelle + 6, len(flach))):
            text = flach[i][1]
            if text and text != LABEL_PLAN and RE_PLAN.match(text):
                ergebnis["plan"] = text
                break

    # Auslastung nur aus dem Gemini-Abschnitt. Der Abschnitt darunter
    # gehoert zu Claude- und GPT-Modellen und wuerde sonst dieselben
    # Beschriftungen liefern.
    start = _index(flach, ABSCHNITT_GEMINI, anker)
    if start is None:
        return ergebnis
    ende = _index(flach, ABSCHNITT_ANDERE, start) or len(flach)

    usage = {}
    for schluessel, label in (("week", LABEL_WOCHE),
                              ("five_hour", LABEL_5H)):
        rest = _wert_nach(flach, start, ende, label)
        if rest is not None:
            # Antigravity zeigt "Remaining", der Vertrag will
            # "verbraucht". Ohne diese Zeile stuende in derselben
            # Presence-Zeile mal das eine, mal das andere.
            usage[schluessel] = 100 - rest
    if usage:
        ergebnis["usage"] = usage
    return ergebnis


def lies_alle(prozessnamen=("Antigravity.exe",)):
    """Ueber alle Fenster hinweg lesen; der erste Treffer je Feld gilt."""
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
