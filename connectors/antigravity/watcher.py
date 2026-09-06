#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Beacon-Connector fuer Discord Rich Presence (SPEC-beacon-v1).

Liest den Zustand laufender Google-Antigravity-Sitzungen aus dem
Transkript (transcript.jsonl) und schreibt atomar eine Beacon-Datei
fuer den zentralen RP-Master.

Verbindlicher Vertrag: SPEC-beacon-v1.md
Kein Netzzugriff, reine Positivliste fuer Datenschutz.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Der Datenordner ist die Regel des Senders (beacons.py im Repo-Stamm),
# nicht des Waechters: beide muessen denselben Ort meinen. Gefunden wird
# der Stamm relativ zu dieser Datei.
HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent.parent
if str(WURZEL) not in sys.path:
    sys.path.insert(0, str(WURZEL))
import beacons  # noqa: E402

# Feste Erlaubnislisten gemaess SPEC-beacon-v1.md
ZUSTAENDE = {"working", "waiting", "idle"}
AKTIONEN = {
    "thinking", "reading", "editing", "running_tests",
    "running_command", "web_search", "waiting_approval", "idle",
}
DATEIARTEN = {
    "python", "javascript", "typescript", "markdown", "json",
    "yaml", "html", "css", "shell", "powershell",
    "csharp", "cpp", "rust", "go", "java",
    "sql", "text", "config", "image", "data", "other",
}

# Dateiendungs-Zuordnung fuer file_kind
# Nur die Endung wird ausgewertet; der Pfad wird sofort verworfen.
ENDUNG_ZU_DATEIART = {
    # Python
    ".py": "python", ".pyw": "python", ".pyi": "python",
    # JavaScript
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    # TypeScript
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "typescript",
    # Markdown
    ".md": "markdown", ".markdown": "markdown", ".mdown": "markdown", ".mkdn": "markdown",
    # JSON
    ".json": "json", ".jsonl": "json", ".json5": "json", ".ipynb": "json",
    # YAML
    ".yaml": "yaml", ".yml": "yaml",
    # HTML
    ".html": "html", ".htm": "html", ".xhtml": "html", ".vue": "html", ".svelte": "html",
    # CSS
    ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    # Shell
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    # PowerShell & Windows-Skripte
    ".ps1": "powershell", ".psm1": "powershell", ".psd1": "powershell", ".bat": "powershell", ".cmd": "powershell",
    # C#
    ".cs": "csharp",
    # C / C++
    ".cpp": "cpp", ".c": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    # Rust
    ".rs": "rust",
    # Go
    ".go": "go",
    # Java & JVM
    ".java": "java", ".kt": "java", ".kts": "java", ".scala": "java",
    # SQL
    ".sql": "sql",
    # Text & Dokumente
    ".txt": "text", ".log": "text", ".rst": "text", ".asciidoc": "text", ".org": "text", ".tex": "text", ".pdf": "text",
    # Konfiguration
    ".toml": "config", ".ini": "config", ".cfg": "config", ".conf": "config", ".env": "config",
    ".pbtxt": "config", ".editorconfig": "config", ".prettierrc": "config", ".eslintrc": "config",
    # Bilder
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".svg": "image",
    ".webp": "image", ".bmp": "image", ".ico": "image", ".tiff": "image",
    # Daten & Datenbanken
    ".csv": "data", ".tsv": "data", ".parquet": "data", ".arrow": "data",
    ".xml": "data", ".proto": "data", ".pb": "data", ".db": "data", ".sqlite": "data", ".sqlite3": "data",
}

# Modellnamen: dasselbe Tor wie bei Claude und Codex. Nur Buchstaben,
# Ziffern, Punkt, Bindestrich, Unterstrich, Leerzeichen; hoechstens 40.
RE_MODELL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,39}$")

# Regex zur Erkennung von Test-Befehlen bei run_command
RE_TEST_BEFEHL = re.compile(
    r"(?:npm\s+(?:run\s+)?test|pytest|cargo\s+test|go\s+test|dotnet\s+test|python\s+-m\s+unittest|vitest|jest)",
    re.IGNORECASE,
)


def ermittle_beacon_ordner() -> Path:
    """Der Beacon-Zielordner gemaess SPEC-beacon-v1, Abschnitt 1.

    Die Regel lebt in beacons.produzenten_datenordner: erst
    CLAUDE_RPC_DATA_DIR, sonst der nicht umgeleitete Profilordner.
    """
    p = beacons.produzenten_datenordner() / "beacons"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ermittle_antigravity_basis() -> Path:
    """Gibt das Basisverzeichnis von Antigravity zurueck."""
    return Path(os.path.expanduser("~/.gemini/antigravity"))


_PROZESS_CACHE = {"zeit": 0.0, "antwort": False}


def antigravity_laeuft(hoechstalter: float = 15.0) -> bool:
    """Ist Antigravity ueberhaupt offen?

    Der Waechter startet mit der Anmeldung und laeuft auch dann weiter,
    wenn Antigravity gar nicht auf ist. Ohne diese Frage wuerde sein
    Herzschlag "Google Antigravity" dauerhaft in die Presence schreiben,
    obwohl das Programm zu ist.

    Die Antwort wird kurz zwischengespeichert: die Schleife laeuft im
    Sekundentakt, und eine Prozessliste pro Sekunde waere Verschwendung.
    """
    jetzt = time.time()
    if jetzt - _PROZESS_CACHE["zeit"] < hoechstalter:
        return _PROZESS_CACHE["antwort"]

    antwort = False
    try:
        if os.name == "nt":
            # Ohne text=True, und der Vergleich laeuft auf Bytes.
            #
            # tasklist antwortet in der Systemsprache und in der
            # Konsolen-Codepage. Auf einem deutschen Windows lautet die
            # Fehlanzeige "Es werden keine Aufgaben ... ausgefuehrt" --
            # mit einem Umlaut in Codepage 850. Python decodierte das
            # als cp1252 und warf UnicodeDecodeError. Die Ausnahme fiel
            # in den Auffangblock, die Antwort war zufaellig richtig
            # (False), aber aus dem falschen Grund. Auf einem System mit
            # anderer Codepage haette dasselbe "laeuft" bedeuten koennen.
            ausgabe = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Antigravity.exe", "/NH"],
                capture_output=True, timeout=10,
                creationflags=0x08000000,
            ).stdout or b""
            antwort = b"antigravity.exe" in ausgabe.lower()
        else:
            for eintrag in os.listdir("/proc"):
                if not eintrag.isdigit():
                    continue
                try:
                    with open("/proc/%s/comm" % eintrag, encoding="utf-8") as h:
                        if "antigravity" in h.read().strip().lower():
                            antwort = True
                            break
                except OSError:
                    continue
    except Exception:
        # Im Zweifel "laeuft nicht": ein fehlender Beacon verfaellt von
        # selbst, ein faelschlich geschriebener bliebe stehen.
        antwort = False

    _PROZESS_CACHE["zeit"] = jetzt
    _PROZESS_CACHE["antwort"] = antwort
    return antwort


def ermittle_file_kind(zielpfad: Optional[str]) -> Optional[str]:
    """Ermittelt ausschliesslich aus der Dateiendung die file_kind-Marke.

    Datenschutzgarantie: Der Pfad wird hier sofort verworfen.
    """
    if not zielpfad:
        return None
    try:
        # Nur Endung extrahieren (z. B. .py)
        ext = os.path.splitext(zielpfad.strip().rstrip("/\\"))[1].lower()
        if not ext:
            return "other"
        return ENDUNG_ZU_DATEIART.get(ext, "other")
    except Exception:
        return "other"


def parse_modell_name(text: Optional[str]) -> Optional[str]:
    """Extrahiert lesbaren Modellnamen aus Einstellungs-Aenderungen.

    Wichtig: Einstellungszeilen enthalten oft altes und neues Modell
    ('from X to Y'). Es wird ausschliesslich der Teil nach 'to ' ausgewertet.
    """
    if not text:
        return None
    # Falls Richtungsangabe vorhanden, nur das Zielmodell nach 'to ' pruefen
    zieltext = text
    if " to " in text:
        zieltext = text.split(" to ", 1)[1]
    # "(High)" ist die Denkstufe, "<...>" der Rahmen der Systemmeldung --
    # beides gehoert nicht zum Namen.
    for trenner in ("(", "<"):
        zieltext = zieltext.split(trenner, 1)[0]
    zieltext = zieltext.strip().rstrip(".")
    # Keine Liste bekannter Namen mehr: ein neues Modell soll sich
    # selbst erkennen. Das Muster laesst nur Zeichen durch, aus denen
    # sich kein Satz bauen laesst; alles andere wird verworfen.
    if RE_MODELL.match(zieltext):
        return zieltext
    return None


class AntigravityWatcher:
    """Beobachtet Antigravity-Transkripte und publiziert den Beacon."""

    def __init__(self, intervall: float = 1.0, herzschlag_intervall: float = 5.0,
                 ruhe_herzschlag: float = 60.0):
        self.intervall = intervall
        self.herzschlag_intervall = herzschlag_intervall
        # Deutlich unter der Verfallsgrenze des Masters (900 s), aber
        # selten genug, dass ein ruhendes Antigravity nichts kostet.
        self.ruhe_herzschlag = ruhe_herzschlag
        self.beacon_ordner = ermittle_beacon_ordner()
        self.beacon_datei = self.beacon_ordner / "antigravity.json"
        self.tmp_datei = self.beacon_ordner / "antigravity.json.tmp"
        self.antigravity_basis = ermittle_antigravity_basis()
        self.brain_dir = self.antigravity_basis / "brain"

        # Zustandsspeicher
        self.aktuelle_datei: Optional[Path] = None
        self.file_pos: int = 0
        self.letzter_write_zeitpunkt: float = 0.0
        self.letzte_transkript_zeit: float = 0.0
        self.session_start: Optional[int] = None
        self.aktueller_state: str = "idle"
        self.aktuelle_action: str = "idle"
        self.aktuelles_file_kind: Optional[str] = None
        # Vorgabe ist None gemaess Review (keine erfundenen/geratenen Vorgaben)
        self.aktuelles_modell: Optional[str] = None

        # Letzter geschriebener Stand (fuer Drosselung)
        self.letzter_beacon: Optional[Dict[str, Any]] = None

        # Aus dem Fenster abgelesen, mit Altersvermerk.
        self.abo: Optional[str] = None
        self.abo_zeit: int = 0
        self.auslastung: Optional[Dict[str, int]] = None
        self.auslastung_zeit: int = 0
        self.hoechstalter: int = 180 * 60
        self.abo_hoechstalter: int = 30 * 24 * 3600
        self.letzter_fensterblick: float = 0.0
        self.fensterblick_takt: float = 20.0
        self.fenster_moeglich: bool = True

    def beacon_entfernen(self):
        """Eigene Beacon-Datei loeschen, wenn das Programm zu ist.

        Nur beim ersten Mal Arbeit, danach ist nichts mehr da. Der
        Zustand wird zurueckgesetzt, damit beim naechsten Start von
        Antigravity wieder sauber von vorn gemeldet wird.
        """
        try:
            if self.beacon_datei.exists():
                self.beacon_datei.unlink()
        except OSError:
            return
        self.aktueller_state = "idle"
        self.aktuelle_action = "idle"
        self.aktuelle_datei = None
        self.file_pos = 0
        self.session_start = None
        self.letzter_beacon = None

    def fensterblick(self):
        """Einstellungsfenster ansehen, falls es gerade offen ist.

        Der Blick kostet einen Baumdurchlauf, deshalb hoechstens alle
        20 Sekunden. Traegt uiautomation auf diesem Rechner nicht,
        wird es genau einmal versucht und danach nie wieder -- ein
        Waechter, der im Sekundentakt in denselben Fehler laeuft, ist
        schlimmer als einer, der auf die Angabe verzichtet.
        """
        if not self.fenster_moeglich:
            return
        jetzt = time.time()
        if jetzt - self.letzter_fensterblick < self.fensterblick_takt:
            return
        self.letzter_fensterblick = jetzt
        try:
            import fenster as fensterleser
            gelesen = fensterleser.lies_alle()
        except Exception:
            self.fenster_moeglich = False
            return
        if gelesen.get("plan"):
            self.abo = gelesen["plan"]
            self.abo_zeit = int(jetzt)
        if gelesen.get("usage"):
            self.auslastung = gelesen["usage"]
            self.auslastung_zeit = int(jetzt)
        # Das Modell steht in der Eingabezeile und ist damit verlaesslicher
        # als das Warten auf einen Modellwechsel im Transkript.
        if gelesen.get("model"):
            self.aktuelles_modell = gelesen["model"]

    def suche_neuestes_transkript(self) -> Optional[Path]:
        """Findet das juengste transcript.jsonl nach Aenderungszeit."""
        if not self.brain_dir.exists():
            return None

        neueste_datei: Optional[Path] = None
        neueste_mtime: float = -1.0

        try:
            # Iteriere ueber alle Konversationsordner
            for convo_dir in self.brain_dir.iterdir():
                if not convo_dir.is_dir():
                    continue
                transkript = convo_dir / ".system_generated" / "logs" / "transcript.jsonl"
                if transkript.is_file():
                    try:
                        mtime = transkript.stat().st_mtime
                        if mtime > neueste_mtime:
                            neueste_mtime = mtime
                            neueste_datei = transkript
                    except OSError:
                        continue
        except Exception:
            pass

        return neueste_datei

    def schreibe_beacon(self, state: str, action: str, file_kind: Optional[str] = None, force_heartbeat: bool = False):
        """Schreibt atomar eine Beacon-Datei gemaess SPEC-beacon-v1."""
        jetzt = int(time.time())

        # Validierung gegen geschlossene Wertelisten
        if state not in ZUSTAENDE:
            state = "idle"
        if action not in AKTIONEN:
            action = "idle"
        if action not in ("reading", "editing"):
            file_kind = None
        elif file_kind not in DATEIARTEN:
            file_kind = "other"

        # Ratenbegrenzung: Maximal einmal pro Sekunde, ausser bei echtem State-Wechsel oder Herzschlag
        if not force_heartbeat:
            if (time.time() - self.letzter_write_zeitpunkt < 1.0 and
                    state == self.aktueller_state and
                    action == self.aktuelle_action and
                    file_kind == self.aktuelles_file_kind):
                return

        payload = {
            "v": 1,
            "client": "antigravity",
            "display_name": "Google Antigravity",
            "state": state,
            "action": action,
            "model": self.aktuelles_modell,
            "session_start": self.session_start,
            "updated_at": jetzt,
            "file_kind": file_kind,
        }
        # Abo und Auslastung stehen nur im Einstellungsfenster und
        # altern danach. Ohne Verfall stuende in sechs Stunden noch die
        # Zahl von jetzt in der Presence -- lieber keine Zahl als eine
        # falsche. Dieselbe Regel gilt bei Claude fuer das Modell-Limit.
        # Zwei Grenzen: eine Auslastung von vor drei Stunden ist eine
        # Falschaussage, eine Abo-Bezeichnung von vor drei Stunden ist
        # einfach die Abo-Bezeichnung.
        if self.abo and jetzt - self.abo_zeit <= self.abo_hoechstalter:
            payload["plan"] = self.abo
        if (self.auslastung
                and jetzt - self.auslastung_zeit <= self.hoechstalter):
            payload["usage"] = dict(self.auslastung)

        # Atomares Schreiben via .tmp -> replace
        try:
            inhalt = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            data_bytes = inhalt.encode("utf-8")
            if len(data_bytes) > 4096:
                # Sicherheitsgrenze aus SPEC
                return

            with open(self.tmp_datei, "wb") as f:
                f.write(data_bytes)
                f.flush()
                os.fsync(f.fileno())

            os.replace(self.tmp_datei, self.beacon_datei)
            self.letzter_write_zeitpunkt = time.time()
            self.aktueller_state = state
            self.aktuelle_action = action
            self.aktuelles_file_kind = file_kind
            self.letzter_beacon = payload
        except Exception:
            # Connector darf bei I/O-Fehlern nicht abstuerzen
            pass

    def verarbeite_zeile(self, raw_line: str) -> bool:
        """Parst eine Transkriptzeile streng ueber Positivliste."""
        try:
            obj = json.loads(raw_line)
        except Exception:
            # Unvollstaendige Zeile (halber Schreibvorgang)
            return False

        if not isinstance(obj, dict):
            return True

        # Positivliste: Nur diese Metadaten duerfen verarbeitet werden
        schritt_typ = obj.get("type")
        tool_calls = obj.get("tool_calls") or []

        # Modell-Aktualisierung ausschliesslich aus SYSTEM_MESSAGE / EPHEMERAL_MESSAGE
        # Prompts (USER_INPUT) und Antworten (PLANNER_RESPONSE) werden NIE nach content gelesen!
        if schritt_typ in ("SYSTEM_MESSAGE", "EPHEMERAL_MESSAGE"):
            content = obj.get("content")
            if isinstance(content, str) and "Model Selection" in content:
                # Auch None uebernehmen: ein alter Wert bleibt nicht stehen.
                self.aktuelles_modell = parse_modell_name(content)

        self.letzte_transkript_zeit = time.time()

        # 1. Benutzer-Eingabe -> Modell faengt an nachzudenken
        if schritt_typ == "USER_INPUT":
            self.schreibe_beacon(state="working", action="thinking", file_kind=None)
            return True

        # 2. Werkzeug-Ausfuehrung / Schritte
        if tool_calls and isinstance(tool_calls, list):
            erster_call = tool_calls[0] if tool_calls else {}
            tool_name = erster_call.get("name", "")
            args = erster_call.get("args") or {}

            if tool_name == "view_file":
                # Nur Endung extrahieren, Pfad sofort verwerfen
                pfad = args.get("AbsolutePath")
                art = ermittle_file_kind(pfad)
                self.schreibe_beacon(state="working", action="reading", file_kind=art)
                return True

            elif tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                pfad = args.get("TargetFile")
                art = ermittle_file_kind(pfad)
                self.schreibe_beacon(state="working", action="editing", file_kind=art)
                return True

            elif tool_name == "run_command":
                cmd = args.get("CommandLine", "")
                if isinstance(cmd, str) and RE_TEST_BEFEHL.search(cmd):
                    self.schreibe_beacon(state="working", action="running_tests", file_kind=None)
                else:
                    self.schreibe_beacon(state="working", action="running_command", file_kind=None)
                return True

            elif tool_name in ("search_web", "read_url_content"):
                self.schreibe_beacon(state="working", action="web_search", file_kind=None)
                return True

            elif tool_name == "ask_question":
                self.schreibe_beacon(state="waiting", action="waiting_approval", file_kind=None)
                return True

            else:
                # Unbekannte oder sonstige Werkzeuge
                self.schreibe_beacon(state="working", action="running_command", file_kind=None)
                return True

        # 3. Antwort ohne Werkzeugaufruf abgeschlossen
        if schritt_typ == "PLANNER_RESPONSE" and not tool_calls:
            # Der Zug ist fertig -- das ist Leerlauf, keine Freigabe.
            #
            # Hier stand "waiting_approval", und der Master macht daraus
            # woertlich "waiting for approval". In der Presence stand
            # also, Antigravity warte auf eine Freigabe, obwohl niemand
            # um etwas gebeten worden war. Auf Freigabe wartet es nur
            # beim Werkzeug ask_question, und das hat seinen eigenen
            # Zweig weiter oben.
            self.schreibe_beacon(state="waiting", action="idle", file_kind=None)
            return True

        return True

    def initialisiere_neuestes_transkript(self):
        """Liest ein bereits existierendes Transkript bis zum aktuellen Stand ein."""
        if not self.aktuelle_datei or not self.aktuelle_datei.exists():
            return
        try:
            with open(self.aktuelle_datei, "r", encoding="utf-8", errors="replace") as f:
                for zeile in f:
                    z = zeile.strip()
                    if z:
                        self.verarbeite_zeile(z)
                self.file_pos = f.tell()
        except Exception:
            pass

    def schritt(self):
        """Ein Pruefzyklus (ca. 1s)."""
        # Ist Antigravity zu, hat dieser Waechter nichts zu melden --
        # und zwar gar nichts, nicht einmal "idle".
        #
        # Vorher war nur der Herzschlag an diese Frage gebunden. Die
        # Zustandswechsel weiter unten schrieben trotzdem: startet der
        # Waechter neu, liest er das letzte Transkript ein, landet nach
        # drei Minuten Inaktivitaet bei "idle" und schreibt das einmal
        # heraus. Damit stand ein geschlossenes Antigravity fuer weitere
        # 15 Minuten in der Presence. Am 23.08.2026 gemessen: kein
        # Antigravity-Prozess, Beacon 269 Sekunden alt.
        #
        # Die Beacon-Datei wird beim Schliessen entfernt, statt auf den
        # Verfall zu warten. Wer sein Programm zumacht, erwartet, dass
        # es sofort verschwindet, und nicht in einer Viertelstunde.
        if not antigravity_laeuft():
            self.beacon_entfernen()
            return

        self.fensterblick()
        neueste = self.suche_neuestes_transkript()

        # Sitzungswechsel erkennen
        if neueste != self.aktuelle_datei:
            self.aktuelle_datei = neueste
            self.file_pos = 0
            if neueste and neueste.exists():
                try:
                    self.session_start = int(neueste.stat().st_mtime)
                except OSError:
                    self.session_start = int(time.time())
                self.initialisiere_neuestes_transkript()
            else:
                self.session_start = None

        if not self.aktuelle_datei or not self.aktuelle_datei.exists():
            # Kein Transkript verfuegbar -> Idle
            if self.aktueller_state != "idle":
                self.schreibe_beacon(state="idle", action="idle", file_kind=None)
            return

        # Anhaengend aus dem Transkript lesen (tail)
        try:
            with open(self.aktuelle_datei, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self.file_pos)
                while True:
                    cur_pos = f.tell()
                    zeile = f.readline()
                    if not zeile:
                        break
                    # Vollstaendigkeit der Zeile pruefen (muss mit Newline enden)
                    if not zeile.endswith("\n"):
                        # Unvollstaendige Zeile -> zurueckspulen und auf naechsten Zyklus warten
                        f.seek(cur_pos)
                        break

                    zeile_clean = zeile.strip()
                    if zeile_clean:
                        if self.verarbeite_zeile(zeile_clean):
                            self.file_pos = f.tell()
                        else:
                            # Fehlerhaftes JSON (Streaming-Luecke) -> zurueckspulen
                            f.seek(cur_pos)
                            break
                    else:
                        self.file_pos = f.tell()
        except Exception:
            pass

        # Timeout- und Herzschlaglogik
        jetzt = time.time()
        inaktivitaet = jetzt - self.letzte_transkript_zeit if self.letzte_transkript_zeit > 0 else 9999

        if inaktivitaet > 180:
            # Nach 3 Minuten Inaktivitaet -> Idle
            if self.aktueller_state != "idle":
                self.schreibe_beacon(state="idle", action="idle", file_kind=None)
        elif inaktivitaet > 30:
            # Nach 30 s ohne neuen Schritt: nicht mehr "arbeitet", aber
            # auch keine Behauptung darueber, WORAUF gewartet wird.
            #
            # Hier stand "waiting_approval". Das war die haeufigste der
            # drei Quellen fuer diesen Zustand und zugleich die
            # unehrlichste: gemessen wird blosse Stille im Transkript.
            # Die kann alles heissen -- langer Modelllauf, langsamer
            # Befehl, beendeter Zug. Von einer Freigabe weiss der Code an
            # dieser Stelle nichts. In der Presence stand trotzdem
            # "waiting for approval".
            if self.aktueller_state == "working":
                self.schreibe_beacon(state="waiting", action="idle", file_kind=None)

        # Herzschlag. Bei Arbeit alle herzschlag_intervall Sekunden
        # (SPEC <= 20s), im Ruhezustand seltener -- aber eben nicht nie.
        #
        # Das "nie" war ein echter Fehler: der Master laesst einen Beacon
        # nach 900 Sekunden ohne Erneuerung fallen. Ein einmal
        # geschriebener Ruhe-Beacon verschwand deshalb nach einer
        # Viertelstunde, und Antigravity fiel lautlos aus der Anzeige,
        # obwohl das Programm offen war. Am 21.08.2026 gemessen: alle
        # drei Clients ruhig, sichtbar war nur Claude Desktop.
        #
        # Geschrieben wird nur, solange Antigravity wirklich laeuft.
        # Sonst bliebe der Name in der Presence stehen, bis der Waechter
        # endet -- und der endet erst mit der Abmeldung.
        if self.aktueller_state != "idle":
            faellig = self.herzschlag_intervall
        elif antigravity_laeuft():
            faellig = self.ruhe_herzschlag
        else:
            return
        if jetzt - self.letzter_write_zeitpunkt >= faellig:
            self.schreibe_beacon(
                state=self.aktueller_state,
                action=self.aktuelle_action,
                file_kind=self.aktuelles_file_kind,
                force_heartbeat=True,
            )

    def run(self):
        """Hauptschleife des Watchers."""
        try:
            # Ersten Schritt sofort ausfuehren
            self.schritt()
            while True:
                time.sleep(self.intervall)
                self.schritt()
        except KeyboardInterrupt:
            # Sauberer Ausstieg
            self.schreibe_beacon(state="idle", action="idle", file_kind=None, force_heartbeat=True)


if __name__ == "__main__":
    watcher = AntigravityWatcher(intervall=1.0, herzschlag_intervall=5.0)
    watcher.run()
