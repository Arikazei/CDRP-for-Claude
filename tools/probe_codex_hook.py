"""Fuettert den Codex-Hook mit synthetischen Nutzlasten und prueft den Beacon.

Der Befund von Codex konnte PreToolUse/PostToolUse nicht real messen (TLS in
der Sandbox). Genau dieser Pfad wird hier trotzdem durchgespielt.
"""
import json
import os
import subprocess
import sys
import tempfile

# In einen Wegwerfordner schreiben, nie in den echten Datenordner: der
# Hook wuerde sonst den Beacon des laufenden Codex mit Testwerten
# ueberschreiben. Der Kindprozess erbt die Umgebung.
_WEGWERF = tempfile.TemporaryDirectory()
os.environ["CLAUDE_RPC_DATA_DIR"] = _WEGWERF.name

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
HOOK = os.path.join(WURZEL, "connectors", "codex", "codex_beacon.py")
sys.path.insert(0, HIER)
from validate_beacon import einmal, beacon_ordner  # noqa: E402

FAELLE = [
    ("SessionStart", {"hook_event_name": "SessionStart", "model": "gpt-5.6-sol",
                      "session_id": "abc", "cwd": r"X:\geheim\projekt",
                      "transcript_path": r"C:\geheim\t.jsonl"}),
    ("UserPromptSubmit", {"hook_event_name": "UserPromptSubmit",
                          "model": "gpt-5.6-sol", "turn_id": "t1",
                          "prompt": "GEHEIMER PROMPT ueber kuendigung_mueller"}),
    ("PreToolUse Edit", {"hook_event_name": "PreToolUse", "model": "gpt-5.6-sol",
                         "tool_name": "Edit",
                         "tool_input": {"file_path": r"X:\geheim\Script.py"}}),
    ("PreToolUse Bash test", {"hook_event_name": "PreToolUse",
                              "model": "gpt-5.6-sol", "tool_name": "Bash",
                              "tool_input": {"command": "pytest -q tests/"}}),
    ("PreToolUse Bash sonst", {"hook_event_name": "PreToolUse",
                               "model": "gpt-5.6-sol", "tool_name": "Bash",
                               "tool_input": {"command": "curl https://geheim.example/x"}}),
    ("Stop", {"hook_event_name": "Stop", "model": "gpt-5.6-sol"}),
]

VERBOTEN = ["geheim", "Script.py", "kuendigung", "pytest", "curl",
            "https", "abc", "t.jsonl", "X:\\", "C:\\"]

fehler = []
for name, nutzlast in FAELLE:
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(nutzlast),
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        fehler.append("%s: Exitcode %d (muss immer 0 sein)"
                      % (name, p.returncode))
    pfad = os.path.join(beacon_ordner(), "codex.json")
    verstoesse, daten = einmal(pfad)
    if verstoesse:
        fehler.append("%s: %s" % (name, "; ".join(verstoesse)))
        print("%-22s FEHLER" % name)
        continue
    roh = open(pfad, encoding="utf-8").read()
    leck = [w for w in VERBOTEN if w.lower() in roh.lower()]
    if leck:
        fehler.append("%s: Leck im Beacon: %s" % (name, ", ".join(leck)))
    print("%-22s -> %-16s %-16s kind=%s  modell=%s"
          % (name, daten["state"], daten["action"],
             daten["file_kind"], daten["model"]))

print()
if fehler:
    print("FEHLER:")
    for e in fehler:
        print("  -", e)
    sys.exit(1)
print("OK - alle Faelle vertragskonform, kein Leck")
