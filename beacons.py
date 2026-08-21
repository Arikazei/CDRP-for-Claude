"""Mehrere Coding-Agenten, ein Sender.

Andere Agenten (OpenAI Codex, Google Antigravity) melden ihren Zustand als
kleine JSON-Datei im Unterordner "beacons" des Datenordners. Der Vertrag
steht in SPEC-beacon-v1.md. Hier wird nur gelesen, geprueft und verfallen
gelassen; die Produzenten kennen einander nicht.

Warum ueberhaupt ein Sender: Discord zeigt genau eine Aktivitaet an und
waehlt bei mehreren RPC-Verbindungen unzuverlaessig aus. Zusammenfuehren
ist deshalb Pflicht, nicht Komfort.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

FELDER = {"v", "client", "display_name", "state", "action",
          "model", "session_start", "updated_at", "file_kind"}
ZUSTAENDE = ("working", "waiting", "idle")
AKTIONEN = {
    "thinking", "reading", "editing", "running_tests",
    "running_command", "web_search", "waiting_approval", "idle",
}
RE_SLUG = re.compile(r"^[a-z0-9_-]{1,32}$")

# Verfallsleiter. Ein abgestuerzter Produzent hinterlaesst eine alte Datei;
# sie wird schrittweise zurueckgestuft statt sofort geglaubt oder sofort
# verworfen. So verschwindet ein langer, ereignisloser Denkzug nicht, und
# eine Leiche verfaellt trotzdem von selbst.
STALE = 45
WAITING = 180
DROP = 900

# Die Marken der Produzenten werden erst hier zu Text. Das ist Absicht:
# schickte ein Produzent fertige Formulierungen, koennte er darueber
# beliebigen Inhalt in die Presence schreiben.
AKTIONSTEXT = {
    "thinking": "thinking",
    "reading": "reading",
    "editing": "editing",
    "running_tests": "running tests",
    "running_command": "running a command",
    "web_search": "searching the web",
    "waiting_approval": "waiting for approval",
    "idle": "idle",
}
DATEIART = {
    "python": "Python", "javascript": "JavaScript",
    "typescript": "TypeScript", "markdown": "Markdown", "json": "JSON",
    "yaml": "YAML", "html": "HTML", "css": "CSS", "shell": "shell",
    "powershell": "PowerShell", "csharp": "C#", "cpp": "C++",
    "rust": "Rust", "go": "Go", "java": "Java", "sql": "SQL",
    "text": "text", "config": "config", "image": "image", "data": "data",
    "other": "",
}


def beacon_ordner(datenordner, systemweit=True):
    """Alle Ordner, in denen Beacons liegen koennen -- der eigene zuerst.

    Windows leitet %LOCALAPPDATA% fuer Anwendungen aus dem Microsoft Store
    still um. Die Store-Fassung von Claude Desktop landet deshalb in
    ...\\Packages\\Claude_*\\LocalCache\\Local\\ClaudeDiscordPresence,
    waehrend der Codex-Hook und der Antigravity-Waechter als gewoehnliche
    Prozesse laufen und im echten Ordner schreiben. Beide Seiten glauben,
    denselben Pfad zu benutzen, und sehen einander nie. Gemessen am
    21.08.2026: der eigene Zustand lag in LocalCache, der von Codex im
    echten Ordner, und die Presence blieb bei Claude stehen.

    Gelesen wird deshalb, was erreichbar ist. Geschrieben wird weiterhin
    nur in den eigenen Ordner -- niemand soll fremde Ablagen anlegen.
    """
    ordner = [Path(datenordner) / "beacons"]
    if systemweit and os.name == "nt":
        profil = os.environ.get("USERPROFILE")
        if profil:
            lokal = Path(profil) / "AppData" / "Local"
            ordner.append(lokal / "ClaudeDiscordPresence" / "beacons")
            try:
                for paket in sorted((lokal / "Packages").glob("Claude_*")):
                    ordner.append(paket / "LocalCache" / "Local"
                                  / "ClaudeDiscordPresence" / "beacons")
            except OSError:
                pass
    gesehen = set()
    eindeutig = []
    for pfad in ordner:
        schluessel = os.path.normcase(str(pfad))
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            eindeutig.append(pfad)
    return eindeutig


def pruefen(daten, slug):
    """Gibt den Eintrag zurueck oder None. Im Zweifel None (fail closed)."""
    if not isinstance(daten, dict) or set(daten) != FELDER:
        return None
    if daten.get("v") != 1 or daten.get("client") != slug:
        return None
    if daten.get("state") not in ZUSTAENDE:
        return None
    if daten.get("action") not in AKTIONEN:
        return None
    art = daten.get("file_kind")
    if art is not None and art not in DATEIART:
        return None
    zeit = daten.get("updated_at")
    if not isinstance(zeit, int) or isinstance(zeit, bool):
        return None
    return daten


def verfallen(daten, jetzt):
    """Wendet die Verfallsleiter an. None heisst: zu alt, ignorieren."""
    alter = jetzt - daten["updated_at"]
    if alter > DROP:
        return None
    eintrag = dict(daten)
    if alter > WAITING:
        eintrag["state"] = "idle"
        eintrag["action"] = "idle"
        eintrag["file_kind"] = None
    elif alter > STALE and eintrag["state"] == "working":
        eintrag["state"] = "waiting"
    return eintrag


def rahmen_waehlen(eintraege):
    """Wem gehoert der Rahmen? Reine Funktion, damit ohne Discord pruefbar.

    Zeile 1 und Zeile 2 muessen zwingend vom selben Client stammen -- sonst
    stuende die Taetigkeit des einen ueber dem Modell des anderen. Ein
    Karussell im Sekundentakt gibt es bewusst nicht: der Rahmen wechselt
    nur, wenn die Arbeit wirklich woanders hinwandert.
    """
    for zustand in ("working", "waiting"):
        passend = [e for e in eintraege if e["state"] == zustand]
        if passend:
            return max(passend, key=lambda e: e["updated_at"])
    # Leerlauf zaehlt nur fuer fremde Clients. Claude Desktop hat fuer den
    # eigenen Leerlauf schon einen Weg -- den Leerlauftext aus der
    # Einstellung. Stuende der eigene Beacon hier mit in der Auswahl,
    # gewaenne er praktisch immer: er wird bei jedem Durchlauf neu
    # geschrieben und ist damit fast immer der juengste.
    ruhend = [e for e in eintraege
              if e["state"] == "idle" and e["client"] != "claude"]
    if ruhend:
        return max(ruhend, key=lambda e: e["updated_at"])
    return None


def zeile_taetigkeit(eintrag):
    """Zeile 1: was dieser Client gerade tut.

    Im Leerlauf steht dort nur der Name -- genau wie Claude Desktop im
    Leerlauf "Claude Desktop" zeigt und nicht "Claude Desktop · idle".
    """
    if eintrag["state"] == "idle" or eintrag["action"] == "idle":
        return eintrag["display_name"]
    text = AKTIONSTEXT.get(eintrag["action"], "working")
    art = eintrag.get("file_kind")
    if art and eintrag["action"] in ("reading", "editing"):
        name = DATEIART.get(art, "")
        text += " a %s file" % name if name else " a file"
    return "%s · %s" % (eintrag["display_name"], text)


def zeilen_sitzung(eintrag, cfg=None):
    """Zeile 2 als Liste: alles, was ueber diesen Client bekannt ist.

    Der Aufrufer wechselt zwischen den Teilen durch, so wie Claude
    zwischen Sitzung, Auslastung und Abo wechselt. Fuer fremde Clients
    gibt es Auslastung und Kontingent bewusst nicht: es existiert keine
    lokal lesbare Quelle dafuer, und Anbieter-APIs abzufragen oder Token
    auszulesen ist in diesem Projekt gesperrt (SPEC-beacon-v1). Was hier
    stehen kann, ist deshalb entweder gemessen (Modell) oder von Hand
    eingetragen (Abo-Bezeichnung je Client).
    """
    teile = []
    if eintrag.get("model"):
        teile.append("using %s with %s"
                     % (eintrag["display_name"], eintrag["model"]))
    marken = ((cfg or {}).get("client_plans") or {})
    marke = marken.get(eintrag["client"])
    if isinstance(marke, str) and marke.strip():
        vorlage = ((cfg or {}).get("plan") or {}).get(
            "template", "Abonnement: {plan}")
        teile.append(vorlage.replace("{plan}", marke.strip()))
    return teile


def zeile_sitzung(eintrag, cfg=None):
    """Zeile 2 als einzelner Text -- None, wenn nichts bekannt ist."""
    teile = zeilen_sitzung(eintrag, cfg)
    return " · ".join(teile) if teile else None


class Pool:
    """Liest die Beacon-Dateien der anderen Agenten."""

    def __init__(self, datenordner, systemweit=True):
        # systemweit=False haelt Tests hermetisch: sonst laese ein Pool
        # ueber einem Wegwerfordner die echten Beacons des Rechners mit.
        self.ordner = beacon_ordner(datenordner, systemweit)
        self._gemeldet = set()

    def lesen(self, jetzt=None):
        jetzt = time.time() if jetzt is None else jetzt
        # Derselbe Client kann in mehreren Ordnern liegen (siehe
        # beacon_ordner). Dann gilt der juengste Eintrag, nicht der aus
        # dem zuerst durchsuchten Ordner -- sonst wuerde eine alte Leiche
        # den frischen Zustand verdecken.
        neueste = {}
        for ordner in self.ordner:
            try:
                dateien = sorted(ordner.glob("*.json"))
            except OSError:
                continue
            for pfad in dateien:
                slug = pfad.stem
                # Produzenten legen Beistelldateien daneben, etwa
                # "codex.state.json" fuer zustandslose Hooks. Deren Stamm
                # enthaelt einen Punkt. Ohne diese Zeile wuerde der Pool
                # sie bei jedem Durchlauf lesen, verwerfen, protokollieren.
                if "." in slug or not RE_SLUG.match(slug):
                    continue
                daten = self._laden(pfad, slug)
                if daten is None:
                    continue
                alt = neueste.get(slug)
                if alt is None or daten["updated_at"] > alt["updated_at"]:
                    neueste[slug] = daten
        eintraege = []
        for daten in neueste.values():
            eintrag = verfallen(daten, jetzt)
            if eintrag is not None:
                eintraege.append(eintrag)
        return eintraege

    def _laden(self, pfad, slug):
        try:
            if pfad.stat().st_size > 4096:
                return None
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        geprueft = pruefen(daten, slug)
        if geprueft is None and slug not in self._gemeldet:
            # Einmal je Prozess, nicht bei jedem Durchlauf: sonst laeuft
            # das Protokoll bei einem kaputten Produzenten zu.
            self._gemeldet.add(slug)
            logging.warning("Beacon %s verletzt den Vertrag - ignoriert", slug)
        return geprueft


def eigenen_schreiben(datenordner, state, action, model, session_start,
                      file_kind=None):
    """Der Daemon meldet sich selbst als Produzent.

    Er koennte seinen Zustand auch direkt in den Rahmenwaehler reichen.
    Dann waere er dort aber ein Sonderfall neben den anderen Clients --
    und Sonderfaelle in der Mehrprozess-Koordination sind in diesem
    Projekt schon mehrfach teuer geworden. So gilt fuer alle drei
    dieselbe Regel und derselbe Verfall.
    """
    ordner = datenordner / "beacons"
    daten = {
        "v": 1,
        "client": "claude",
        "display_name": "Claude Desktop",
        "state": state,
        "action": action,
        "model": model,
        "session_start": session_start,
        "updated_at": int(time.time()),
        "file_kind": file_kind,
    }
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        tmp = ordner / "claude.json.tmp"
        tmp.write_text(json.dumps(daten, ensure_ascii=False),
                       encoding="utf-8")
        # Atomar: der Master liest asynchron und darf nie eine halbe
        # Datei sehen.
        os.replace(str(tmp), str(ordner / "claude.json"))
    except OSError as exc:
        logging.warning("Eigener Beacon nicht schreibbar (%s)", exc)
