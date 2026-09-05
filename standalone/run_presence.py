"""Die Presence als eigenstaendiger Dienst, unabhaengig von Claude Desktop.

Warum ueberhaupt: bisher lief der Sender als Kind der Claude-Desktop-App.
Das hatte drei Folgen, die alle laestig waren.

Erstens war die Presence weg, sobald Claude zu war -- auch wenn Codex
oder Antigravity gerade arbeiteten. Zweitens leitete Windows den
Datenordner um, weil die Store-Fassung von Claude in einem App-Container
laeuft; Produzenten ausserhalb schrieben woanders hin und wurden nie
gesehen. Drittens brauchte es Mutex, Watchdog und Uebernahmeschleife nur,
um diese Kopplung zu verwalten.

Der Dienst hat Vorrang vor der Extension (siehe beacons.ROLLEN_RANG).
Laeuft er, weicht sie und beantwortet nur noch Werkzeugaufrufe. Faellt er
aus, uebernimmt sie binnen einer Minute wieder. Es muss sich also
niemand eine Startreihenfolge merken.
"""
import json
import os
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(HIER / "lib"))

WARTETAKT = 15


def datenordner():
    """Der eigene Datenordner -- CLAUDE_RPC_DATA_DIR, wenn gesetzt.

    Die Umgebungsvariable gilt ueberall sonst im Projekt; hier wurde sie
    bisher ueberschrieben. Damit liess sich der Dienst nicht abgetrennt
    betreiben, etwa fuer einen Test aus einem frischen Klon, ohne den
    laufenden Datenordner anzufassen.
    """
    from pathlib import Path
    from hostplatform import app_data_dir
    eigen = os.environ.get("CLAUDE_RPC_DATA_DIR")
    pfad = Path(eigen).expanduser().resolve() if eigen else app_data_dir()
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def konfiguration_finden(eigener):
    """Die Konfiguration, die der Nutzer wirklich eingestellt hat.

    Die Einstellungen kommen aus dem Dialog von Claude Desktop; die
    Extension schreibt sie nach config.json. Unter Windows landet das im
    umgeleiteten Ordner des App-Containers, den dieser Dienst nicht als
    seinen eigenen kennt. Deshalb dieselbe Suche wie bei den Beacons:
    alle Kandidatenordner ansehen, die juengste Datei gewinnt.

    Ohne das liefe der Dienst mit der mitgelieferten Vorgabe, waehrend im
    Einstellungsdialog etwas anderes steht -- und niemand kaeme darauf,
    warum.
    """
    import beacons
    beste = None
    bestes_alter = None
    for ordner in beacons.datenordner_kandidaten(eigener):
        pfad = ordner / "config.json"
        try:
            zeit = pfad.stat().st_mtime
        except OSError:
            continue
        if bestes_alter is None or zeit > bestes_alter:
            bestes_alter = zeit
            beste = pfad
    if beste is None:
        vorlage = WURZEL / "config.example.json"
        ziel = eigener / "config.json"
        try:
            ziel.write_text(vorlage.read_text(encoding="utf-8"),
                            encoding="utf-8")
            return ziel
        except OSError:
            return vorlage
    return beste


def main():
    eigener = datenordner()
    os.environ["CLAUDE_RPC_DATA_DIR"] = str(eigener)
    os.environ.setdefault("CLAUDE_RPC_LOG", str(eigener / "standalone.log"))
    os.environ["CLAUDE_RPC_CONFIG"] = str(konfiguration_finden(eigener))

    import beacons
    import hostplatform
    import claude_rpc as rpc

    rpc.init_com()
    while True:
        try:
            rpc.main(rolle="standalone")
        except Exception:
            import logging
            logging.exception("Presence-Schleife abgebrochen")
        # Auch waehrend des Wartens sichtbar bleiben. Ein Dienst, der
        # sich nur beim Senden meldet, wuerde von der Extension nie
        # gesehen -- sie gaebe die Sperre nicht frei und beide warteten
        # aufeinander.
        # Waehrend des Wartens weiter anmelden -- und deutlich oefter
        # nachsehen, als der Wartetakt lang ist. Die Extension gibt den
        # Mutex frei und greift ihn drei Sekunden spaeter zurueck, wenn
        # niemand schneller ist: gemessen am 30.08.2026, 11:06:50 Rueckzug,
        # 11:06:53 wieder da. Der Dienst stand danach 18 Minuten stumm.
        for _ in range(WARTETAKT):
            beacons.sender_melden(eigener, "standalone")
            if hostplatform.single_instance():
                hostplatform.release_instance()
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
