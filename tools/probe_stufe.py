"""Zeigt Modell und Denkstufe aller Claude-Code-Sitzungen.

Gedacht zum Nachmessen, wenn sich an Claude Code etwas aendert: die
Zuordnung der Menuestufen zu den internen Werten ist gemessen, nicht
dokumentiert, und kann jederzeit veralten.

So wurde sie am 23.08.2026 aufgenommen -- je Stufe im Menue umstellen,
eine kurze Aufgabe laufen lassen, dann dieses Werkzeug aufrufen:

    niedrig   effort=low       ultracode nie gesetzt
    mittel    effort=medium    ultracode=false
    hoch      effort=high      ultracode=false
    extra     effort=xhigh     ultracode=false
    max       effort=max       ultracode=false
    ultracode effort=xhigh     ultracode=true

Gezeigt wird nur, was fuer die Zuordnung noetig ist. Titel und
Arbeitsverzeichnis der Sitzungen bleiben bewusst draussen -- sie haben
weder in der Presence noch in einem Messprotokoll etwas verloren.
"""
import glob
import json
import os
import time

# Eine Probe-Datei, die die Sitzung selbst schreibt ("stufe=hoch"),
# macht die Zuordnung eindeutig: der Zeitstempel des Schreibens gehoert
# zu genau einem Turn. Ohne sie raet man ueber die juengste Aktivitaet.
PROBE = os.environ.get("STUFE_PROBE", "")
WURZEL = os.path.expandvars(r"%APPDATA%\Claude\claude-code-sessions")

if PROBE:
    behauptet = "(keine Probe-Datei)"
    try:
        with open(PROBE, encoding="utf-8") as h:
            behauptet = h.read().strip()
    except OSError:
        pass
    print("Behauptete Stufe:", behauptet)
    try:
        print("Probe geschrieben:", time.strftime(
            "%H:%M:%S", time.localtime(os.path.getmtime(PROBE))))
    except OSError:
        pass

print("Sitzungen (juengste Aktivitaet zuerst):")
zeilen = []
for pfad in glob.glob(os.path.join(WURZEL, "**", "local_*.json"),
                      recursive=True):
    try:
        with open(pfad, encoding="utf-8") as h:
            j = json.load(h)
    except (OSError, ValueError):
        continue
    letzte = j.get("lastActivityAt") or 0
    zeilen.append((letzte, {
        "sitzung": (j.get("cliSessionId") or j.get("sessionId") or "?")[:8],
        "effort": j.get("effort"),
        "settings": j.get("sessionSettings"),
        "model": j.get("model"),
        "turns": j.get("completedTurns"),
        "aktiv": time.strftime("%H:%M:%S", time.localtime(letzte / 1000.0))
                 if letzte else "-",
        "datei": time.strftime("%H:%M:%S",
                               time.localtime(os.path.getmtime(pfad))),
    }))

for _, z in sorted(zeilen, reverse=True):
    print("  %s  effort=%-8s settings=%-22s model=%-18s turns=%-3s "
          "aktiv=%s datei=%s"
          % (z["sitzung"], z["effort"], json.dumps(z["settings"]),
             z["model"], z["turns"], z["aktiv"], z["datei"]))
if not zeilen:
    print("  keine gefunden")
