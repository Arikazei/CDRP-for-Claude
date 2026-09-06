"""Haelt Codex in der Presence sichtbar, solange die App offen ist.

Warum es das braucht: die Hooks von Codex feuern nur bei Ereignissen.
Ist keine Aufgabe unterwegs, schreibt niemand mehr, und der Master
laesst den Beacon nach 900 Sekunden fallen -- Codex verschwand also
eine Viertelstunde nach der letzten Aufgabe lautlos aus der Anzeige,
obwohl die App offen dastand.

Dieser Waechter ergaenzt die Hooks, er ersetzt sie nicht. Er meldet
ausschliesslich "offen und untaetig" und fasst einen Beacon, den ein
Hook geschrieben hat, nicht an, solange dessen Verfallsleiter im Master
noch laeuft.

Erhoben wird nichts ausser der Frage, ob ein Prozess laeuft. Keine
Chatinhalte, keine Titel, keine Pfade, kein Netzzugriff.
"""
import os
import subprocess
import sys
import time

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

from codex_beacon import (  # noqa: E402
    CLIENT, DISPLAY_NAME, atomic_json, beacon_paths, load_state,
    load_window, model_label, window_path,
)

# Prozessnamen der Codex-App. ChatGPT.exe ist das Fenster, codex.exe der
# mitgelieferte Kern; einer von beiden genuegt.
PROZESSE = ("chatgpt.exe", "codex.exe")
PROZESSE_LINUX = ("chatgpt", "codex")

TAKT = 15.0          # Wie oft nachgesehen wird
RUHE_HERZSCHLAG = 60.0   # Wie oft der Ruhe-Beacon erneuert wird
# Ab hier haette der Master den Hook-Beacon ohnehin auf "idle"
# zurueckgestuft (beacons.WAITING = 180). Erst danach uebernimmt der
# Waechter, damit er einem laufenden Denkzug nicht dazwischenfunkt.
UEBERNAHME_AB = 200.0


def app_laeuft():
    """Ist die Codex-App offen?

    Im Zweifel False: ein fehlender Beacon verfaellt von selbst, ein
    faelschlich geschriebener bliebe stehen, bis sich der Nutzer
    abmeldet.
    """
    try:
        if os.name == "nt":
            # Ohne text=True: tasklist antwortet in der Konsolen-Codepage
            # und in der Systemsprache. Auf einem deutschen Windows
            # enthaelt schon die Fehlanzeige einen Umlaut, an dem Python
            # mit UnicodeDecodeError abbrach. Der Vergleich laeuft
            # deshalb auf Bytes.
            ausgabe = (subprocess.run(
                ["tasklist", "/NH"], capture_output=True,
                timeout=20, creationflags=0x08000000,
            ).stdout or b"").lower()
            return any(name.encode("ascii") in ausgabe for name in PROZESSE)
        for eintrag in os.listdir("/proc"):
            if not eintrag.isdigit():
                continue
            try:
                with open("/proc/%s/comm" % eintrag, encoding="utf-8") as h:
                    name = h.read().strip().lower()
            except OSError:
                continue
            if name in PROZESSE_LINUX:
                return True
        return False
    except Exception:
        return False


# Wie lange der Waechter einen "working"-Zustand am Leben haelt, wenn
# kein neues Hook-Ereignis kommt. Danach uebernimmt wieder die
# Verfallsleiter des Masters.
#
# Der Grund: die Hooks feuern je Werkzeugaufruf. Denkt Codex laenger
# nach oder laeuft ein Befehl minutenlang, kommt dazwischen nichts, und
# der Master stuft nach 45 Sekunden auf "waiting" zurueck -- Codex faellt
# aus der Anzeige, obwohl er sichtbar arbeitet. Am 22.08.2026 gemessen:
# zweieinhalb Minuten Arbeit, in der Presence nie zu sehen.
#
# Die Obergrenze ist der Preis dafuer: stirbt Codex mitten in einer
# Aufgabe, steht er hoechstens so lange faelschlich als arbeitend da.
ARBEIT_HERZSCHLAG = 20.0
ARBEIT_MAX = 600.0

_ARBEIT = {"seit": 0.0, "stand": None}


def arbeit_verlaengern(zustand, jetzt):
    """Soll der laufende Arbeitszustand erneuert werden?

    Der Anker ist der Zeitstempel des letzten echten Hook-Ereignisses.
    Kommt ein neues, wandert der Anker mit; bis dahin zaehlt der
    Waechter von ihm aus.
    """
    if not zustand or zustand.get("state") != "working":
        _ARBEIT["stand"] = None
        return False
    stand = zustand.get("updated_at")
    if stand != _ARBEIT["stand"]:
        # Neues Hook-Ereignis (oder erster Blick): Anker neu setzen.
        _ARBEIT["stand"] = stand
        _ARBEIT["seit"] = jetzt
        return False
    if jetzt - _ARBEIT["seit"] > ARBEIT_MAX:
        return False
    return jetzt - (stand or 0) >= ARBEIT_HERZSCHLAG


def faellig(zustand, jetzt):
    """Soll der Waechter jetzt schreiben?

    Drei Faelle, in dieser Reihenfolge:

    - Kein Beacon vorhanden: schreiben, die App ist offen.
    - Der letzte Stand ist schon "idle": erneuern, sobald er altert.
      Genau das haelt Codex in der Runde.
    - Der letzte Stand kommt von einem Hook (working/waiting): in Ruhe
      lassen, bis die Verfallsleiter des Masters ihn ohnehin auf "idle"
      gestellt haette. Sonst wuerde ein langer Denkzug ohne
      Werkzeugaufruf faelschlich als Leerlauf gemeldet.
    """
    if not zustand:
        return True
    alter = jetzt - (zustand.get("updated_at") or 0)
    if zustand.get("state") == "idle":
        return alter >= RUHE_HERZSCHLAG
    return alter >= UEBERNAHME_AB


_FENSTER = {"zeit": 0.0, "moeglich": True}
FENSTERBLICK_TAKT = 20.0


def fensterblick(jetzt):
    """Einstellungsfenster ansehen, falls es gerade offen ist.

    Kostet einen Baumdurchlauf, deshalb hoechstens alle 20 Sekunden.
    Traegt uiautomation hier nicht, wird es genau einmal versucht und
    danach nie wieder.
    """
    if not _FENSTER["moeglich"]:
        return
    if jetzt - _FENSTER["zeit"] < FENSTERBLICK_TAKT:
        return
    _FENSTER["zeit"] = jetzt
    try:
        import fenster
        gelesen = fenster.lies_alle()
    except Exception:
        _FENSTER["moeglich"] = False
        return
    if not gelesen:
        return
    gelesen["read_at"] = int(jetzt)
    try:
        atomic_json(window_path(), gelesen)
    except Exception:
        pass


def ruhe_beacon(zustand, jetzt):
    """Beacon fuer "offen, aber untaetig".

    Das Modell wird aus dem letzten Hook-Stand uebernommen, wenn eines
    bekannt ist -- es aendert sich im Leerlauf nicht. Die Sitzung faellt
    weg: eine Laufzeit ohne laufende Sitzung waere eine erfundene Zahl.
    """
    beacon = {
        "v": 1,
        "client": CLIENT,
        "display_name": DISPLAY_NAME,
        "state": "idle",
        "action": "idle",
        # Durch dieselbe Pruefung wie im Hook: der Zustandsspeicher ist
        # eine Datei, und was darin steht, gilt nicht ungeprueft.
        "model": model_label((zustand or {}).get("model")),
        "session_start": None,
        "updated_at": int(jetzt),
        "file_kind": None,
    }
    beacon.update(load_window(int(jetzt)))
    return beacon


def beacon_entfernen():
    """Eigene Beacon-Datei loeschen, wenn die App zu ist.

    Statt auf den Verfall nach 15 Minuten zu warten: wer sein Programm
    zumacht, erwartet, dass es sofort aus der Presence verschwindet.
    Der Zustandsspeicher der Hooks bleibt liegen -- er ist deren
    Gedaechtnis, nicht unsere Anzeige.
    """
    beacon_pfad, _ = beacon_paths()
    try:
        if os.path.exists(beacon_pfad):
            os.remove(beacon_pfad)
    except OSError:
        pass


def schritt():
    if not app_laeuft():
        beacon_entfernen()
        _ARBEIT["stand"] = None
        return False
    jetzt = time.time()
    # Erst nachsehen, dann schreiben: sonst traegt der Ruhe-Beacon die
    # Werte des vorigen Durchlaufs, obwohl gerade frischere dastehen.
    fensterblick(jetzt)
    beacon_pfad, zustand_pfad = beacon_paths()
    zustand = load_state(zustand_pfad)

    if arbeit_verlaengern(zustand, jetzt):
        # Denselben Zustand noch einmal schreiben, nur mit frischer
        # Uhrzeit. Inhaltlich wird nichts erfunden -- es bleibt exakt
        # das, was der letzte Hook gemeldet hat.
        daten = dict(zustand)
        daten["model"] = model_label(daten.get("model"))
        daten["updated_at"] = int(jetzt)
        daten.update(load_window(int(jetzt)))
        atomic_json(beacon_pfad, daten)
        return True

    if not faellig(zustand, jetzt):
        return False
    daten = ruhe_beacon(zustand, jetzt)
    atomic_json(beacon_pfad, daten)
    atomic_json(zustand_pfad, daten)
    return True


def main():
    while True:
        try:
            schritt()
        except Exception:
            # Ein Waechter, der an einem Schreibfehler stirbt, ist
            # nutzloser als einer, der es beim naechsten Mal erneut
            # versucht.
            pass
        time.sleep(TAKT)


if __name__ == "__main__":
    main()
