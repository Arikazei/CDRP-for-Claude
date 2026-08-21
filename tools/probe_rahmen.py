"""Zeigt, was der Master aus den aktuell liegenden Beacons machen wuerde.

Ende-zu-Ende ohne Discord: liest die echten Beacon-Ordner, entscheidet
wie die Hauptschleife und schreibt die volle Runde auf -- also jede
Karte, die im Wechsel zu sehen waere, mit ihrer Uhrzeit.

Der eigene Zustand von Claude ist hier erfunden (die echten Werte kommen
aus dem laufenden Fenster). Er steht nur als Platzhalter drin, damit die
Reihenfolge der Karten sichtbar wird.
"""
import json
import os
import sys
import time
from pathlib import Path

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
os.environ.setdefault("CLAUDE_RPC_CONFIG", os.path.join(WURZEL, "config.json"))

import beacons  # noqa: E402
from claude_rpc import DATA_DIR, karte_payload  # noqa: E402

cfg = json.loads(Path(os.environ["CLAUDE_RPC_CONFIG"]).read_text("utf-8"))
takt = (cfg.get("state_line") or {}).get("alternate_seconds", 20)
pool = beacons.Pool(DATA_DIR)
jetzt = time.time()
eintraege = pool.lesen(jetzt)

print("Eigener Datenordner:", DATA_DIR)
print("Durchsuchte Beacon-Ordner:")
for ordner in pool.ordner:
    print("   %s %s" % ("[ja] " if ordner.is_dir() else "[nein]", ordner))
print("\nBeacons gelesen:", len(eintraege))
for e in eintraege:
    print("  %-14s %-8s %-16s modell=%s alter=%.0fs"
          % (e["client"], e["state"], e["action"], e["model"],
             jetzt - e["updated_at"]))

eigen = {
    "details": "Claude Desktop",
    "zeilen": ["<Sitzung>", "<Auslastung>", "<Abo>"],
    "start": int(jetzt),
    "aktiv": True,
}
chef = beacons.arbeiter(eintraege)
print()
if chef is None:
    print("Niemand arbeitet -> volle Runde durch alle Clients")
    liste = beacons.karten(
        eigen, [e for e in eintraege if e["client"] != "claude"], cfg)
else:
    print("Es arbeitet: %s -> der bekommt die Anzeige allein" % chef["client"])
    if chef["client"] == "claude":
        liste = beacons.karten(eigen, [], cfg)
    else:
        liste = beacons.karten(None, [chef], cfg)

if not liste:
    print("Keine Karte -> Presence bleibt leer")
    raise SystemExit(0)

print("\nVolle Runde: %d Karten a %d s = %d s" % (
    len(liste), max(15, takt), len(liste) * max(15, takt)))
jetzige = beacons.karte_waehlen(liste, jetzt, takt)
for nummer, karte in enumerate(liste):
    p = karte_payload(karte, cfg)
    marke = "->" if karte is jetzige else "  "
    print("%s %d. [%s] %s" % (marke, nummer + 1, karte["client"],
                              p.get("details")))
    print("        %s" % (p.get("state") or "(keine zweite Zeile)"))
