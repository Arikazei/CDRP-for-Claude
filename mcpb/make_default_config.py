"""Erzeugt server/config.default.json aus der lokalen config.json.

Alles Persoenliche wird dabei geleert und alles Heikle abgeschaltet, damit
die weitergegebene Fassung nicht versehentlich deine Einstellungen erbt.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(os.path.dirname(HERE), "config.json")
TARGET = os.path.join(HERE, "server", "config.default.json")

with open(SOURCE, encoding="utf-8") as handle:
    cfg = json.load(handle)

# Mitgelieferte Discord-Anwendung: wer keine eigene anlegen will, bekommt
# damit sofort eine funktionierende Presence. Name und Bilder stammen dann
# aus dieser Anwendung. Eine eigene ID im Einstellungsdialog ueberschreibt sie.
DEFAULT_CLIENT_ID = "1529478569636659372"

cfg.pop("_token_status_hinweis", None)
cfg["client_id"] = DEFAULT_CLIENT_ID
cfg["buttons"] = []
cfg.setdefault("token_status", {}).update({
    "enabled": False,
    "plan_override": "",
})
cfg.setdefault("local_usage", {})["enabled"] = True

EXAMPLE = os.path.join(os.path.dirname(HERE), "config.example.json")

for path in (TARGET, EXAMPLE):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, ensure_ascii=False, indent=2)
    print("geschrieben:", path)
