"""Beendet laufende claude_rpc-Instanzen und startet eine neue."""
import os
import signal
import subprocess
import sys
import time

import claude_rpc as R

BASE = os.path.dirname(os.path.abspath(__file__))


def running():
    """Laufende Daemon-Prozesse, erkannt an der Befehlszeile.

    Frueher wurde am Pfad des Interpreters erkannt -- damit blieb eine
    Instanz unsichtbar, die mit einem anderen Python gestartet wurde. Genau
    so lief monatelang ein zweiter Dienst aus dem Autostart mit.
    Der eigene Prozess bleibt aussen vor, sonst beendet dieses Skript sich
    selbst, bevor es etwas ausgibt.
    """
    found = []
    me = os.getpid()
    target = os.path.normcase(os.path.join(BASE, "claude_rpc.py"))
    for pid, name, _ in R.iter_processes():
        if pid == me:
            continue
        if not (name.startswith("python")
                or name.startswith("claudediscordpresence")):
            continue
        if target in os.path.normcase(R.process_cmdline(pid)):
            found.append((pid, R.process_path(pid) or name))
    return found


killed = []
for pid, path in running():
    try:
        os.kill(pid, signal.SIGTERM)
        killed.append(pid)
    except OSError as exc:
        print("kill fehlgeschlagen", pid, exc)
print("beendet:", killed)
time.sleep(2)

subprocess.Popen(
    ["wscript.exe", os.path.join(BASE, "start_claude_rpc.vbs")],
    creationflags=0x00000008,
)
time.sleep(10)

alive = running()
print("laeuft jetzt:")
for entry in alive:
    print("  ", entry)
if not alive:
    print("  nichts - siehe claude_rpc.log")
    sys.exit(1)
