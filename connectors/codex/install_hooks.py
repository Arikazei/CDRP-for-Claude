"""Erzeugt Starter und Hook-Dateien fuer den Codex-Connector.

Codex ruft bei jedem Ereignis einen Befehl auf. Der muss den Python-
Interpreter und codex_beacon.py dieser Installation kennen -- zwei Pfade,
die auf jedem Rechner anders sind. Deshalb stehen im Repo nur Vorlagen
mit Platzhaltern, und dieses Skript fuellt sie aus:

    {{PYTHON}}   Interpreter, der den Hook ausfuehrt
    {{BEACON}}   connectors/codex/codex_beacon.py dieser Kopie
    {{STARTER}}  erzeugte Startdatei, ein Pfad ohne Leerzeichen

Warum ein Starter: Codex startet unter Windows keine Befehlszeile mit
Anfuehrungszeichen. Ein Interpreterpfad mit Leerzeichen laesst sich also
nicht direkt eintragen. Der Starter ist eine winzige .cmd (Linux: .sh),
deren eigener Pfad ohne Leerzeichen auskommt und die innerhalb der Datei
beliebig zitieren darf.

Warum erzeugt und nicht von Hand gepflegt: eine handgeschriebene Kopie
lief hier schon einmal still auseinander -- Aenderungen am Connector
kamen beim Hook nie an. Der Starter zeigt deshalb immer auf die Datei im
Repo, und dieses Skript ist der einzige Weg, ihn zu schreiben.

Erzeugt wird:

    <Datenordner>/codex-hook.cmd bzw. .sh   der Starter
    <Datenordner>/codex-hooks.json          Inhalt fuer ~/.codex/hooks.json
    connectors/codex/plugin/plugins/codex-discord-presence/hooks.json
                                            fuer das Codex-Plugin, untracked

Aufruf:

    python connectors/codex/install_hooks.py
    python connectors/codex/install_hooks.py --python <Pfad zu python>
    python connectors/codex/install_hooks.py --starter <Pfad ohne Leerzeichen>
"""
import argparse
import json
import os
import stat
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(os.path.dirname(HIER))
if WURZEL not in sys.path:
    sys.path.insert(0, WURZEL)
import beacons  # noqa: E402

BEACON = os.path.join(HIER, "codex_beacon.py")
VORLAGE_GLOBAL = os.path.join(HIER, "hooks.json")
MARKTPLATZ = os.path.join(HIER, "plugin")
PLUGIN = os.path.join(MARKTPLATZ, "plugins", "codex-discord-presence")
VORLAGE_PLUGIN = os.path.join(PLUGIN, "hooks.json.in")
ZIEL_PLUGIN = os.path.join(PLUGIN, "hooks.json")


def python_finden(wunsch):
    """Der Interpreter fuer den Hook.

    pythonw hat keine Standardausgabe, der Hook muss aber "{}" zurueckgeben.
    Wer mit pythonw installiert, bekommt deshalb das python.exe daneben.
    """
    pfad = os.path.abspath(wunsch or sys.executable)
    ordner, name = os.path.split(pfad)
    if name.lower().startswith("pythonw"):
        kandidat = os.path.join(ordner, "python" + name[7:])
        if os.path.exists(kandidat):
            pfad = kandidat
    if not os.path.exists(pfad):
        raise SystemExit("Interpreter nicht gefunden: %s" % pfad)
    return pfad


def starter_pfad(wunsch, datenordner):
    if wunsch:
        return os.path.abspath(wunsch)
    name = "codex-hook.cmd" if os.name == "nt" else "codex-hook.sh"
    return os.path.join(datenordner, name)


def starter_schreiben(pfad, python, beacon):
    if any(zeichen.isspace() for zeichen in pfad):
        raise SystemExit(
            "Der Starter darf keinen Leerraum im Pfad haben: %s\n"
            "Codex startet unter Windows keine Befehlszeile mit "
            "Anfuehrungszeichen. Mit --starter einen kurzen Pfad ohne "
            "Leerzeichen angeben." % pfad)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    if os.name == "nt":
        zeilen = [
            "@echo off",
            "rem Startet den Beacon-Schreiber fuer Codex.",
            "rem Erzeugt von connectors/codex/install_hooks.py. Nicht von",
            "rem Hand bearbeiten: der naechste Lauf ersetzt die Datei.",
            '"%s" "%s"' % (python, beacon),
        ]
        inhalt = "\r\n".join(zeilen) + "\r\n"
    else:
        zeilen = [
            "#!/bin/sh",
            "# Startet den Beacon-Schreiber fuer Codex.",
            "# Erzeugt von connectors/codex/install_hooks.py. Nicht von",
            "# Hand bearbeiten: der naechste Lauf ersetzt die Datei.",
            'exec "%s" "%s"' % (python, beacon),
        ]
        inhalt = "\n".join(zeilen) + "\n"
    with open(pfad, "w", encoding="utf-8", newline="") as handle:
        handle.write(inhalt)
    if os.name != "nt":
        os.chmod(pfad, os.stat(pfad).st_mode
                 | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def rendern(vorlage, ziel, werte):
    """Platzhalter ersetzen; jeder Wert wird JSON-sicher eingesetzt."""
    with open(vorlage, "r", encoding="utf-8") as handle:
        text = handle.read()
    for name, wert in werte.items():
        text = text.replace("{{%s}}" % name, json.dumps(wert)[1:-1])
    if "{{" in text:
        raise SystemExit("Unbekannter Platzhalter in %s" % vorlage)
    json.loads(text)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(ziel, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def selbsttest(starter):
    """Ein leeres Ereignis durch den Starter schicken.

    Ein leeres Objekt ist kein bekanntes Ereignis: der Hook schreibt
    keinen Beacon, antwortet aber mit "{}" und Exitcode 0. Genau das
    muss ankommen, sonst stimmt einer der beiden Pfade nicht.
    """
    try:
        lauf = subprocess.run([starter], input="{}", capture_output=True,
                              text=True, timeout=30)
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    if lauf.returncode != 0:
        return False, "Exitcode %d" % lauf.returncode
    if lauf.stdout.strip() != "{}":
        return False, "unerwartete Ausgabe (%d Zeichen)" % len(lauf.stdout)
    return True, "ok"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", help="Interpreter fuer den Hook "
                        "(Vorgabe: der, der dieses Skript ausfuehrt)")
    parser.add_argument("--starter", help="Pfad des erzeugten Starters, "
                        "ohne Leerzeichen (Vorgabe: im Datenordner)")
    parser.add_argument("--ohne-test", action="store_true",
                        help="Selbsttest des Starters ueberspringen")
    args = parser.parse_args()

    datenordner = str(beacons.produzenten_datenordner())
    python = python_finden(args.python)
    starter = starter_pfad(args.starter, datenordner)
    starter_schreiben(starter, python, BEACON)

    werte = {"PYTHON": python, "BEACON": BEACON, "STARTER": starter}
    ziel_global = os.path.join(datenordner, "codex-hooks.json")
    rendern(VORLAGE_GLOBAL, ziel_global, werte)
    rendern(VORLAGE_PLUGIN, ZIEL_PLUGIN, werte)

    print("Interpreter:   ", python)
    print("Beacon-Skript: ", BEACON)
    print("Starter:       ", starter)
    print("Hook-Datei:    ", ziel_global)
    print("Plugin-Hooks:  ", ZIEL_PLUGIN)
    if not args.ohne_test:
        ok, meldung = selbsttest(starter)
        print("Selbsttest:    ", meldung)
        if not ok:
            return 1
    print()
    print("Einmalig in Codex registrieren:")
    print('  codex plugin marketplace add "%s"' % MARKTPLATZ)
    print("  codex plugin add codex-discord-presence@personal")
    print("Danach in der App /hooks oeffnen und die sieben Hooks als")
    print("vertrauenswuerdig bestaetigen. Ohne Plugin tut es auch die")
    print("Hook-Datei: ihren Inhalt nach ~/.codex/hooks.json uebernehmen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
