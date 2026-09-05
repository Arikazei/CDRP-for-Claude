"""Fenster finden und flach lesen -- fuer alle Connectoren dasselbe.

Warum ein eigenes Modul und nicht ein Import beim Nachbarn: beide
Connectoren hatten eine Datei namens fenster.py. Importiert der eine
"fenster", bekommt er sich selbst, weil der Name in sys.modules schon
belegt ist. Der Fehler war lautlos -- der Waechter fing die Ausnahme,
schaltete den Fensterblick dauerhaft ab und meldete nichts.

Hier steht deshalb nur, was wirklich fuer beide gilt. Was Antigravity
und die ChatGPT-App unterscheidet -- Beschriftungen, Reihenfolge,
Sprache -- bleibt beim jeweiligen Connector.
"""
import subprocess
import time

MAX_KNOTEN = 20000
BUDGET = 8.0


def flach(fenster, budget=BUDGET, max_knoten=MAX_KNOTEN):
    """Fensterbaum in Dokumentreihenfolge als Liste (art, name).

    Der Stapel bekommt die Kinder umgedreht, damit die Reihenfolge der
    Anzeige erhalten bleibt. Darauf beruht die ganze Auswertung: die
    Beschriftung "Weekly Limit Remaining" kommt mehrfach vor, und nur
    ihre Stelle im Ablauf sagt, zu welchem Abschnitt sie gehoert.
    """
    ende = time.time() + budget
    ergebnis = []
    stapel = [(fenster, 0)]
    while stapel and len(ergebnis) < max_knoten and time.time() < ende:
        node, tiefe = stapel.pop()
        try:
            name = node.Name
            art = node.ControlTypeName
        except Exception:
            continue
        if isinstance(name, str) and name and len(name) <= 200:
            ergebnis.append((art, name.strip()))
        if tiefe < 45:
            try:
                kinder = node.GetChildren()
            except Exception:
                kinder = []
            for kind in reversed(kinder):
                stapel.append((kind, tiefe + 1))
    return ergebnis


def prozess_ids(prozessnamen):
    ids = set()
    for name in prozessnamen:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
              "ForEach-Object { $_.ProcessId }" % name)
        try:
            roh = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=20,
                creationflags=0x08000000).stdout
        except Exception:
            continue
        ids.update(int(z) for z in roh.split() if z.strip().isdigit())
    return ids


def fenster_von(prozessnamen):
    """Alle sichtbaren Fenster der genannten Prozesse.

    uiautomation wird erst hier importiert: es zieht COM nach, und ein
    Waechter soll auch dort starten, wo das nicht traegt.
    """
    ids = prozess_ids(prozessnamen)
    if not ids:
        return []
    try:
        import uiautomation as auto
    except Exception:
        return []
    auto.SetGlobalSearchTimeout(2)
    treffer = []
    try:
        for fenster in auto.GetRootControl().GetChildren():
            try:
                if fenster.ProcessId in ids:
                    treffer.append(fenster)
            except Exception:
                continue
    except Exception:
        return []
    return treffer


def erste_stelle(flache, namen, ab=0):
    """Erste Stelle ab `ab`, deren Name genau einem der Namen entspricht."""
    for i in range(ab, len(flache)):
        if flache[i][1] in namen:
            return i
    return None


def pfad_anmelden():
    """Diesen Ordner in sys.path legen, damit `import uia` traegt."""
    import os
    import sys
    hier = os.path.dirname(os.path.abspath(__file__))
    if hier not in sys.path:
        sys.path.insert(0, hier)
