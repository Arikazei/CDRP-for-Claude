"""Zeigt, was der Master aus den aktuell liegenden Beacons machen wuerde.

Ende-zu-Ende ohne Discord: liest den echten Beacon-Ordner, waehlt den
Rahmen und baut die Nutzlast -- genau wie die Hauptschleife.
"""
import json
import os
import sys
from pathlib import Path

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
os.environ.setdefault("CLAUDE_RPC_CONFIG", os.path.join(WURZEL, "config.json"))

import beacons  # noqa: E402
from claude_rpc import DATA_DIR, fremd_payload  # noqa: E402

cfg = json.loads(Path(os.environ["CLAUDE_RPC_CONFIG"]).read_text("utf-8"))
pool = beacons.Pool(DATA_DIR)
eintraege = pool.lesen()

print("Datenordner:", DATA_DIR)
print("Beacons gelesen:", len(eintraege))
for e in eintraege:
    print("  %-14s %-8s %-16s kind=%s" % (e["client"], e["state"],
                                          e["action"], e["file_kind"]))

rahmen = beacons.rahmen_waehlen(eintraege)
print()
if rahmen is None:
    print("Kein Rahmenbesitzer -> Presence bleibt leer")
    raise SystemExit(0)
print("Rahmen:", rahmen["client"])
if rahmen["client"] == "claude":
    print("-> Claude sendet seine eigene, reichere Nutzlast")
    raise SystemExit(0)
p = fremd_payload(rahmen, cfg)
print("Zeile 1:", p.get("details"))
print("Zeile 2:", p.get("state"))
