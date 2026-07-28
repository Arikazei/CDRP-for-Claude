"""Beendet laufende claude_rpc-Instanzen und startet eine neue."""
import os
import signal
import subprocess
import sys
import time

import claude_rpc as R

BASE = os.path.dirname(os.path.abspath(__file__))


def running():
    """Laufende Daemon-Prozesse.

    Nur pythonw (der Daemon laeuft fensterlos) und nie der eigene Prozess --
    sonst beendet dieses Skript sich selbst, bevor es etwas ausgibt.
    """
    found = []
    me = os.getpid()
    for pid, name, _ in R.iter_processes():
        if pid == me or not name.startswith("pythonw"):
            continue
        path = R.process_path(pid)
        if path and os.path.normcase(path).startswith(os.path.normcase(BASE)):
            found.append((pid, path))
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
