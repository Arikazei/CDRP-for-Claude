# RAM-Leak-Report — 15.08.2026 (arikazei, Windows, 93,6 GB RAM)

Analysiert + behoben von Claude (Cowork) via Desktop Commander.
Symptom: RAM lief voll (nur noch ~12 GB frei), Task Manager zeigte
tausende python3.12-Prozesse.

## Befund

**13.000+ python3.12.exe-Prozesse, zusammen ~108 GB privater Speicher.**
(Messung: `Get-Process | Group-Object Name` → python3.12: 13.173 Stück,
108,32 GB; einzelne Prozesse je nur ~30-800 MB, darum in der
Task-Manager-Einzelansicht unauffällig.)

Zwei getrennte Quellen:

### Quelle 1 (HAUPTPROBLEM): Fork-Bombe im Projekt „Modding Converter"

- Skripte: `P:\Programmed with Claude\Modding Converter\pytools\
  run_regress.py` (spawnt auch `mc10_regress.py`)
- Python: Microsoft-Store-Python 3.12 (PythonSoftwareFoundation.Python.
  3.12_qbz5n2kfra8p0)
- Aktiv seit ca. 15.08. 03:00, vermehrte sich noch während der Analyse
  (22 → 104 Prozesse in wenigen Sekunden nach erstem Kill).
- Beweis für Selbst-Vermehrung: Eltern-Kind-Ketten mit IDENTISCHER
  Kommandozeile (python run_regress.py spawnt python run_regress.py);
  nach Kill der Eltern machten verwaiste Kinder weiter.

**Wahrscheinliche Ursache (klassischer Windows-Python-Bug):**
`multiprocessing` (Pool/Process) ohne `if __name__ == "__main__":`-Guard.
Windows hat kein fork — jeder Worker-Prozess importiert das Skript neu
und führt dabei den Modul-Top-Level erneut aus. Steht der
Pool-/Process-Start im Top-Level, spawnt jedes Kind wieder Kinder →
exponentielle Fork-Bombe.

**Nötiger Fix im Modding-Converter-Projekt:**

    # run_regress.py / mc10_regress.py — gesamten Ablauf kapseln:
    def main():
        ...  # bisheriger Top-Level-Code (inkl. Pool/Process-Starts)

    if __name__ == "__main__":
        main()

Zusätzlich empfehlenswert: maxtasksperchild setzen und Worker-Anzahl
begrenzen (os.cpu_count() ist beim 9950X3D = 32 Threads!).

### Quelle 2 (NEBENPROBLEM): Claude-Extension „claude-discord-presence"

- `%APPDATA%\Claude\Claude Extensions\local.mcpb.arikazei.
  claude-discord-presence\server\main.py`
- Seit 14.08. ~16:28 sammelten sich bei jedem Claude-Desktop-Reconnect
  neue main.py-Server-Instanzen an, die nie beendet wurden (je ~einige
  hundert MB). Kein exponentielles Wachstum, aber stetiges Ansammeln.
- Fix-Idee für die Extension: beim Start prüfen, ob schon eine Instanz
  läuft (Lockfile/Port-Bind) und alte Instanz beenden; oder sauberes
  Exit-Handling wenn die stdio-Verbindung zum Host abreißt.

## Was zur Behebung gemacht wurde (Reihenfolge)

1. Diagnose: Top-Prozesse nach privatem Speicher + Gruppierung nach
   Namen → 13.173× python3.12 mit 108 GB identifiziert.
2. Kommandozeilen + Eltern-PIDs ausgelesen → beide Quellen identifiziert.
3. Mit Marcos Freigabe: `taskkill /f /im python3.12.exe /t`
   → RAM sofort 12,3 → 73,3 GB frei. ABER: Bombe wuchs nach
   (Selbst-Vermehrung durch verwaiste Kinder).
4. Kette atomar gebrochen: beide Skripte umbenannt →
   `run_regress.py.disabled` + `mc10_regress.py.disabled`
   (neue Spawns finden die Datei nicht mehr und sterben sofort),
   danach Kill-Schleife bis 0 Prozesse.
5. Verifikation nach 20 s: weiterhin 0 python3.12-Prozesse,
   **75,2 GB RAM frei**. System stabil.

## Aktueller Zustand / offene Punkte

- Die zwei Skripte liegen UMBENANNT (nur .disabled angehängt, nichts
  gelöscht) in `P:\Programmed with Claude\Modding Converter\pytools\`.
- WICHTIG: Vor dem Zurückbenennen MUSS der __main__-Guard eingebaut
  werden, sonst startet die Bombe beim nächsten Lauf sofort wieder.
- Die Discord-Presence-Extension läuft weiter (Claude Desktop startet
  bei Bedarf eine frische Instanz). Falls sie wieder Prozesse ansammelt:
  in Claude Desktop deaktivieren, bis das Exit-Handling gefixt ist.
- Unbeteiligt: Babble-Trainer-Projekt (eigene venv-python.exe),
  chroma-mcp (claude-mem), WSL/vmmem (~0,7 GB, unauffällig).
