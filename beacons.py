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

# Vertrag 1.1. Zusatzfelder sind freiwillig; ein Beacon ohne sie bleibt
# gueltig. Sie sind bewusst eng gefasst, weil hier zum ersten Mal Text
# eines Produzenten in die Presence gelangen koennte. Deshalb:
#
#   plan   -- kurz, und nur Zeichen, aus denen sich kein zweiter Satz
#             bauen laesst. Der Master rendert ihn ueber seine eigene
#             Vorlage, der Produzent liefert nur den nackten Namen.
#   usage  -- gar kein Text, sondern ganze Zahlen. Formuliert wird erst
#             hier. Semantik ist VERBRAUCHT in Prozent, nicht
#             verbleibend: Antigravity zeigt "Weekly Limit Remaining
#             97%", Claude zeigt den verbrauchten Anteil. Stuende in
#             derselben Zeile mal das eine, mal das andere, faellt es
#             niemandem auf und alle Zahlen waeren wertlos.
ZUSATZFELDER = {"plan", "usage"}
PLAN_MAX = 32
RE_PLAN = re.compile(r"^[A-Za-z0-9 ()×.+/-]{1,%d}$" % PLAN_MAX)
USAGE_SCHLUESSEL = ("five_hour", "week")
ZUSTAENDE = ("working", "waiting", "idle")
AKTIONEN = {
    "thinking", "reading", "editing", "running_tests",
    "running_command", "web_search", "waiting_approval", "idle",
}
RE_SLUG = re.compile(r"^[a-z0-9_-]{1,32}$")

# Die Muster fuer Anzeigename und Modell wohnen NUR hier. Sender,
# beide Connectoren, der Fensterleser und der Pruefer importieren sie;
# der Vertrag verweist hierher. Vorher standen sie an fuenf Stellen in
# drei Fassungen, und Pruefer und Vertrag verwarfen Beacons, die die
# Produzenten gueltig schreiben durften. tools/test_beacons.py wacht
# darueber, dass keine zweite Fassung entsteht.
#
# Das Modellmuster ist die Vereinigung der frueheren Fassungen: erstes
# Zeichen alphanumerisch, dann Buchstaben, Ziffern, Leerzeichen, Punkt,
# Unterstrich, Klammern, Plus, Bindestrich, hoechstens 40 Zeichen. Damit
# bleibt "GPT-5 (Preview)" gueltig, und aus einem Prompt, Pfad oder
# Satzzeichen laesst sich trotzdem kein Modellname bauen.
NAME_MAX = 32
MODELL_MAX = 40
RE_NAME = re.compile(r"^[A-Za-z0-9 .()+-]{1,%d}$" % NAME_MAX)
RE_MODELL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,%d}$" % (MODELL_MAX - 1))

# Ein Modellbezeichner wie "gpt-6-astra": Familie, Version, Beiname(n).
RE_MODELL_SLUG = re.compile(r"^([a-z]+)-(\d+(?:\.\d+)*)((?:-[a-z0-9]+)*)$")


def modell_aus_slug(wert):
    """Aus einem Bezeichner einen lesbaren Namen machen.

        gpt-6-astra          -> GPT-6 Astra
        gpt-5.6-sol          -> GPT-5.6 Sol
        gpt-5.1-codex-max    -> GPT-5.1 Codex Max
        gpt-5.6-sol-20260801 -> GPT-5.6 Sol   (Datumsstempel faellt weg)

    Was kein Bezeichner ist -- "Astra 6", "Gemini 3.7 Flash", "o3" --,
    kommt unveraendert zurueck. Das Vorbild ist die Regel fuer Claude-
    Bezeichner in claude_rpc.py: eine Regel statt einer Liste, damit ein
    neues Modell nicht erst ein Update braucht, um ordentlich
    auszusehen. Ausnahmen, die die Regel falsch schriebe (o3, o4-mini),
    fuehrt der Codex-Connector in einer kurzen Ausnahmeliste.
    """
    if not isinstance(wert, str):
        return wert
    treffer = RE_MODELL_SLUG.match(wert.strip().lower())
    if not treffer:
        return wert.strip()
    familie, version, rest = treffer.groups()
    familie = familie.upper() if len(familie) <= 3 else familie.capitalize()
    teile = [t for t in rest.split("-") if t]
    # Ein reiner Zahlenblock am Ende ist ein Datumsstempel, kein Beiname.
    while teile and teile[-1].isdigit() and len(teile[-1]) >= 6:
        teile.pop()
    name = "%s-%s" % (familie, version)
    if teile:
        name += " " + " ".join(t.capitalize() for t in teile)
    return name


def modell_saeubern(wert):
    """Modellwert eines Produzenten annehmen -- oder None."""
    if not isinstance(wert, str):
        return None
    wert = wert.strip()
    return wert if RE_MODELL.match(wert) else None

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
    return [ordner / "beacons"
            for ordner in datenordner_kandidaten(datenordner, systemweit)]


def datenordner_kandidaten(datenordner, systemweit=True):
    """Alle Datenordner, die zu dieser Installation gehoeren koennen.

    Der eigene zuerst. Alles Weitere ist der Store-Umleitung geschuldet
    und faellt auf Linux weg.
    """
    ordner = [Path(datenordner)]
    if systemweit and os.name == "nt":
        profil = os.environ.get("USERPROFILE")
        if profil:
            lokal = Path(profil) / "AppData" / "Local"
            ordner.append(lokal / "ClaudeDiscordPresence")
            try:
                for paket in sorted((lokal / "Packages").glob("Claude_*")):
                    ordner.append(paket / "LocalCache" / "Local"
                                  / "ClaudeDiscordPresence")
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


def produzenten_datenordner():
    """Wohin ein Produzent schreibt -- SPEC-beacon-v1, Abschnitt 1.

    Die Schreibseite ist bewusst enger als die Leseseite: geschrieben
    wird genau ein Ordner, gelesen werden alle Kandidaten oben.

    Nicht ueber LOCALAPPDATA. Ein Prozess aus dem Microsoft Store bekommt
    diese Variable still umgeleitet, USERPROFILE dagegen nie. Codex-Hook,
    Antigravity-Waechter und der Pruefer fragen deshalb alle hier nach,
    statt je eine eigene Fassung dieser Regel zu pflegen -- drei Kopien
    derselben Zeilen waren es vor dem Umzug ins gemeinsame Repo.
    """
    eigen = os.environ.get("CLAUDE_RPC_DATA_DIR")
    if eigen:
        return Path(os.path.abspath(os.path.expanduser(eigen)))
    if os.name == "nt":
        profil = os.environ.get("USERPROFILE")
        if not profil:
            raise RuntimeError("USERPROFILE fehlt")
        return Path(profil) / "AppData" / "Local" / "ClaudeDiscordPresence"
    basis = (os.environ.get("XDG_DATA_HOME")
             or os.path.expanduser("~/.local/share"))
    return Path(basis) / "ClaudeDiscordPresence"


# Wer sendet, wenn Dienst und Extension gleichzeitig laufen?
#
# Der Mutex allein entscheidet nach "wer war zuerst da". Bei einem
# Autostart-Dienst und einem spaeter gestarteten Claude Desktop ist das
# ein Zufallsergebnis, und wer gerade sendet, sieht man von aussen
# nicht. Deshalb eine ausgesprochene Regel: der eigenstaendige Dienst
# hat Vorrang, die Extension weicht.
#
# Angesagt wird das ueber einen Herzschlag. Faellt der Dienst aus,
# uebernimmt die Extension nach einer Minute von selbst; startet er
# spaeter, weicht sie binnen einer Minute zurueck. Niemand muss sich
# eine Startreihenfolge merken.
SENDER_FRISCH = 60
ROLLEN_RANG = {"standalone": 2, "extension": 1}


def sender_datei(rolle):
    """Je Rolle eine eigene Datei -- und das ist der ganze Punkt.

    Vorher schrieben alle Beteiligten dieselbe sender.json. Gemessen am
    30.08.2026: die beiden Kandidatenordner sind physisch dieselbe Datei
    (gleiche st_ino UND st_dev, die Store-Umleitung zeigt auf dasselbe
    Ziel), und entdoppelt wurde nur ueber den Pfadtext. Jeder Prozess
    schrieb also seinen Eintrag und las Millisekunden spaeter genau
    diesen einen wieder -- den eigenen, den fremder_sender ueberspringt.
    Ergebnis: die Rangregel sah nie einen anderen und entschied nie
    etwas. Der Vorrang lief seit seiner Einfuehrung ins Leere; in
    Wahrheit entschied weiter der Mutex nach "wer zuerst zugreift".

    Der Punkt im Namen ist Absicht: der Beacon-Pool ueberliest Dateien
    mit Punkt im Stamm (siehe Pool.lesen).
    """
    sauber = rolle if RE_SLUG.match(rolle or "") else "unbekannt"
    return "sender.%s.json" % sauber


def sender_melden(datenordner, rolle, pid=None):
    """Diesen Prozess als sendende Instanz eintragen."""
    pfad = Path(datenordner) / sender_datei(rolle)
    daten = {
        "rolle": rolle,
        "pid": int(pid if pid is not None else os.getpid()),
        "updated_at": int(time.time()),
    }
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        # Zwischendatei je Prozess, nicht je Name. Teilen sich mehrere
        # Prozesse einen Zwischennamen, tritt sich das Umbenennen
        # gegenseitig auf die Fuesse: gemessen 2136 Fehlschlaege
        # ("Zugriff verweigert", "von einem anderen Prozess verwendet"),
        # davon 107 an einem Tag.
        tmp = pfad.with_name("%s.%d.tmp" % (pfad.name, daten["pid"]))
        tmp.write_text(json.dumps(daten), encoding="utf-8")
        os.replace(str(tmp), str(pfad))
    except OSError as exc:
        logging.warning("Senderkennung nicht schreibbar (%s)", exc)


def sender_abmelden(datenordner, rolle):
    """Eintrag entfernen, wenn dieser Prozess bewusst aufhoert."""
    try:
        (Path(datenordner) / sender_datei(rolle)).unlink(missing_ok=True)
    except OSError:
        pass


def fremder_sender(datenordner, eigene_rolle, eigene_pid=None,
                   jetzt=None, systemweit=True):
    """Sendet gerade ein hoeherrangiger Prozess? Dann dessen Eintrag.

    Durchsucht werden alle Kandidatenordner und alle Rollen. Die
    Ordnerliste kann auf dieselbe Datei zeigen (Store-Umleitung) -- das
    schadet nicht, es wird dann nur zweimal dasselbe gelesen.
    """
    jetzt = time.time() if jetzt is None else jetzt
    eigene_pid = os.getpid() if eigene_pid is None else eigene_pid
    eigener_rang = ROLLEN_RANG.get(eigene_rolle, 0)
    for ordner in datenordner_kandidaten(datenordner, systemweit):
        for rolle in ROLLEN_RANG:
            if ROLLEN_RANG[rolle] <= eigener_rang:
                continue
            try:
                roh = (ordner / sender_datei(rolle)).read_text(
                    encoding="utf-8")
                daten = json.loads(roh)
            except (OSError, ValueError):
                continue
            if not isinstance(daten, dict):
                continue
            zeit = daten.get("updated_at")
            if not isinstance(zeit, int) or jetzt - zeit > SENDER_FRISCH:
                continue
            if daten.get("pid") == eigene_pid:
                continue
            if ROLLEN_RANG.get(daten.get("rolle"), 0) > eigener_rang:
                return daten
    return None


def plan_saeubern(wert):
    """Abo-Bezeichnung eines Produzenten annehmen -- oder verwerfen.

    Kein Kuerzen, kein Ersetzen: was nicht passt, fliegt ganz raus. Ein
    stillschweigend zurechtgeschnittener Text waere genau die Art von
    Halbheit, die spaeter niemand mehr nachvollzieht.
    """
    if not isinstance(wert, str):
        return None
    wert = wert.strip()
    return wert if RE_PLAN.match(wert) else None


def usage_saeubern(wert):
    """Auslastung eines Produzenten annehmen -- ganze Prozent, 0 bis 100."""
    if not isinstance(wert, dict):
        return None
    sauber = {}
    for schluessel in USAGE_SCHLUESSEL:
        zahl = wert.get(schluessel)
        if isinstance(zahl, bool) or not isinstance(zahl, int):
            continue
        if 0 <= zahl <= 100:
            sauber[schluessel] = zahl
    return sauber or None


def pruefen(daten, slug):
    """Gibt den Eintrag zurueck oder None. Im Zweifel None (fail closed).

    Pflichtfelder muessen exakt stimmen. Zusatzfelder duerfen fehlen und
    werden einzeln geprueft: ein unbrauchbares Zusatzfeld verwirft nur
    sich selbst, nicht den ganzen Beacon -- sonst verschwaende ein
    Tippfehler im Abo-Namen die gesamte Anzeige des Clients.
    """
    if not isinstance(daten, dict):
        return None
    vorhanden = set(daten)
    if not FELDER <= vorhanden or not (vorhanden - FELDER) <= ZUSATZFELDER:
        return None
    if daten.get("v") != 1 or daten.get("client") != slug:
        return None
    # Zeile 1 der Presence ist dieser Name. Ein Name, der das Muster
    # nicht besteht, ist kein Name -- fail closed wie bei jedem
    # Pflichtfeld.
    name = daten.get("display_name")
    if not isinstance(name, str) or not RE_NAME.match(name):
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
    geprueft = dict(daten)
    # Das Modell steht in Zeile 2. Die Produzenten pruefen es schon;
    # hier ist die zweite Schleuse, die der Vertrag beschreibt. Ein
    # unbrauchbares Modell kostet nur das Modell, nicht den Beacon.
    if geprueft.get("model") is not None:
        geprueft["model"] = modell_saeubern(geprueft["model"])
    for schluessel, saeubern in (("plan", plan_saeubern),
                                 ("usage", usage_saeubern)):
        if schluessel in geprueft:
            sauber = saeubern(geprueft[schluessel])
            if sauber is None:
                geprueft.pop(schluessel)
            else:
                geprueft[schluessel] = sauber
    return geprueft


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


# Nachlauffrist. Ein Client, dessen Beacon von "working" auf "waiting"
# gefallen ist, bleibt so lange in der aktiven Menge. Der Grund steht in
# aktive(); die Zahl ist ein Kompromiss: laenger als die Luecke zwischen
# zwei Hook-Ereignissen, kuerzer als ein echter Uebergang in den
# Leerlauf.
NACHLAUF = 25

# Wann ein Client zuletzt wirklich gearbeitet hat, je Client. Von
# aktive() gepflegt; Tests geben ein eigenes Gedaechtnis mit.
_ZULETZT_AKTIV = {}


def arbeitet(eintrag):
    """Arbeit im Sinne der Rahmenwahl: working -- oder die Rueckfrage.

    "waiting_approval" heisst, der Agent wartet auf den Nutzer. Das ist
    der Moment groesster Aufmerksamkeit, nicht Leerlauf.
    """
    return (eintrag["state"] == "working"
            or eintrag["action"] == "waiting_approval")


def aktive(eintraege, jetzt=None, gedaechtnis=None):
    """Alle Clients, die gerade wirklich etwas tun -- in fester Ordnung.

    Zwei Anlaeufe waren vorher falsch, und beide aus demselben Grund:
    sie suchten EINEN Gewinner.

    Der erste nahm den juengsten "working"-Eintrag. Die Clients
    schreiben aber unterschiedlich oft -- Claude alle fuenf Sekunden,
    Codex nur bei Hook-Ereignissen. Nach jedem Codex-Ereignis war
    Claudes Zeitstempel Sekundenbruchteile spaeter wieder der juengste.
    Es gewann nicht, wer arbeitet, sondern wer am oeftesten schreibt.

    Der zweite gab dem bisherigen Besitzer Vorrang. Damit hielt Claude
    den Rahmen fest, solange irgendeine Taetigkeit erkannt wurde -- und
    das ist waehrend einer Cowork-Sitzung durchgehend der Fall. Codex
    arbeitete daneben zweieinhalb Minuten und kam nie vor.

    Arbeiten mehrere gleichzeitig, ist die ehrliche Anzeige nicht "einer
    von beiden", sondern beide nacheinander. Wer nur offen ist und
    wartet, bleibt draussen -- ein ruhender Nachbar soll niemanden
    verdraengen, der tippt.

    Sortiert nach Client-Namen, damit die Reihenfolge nicht bei jedem
    Durchlauf springt: der Wechsel haengt an der Uhrzeit, und eine
    wechselnde Reihenfolge liesse die Anzeige zufaellig hin und her
    hopsen.

    Der dritte Fehler, gemessen am 06.09.2026: Codex fiel zwischen zwei
    Hook-Ereignissen fuer eine Sekunde auf "waiting" -- Genehmigungs-
    frage, Ende eines Zuges, Luecke zwischen zwei Werkzeugaufrufen --
    und in genau dieser Sekunde galt niemand mehr als arbeitend. Das
    volle Karussell sprang an, und Claude, der die ganze Zeit untaetig
    wartete, stand in der Presence. Deshalb zwei Ergaenzungen:

    - "waiting_approval" zaehlt als Arbeit (siehe arbeitet()).
    - Eine BEFRISTETE Nachlauffrist: wer zuletzt vor hoechstens NACHLAUF
      Sekunden gearbeitet hat und jetzt "waiting" meldet, bleibt drin.
      Die Frist beginnt erst nach echter Arbeit und laeuft ohne neues
      Ereignis ab. Unbefristet war das in Fassung 1.6.2 schon einmal
      gescheitert -- der bisherige Besitzer bekam Vorrang, und Claude
      gab den Rahmen nie wieder ab. Ein Leerlauf ("idle") beendet die
      Frist sofort: wer sein Programm zumacht, soll auch gehen.

    Das Gedaechtnis ist ein kleines Woerterbuch "Client -> zuletzt
    gearbeitet um"; Eintraege, die ablaufen oder deren Client fehlt,
    werden bei jedem Aufruf entfernt.
    """
    jetzt = time.time() if jetzt is None else jetzt
    merk = _ZULETZT_AKTIV if gedaechtnis is None else gedaechtnis
    ergebnis = []
    gesehen = set()
    for e in eintraege:
        client = e["client"]
        gesehen.add(client)
        if arbeitet(e):
            merk[client] = jetzt
            ergebnis.append(dict(e, aktiv=True))
        elif (e["state"] == "waiting" and client in merk
              and jetzt - merk[client] <= NACHLAUF):
            ergebnis.append(dict(e, aktiv=True))
    for client in list(merk):
        if client not in gesehen or jetzt - merk[client] > NACHLAUF:
            del merk[client]
    return sorted(ergebnis, key=lambda e: e["client"])


def karten(eigen, fremde, cfg=None):
    """Alle Anzeigen, zwischen denen im Ruhezustand gewechselt wird.

    Eine Karte ist eine vollstaendige Anzeige: Zeile 1, Zeile 2 und die
    Sitzung, zu der die Laufzeit gehoert. Ein Client mit drei Angaben in
    Zeile 2 liefert drei Karten -- so wandert die Anzeige erst durch
    seine eigenen Angaben und dann weiter zum naechsten Client.

    Zeile 1 und Zeile 2 stammen immer vom selben Client. Ein Mischbild
    aus der Taetigkeit des einen und dem Abo des anderen waere schlimmer
    als gar keine Anzeige.

    "eigen" ist der Daemon selbst und darf None sein (Claude laeuft
    nicht) -- dann wandert die Anzeige nur durch die fremden Clients.
    """
    rotieren = (((cfg or {}).get("state_line") or {}).get("mode", "alternate")
                == "alternate")

    def zeilen_von(liste):
        if not liste:
            return [None]
        if not rotieren:
            return [" · ".join(liste)]
        return liste

    ergebnis = []
    if eigen is not None:
        for zeile in zeilen_von(eigen.get("zeilen")):
            ergebnis.append({
                "client": "claude",
                "details": eigen["details"],
                "zeile": zeile,
                "start": eigen.get("start"),
                "aktiv": bool(eigen.get("aktiv")),
            })
    for eintrag in sorted(fremde, key=lambda e: e["client"]):
        # Laufzeit nur, solange auch wirklich gearbeitet wird. Der
        # session_start eines ruhenden Clients ist der Beginn seiner
        # letzten Sitzung, nicht die Dauer von irgendetwas: gemessen am
        # 30.08.2026 stand neben einem untaetigen Antigravity ein
        # Zaehler von 19,2 Stunden. Eine Zahl, die niemand erklaeren
        # kann, ist schlechter als keine.
        # aktive() markiert, wen es fuer arbeitend haelt -- auch in der
        # Nachlauffrist. Sonst verschwaende der Zaehler fuer die Dauer
        # der Frist und kaeme danach wieder.
        laeuft = bool(eintrag.get("aktiv")) or arbeitet(eintrag)
        for zeile in zeilen_von(zeilen_sitzung(eintrag, cfg)):
            ergebnis.append({
                "client": eintrag["client"],
                "details": zeile_taetigkeit(eintrag),
                "zeile": zeile,
                "start": eintrag.get("session_start") if laeuft else None,
                "aktiv": laeuft,
            })
    return ergebnis


def karte_waehlen(liste, jetzt, schritt=20):
    """Welche Karte gehoert zu diesem Zeitpunkt?

    Die Untergrenze von 15 Sekunden ist keine Geschmacksfrage: Discord
    leert die Presence, statt zu drosseln, wenn oefter aktualisiert wird
    (discord-api-docs#668).
    """
    if not liste:
        return None
    try:
        schritt = max(15, int(schritt))
    except (TypeError, ValueError):
        schritt = 20
    return liste[int(jetzt / schritt) % len(liste)]


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


VENDOR_PRAEFIXE = ("Google ", "OpenAI ", "Anthropic ", "Microsoft ", "Meta ")


def kurzname(eintrag):
    """Der Produktname ohne Hersteller.

    Zeile 1 nennt den Client bereits vollstaendig -- "Google
    Antigravity". Zeile 2 direkt darunter noch einmal mit "using Google
    Antigravity with ..." zu beginnen, verbraucht die halbe Zeile fuer
    eine Angabe, die eine Zeile hoeher schon steht. Also nur "using
    Antigravity with Gemini 3.7 Flash High".

    Bleibt nach dem Kuerzen nichts uebrig, gilt der volle Name: ein
    Client, der schlicht "Google" hiesse, soll nicht namenlos werden.
    """
    name = eintrag.get("display_name") or eintrag.get("client") or ""
    for praefix in VENDOR_PRAEFIXE:
        if name.startswith(praefix) and len(name) > len(praefix):
            return name[len(praefix):]
    return name


def zeilen_sitzung(eintrag, cfg=None):
    """Zeile 2 als Liste: alles, was ueber diesen Client bekannt ist.

    Der Aufrufer wechselt zwischen den Teilen durch, so wie Claude
    zwischen Sitzung, Auslastung und Abo wechselt.

    Alles hier kommt aus dem Fenster des jeweiligen Clients oder aus der
    Konfiguration -- nie aus einer Anbieter-Schnittstelle und nie aus
    einem Zugangstoken. Antigravity zeigt Plan und Limits in
    "Einstellungen -> Models & Usage", und genau von dort liest sein
    Waechter sie ab, so wie Claude sie aus seinem Nutzungsfenster liest.
    """
    cfg = cfg or {}
    teile = []
    if eintrag.get("model"):
        teile.append("using %s with %s"
                     % (kurzname(eintrag), eintrag["model"]))

    # Auslastung. Beschriftet wie bei Claude, damit in derselben Zeile
    # nicht zwei Sprachen stehen.
    usage = eintrag.get("usage") or {}
    beschriftung = cfg.get("local_usage") or {}
    stuecke = []
    for schluessel, vorgabe, name in (
            ("five_hour", "5h", "label_5h"),
            ("week", "Woche", "label_week")):
        if schluessel in usage:
            stuecke.append("%s %d%%" % (beschriftung.get(name, vorgabe),
                                        usage[schluessel]))
    if stuecke:
        teile.append(" · ".join(stuecke))

    # Abo. Der abgelesene Wert gilt; der von Hand eingetragene greift,
    # solange keiner abgelesen wurde -- dieselbe Regel wie bei Claude,
    # wo plan_override nur bis zum ersten Blick ins Nutzungsfenster gilt.
    marke = eintrag.get("plan")
    if not marke:
        hand = (cfg.get("client_plans") or {}).get(eintrag["client"])
        if isinstance(hand, str) and hand.strip():
            marke = hand.strip()
    if marke:
        vorlage = (cfg.get("plan") or {}).get("template", "Abonnement: {plan}")
        teile.append(vorlage.replace("{plan}", marke))
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


EIGENER_NAME = "Claude Desktop"


def eigenen_schreiben(datenordner, state, action, model, session_start,
                      file_kind=None, display_name=EIGENER_NAME):
    """Der Daemon meldet sich selbst als Produzent.

    Er koennte seinen Zustand auch direkt in den Rahmenwaehler reichen.
    Dann waere er dort aber ein Sonderfall neben den anderen Clients --
    und Sonderfaelle in der Mehrprozess-Koordination sind in diesem
    Projekt schon mehrfach teuer geworden. So gilt fuer alle drei
    dieselbe Regel und derselbe Verfall.
    """
    ordner = datenordner / "beacons"
    # Der Name kommt aus der Konfiguration. Besteht er das Muster nicht,
    # wuerde der Pool den eigenen Beacon verwerfen -- dann gilt die Vorgabe.
    if not isinstance(display_name, str) or not RE_NAME.match(display_name):
        display_name = EIGENER_NAME
    daten = {
        "v": 1,
        "client": "claude",
        "display_name": display_name,
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
