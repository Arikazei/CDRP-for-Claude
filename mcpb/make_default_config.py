"""Erzeugt server/config.default.json aus der versionierten config.example.json.

Frueher war die Quelle die lokale config.json. Das hatte eine stille
Nebenwirkung: kam ueber einen Pull Request ein neuer Schluessel dazu, der
lokal fehlte, warf der naechste Bau ihn wieder aus dem Paket. Die Funktion
war dann im Quelltext vorhanden, per Vorgabe aber abgeschaltet -- genau so
geschehen mit den ui_watcher-Schluesseln aus PR #2.

Mit der versionierten Vorlage als Quelle ist der Bau ausserdem
reproduzierbar: er braucht keine Datei mehr, die nur auf einem Rechner
liegt, und laeuft damit auch auf einem Runner.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(os.path.dirname(HERE), "config.example.json")
TARGET = os.path.join(HERE, "server", "config.default.json")

with open(SOURCE, encoding="utf-8") as handle:
    cfg = json.load(handle)

# Mitgelieferte Discord-Anwendung: wer keine eigene anlegen will, bekommt
# damit sofort eine funktionierende Presence. Name und Bilder stammen dann
# aus dieser Anwendung. Eine eigene ID im Einstellungsdialog ueberschreibt sie.
DEFAULT_CLIENT_ID = "1529478569636659372"

# Die Vorlage ist versioniert und sollte nichts Persoenliches enthalten. Hier
# wird trotzdem geleert und abgeschaltet: kommt doch einmal eine eigene App-ID
# oder ein eigener Knopf hinein, faellt das sonst erst auf, wenn es bei einem
# Fremden im Discord-Profil steht.
cfg["client_id"] = DEFAULT_CLIENT_ID
cfg["buttons"] = []
# Leer heisst: die Plattformschicht entscheidet. "claude.exe" fest
# einzutragen waere unter Linux falsch.
cfg["process_names"] = []
cfg.setdefault("plan", {})["override"] = ""
cfg.setdefault("local_usage", {})["enabled"] = True

with open(TARGET, "w", encoding="utf-8") as handle:
    json.dump(cfg, handle, ensure_ascii=False, indent=2)
print("geschrieben:", TARGET)
