"""Pruefung: sieht dieses Python das echte %APPDATA%\\Claude?"""
import os
import sys

appdata = os.environ.get("APPDATA", "")
claude = os.path.join(appdata, "Claude")
usage = os.path.join(claude, "plan-usage-history.json")
sessions = os.path.join(claude, "claude-code-sessions")

print("python      :", sys.executable)
print("APPDATA     :", appdata)
print("Claude-Ordner:", os.path.isdir(claude))
print("usage-Datei  :", os.path.isfile(usage))
print("sessions-Dir :", os.path.isdir(sessions))
if "WindowsApps" in sys.executable:
    print("WARNUNG: Store-Python - %APPDATA% ist umgeleitet, Reader bleiben leer.")
elif not os.path.isfile(usage):
    print("WARNUNG: plan-usage-history.json nicht gefunden.")
else:
    print("OK: Pfade sichtbar.")
