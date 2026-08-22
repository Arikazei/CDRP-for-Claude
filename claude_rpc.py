"""Discord Rich Presence fuer Claude Desktop.

Zustaende:
  AKTIV - Claude-Fenster im Fokus + Eingaben in den letzten X Sekunden
          -> rotierende Texte aus config.json ("texts.active")
  OFFEN - Claude laeuft, aber kein Fokus / keine Eingabe
          -> Text aus "texts.open" (Standard: "Claude Desktop")
  AUS   - laenger als idle_timeout_minutes inaktiv -> Presence entfernt,
          bei erneutem Fokus sofort wieder da (Timer startet neu)

Alle Texte und Timings sind in config.json einstellbar.
"""
import json
import logging
import os
import time
from pathlib import Path

import re

from pypresence import Presence

import beacons

from hostplatform import (
    DEFAULT_PROCESS_NAMES, accessibility_enable, claude_candidates,
    claude_config_dir, claude_focused, claude_running, idle_backend_name,
    release_instance,
    idle_configure, idle_seconds, idle_supported, init_com, iter_processes,
    process_cmdline, process_path, single_instance, ui_tree_nodes,
    ui_tree_supported,
)

try:
    import uiautomation as _uia
except ImportError:
    _uia = None

BASE_DIR = Path(__file__).resolve().parent
# Im MCPB liegt der Code in einem Ordner, in den nicht geschrieben werden
# soll; Konfiguration, Log und Beacon wandern deshalb per Umgebungsvariable
# in ein Datenverzeichnis.
DATA_DIR = Path(os.environ.get("CLAUDE_RPC_DATA_DIR") or BASE_DIR)
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = BASE_DIR
CONFIG_PATH = Path(os.environ.get("CLAUDE_RPC_CONFIG") or (BASE_DIR / "config.json"))
LOG_PATH = Path(os.environ.get("CLAUDE_RPC_LOG") or (DATA_DIR / "claude_rpc.log"))

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# Vom MCP-Server umschaltbar, damit die Presence pausiert werden kann,
# ohne den Prozess zu beenden.
#
# Der Schalter liegt als Datei im Datenordner und nicht nur im Speicher:
# Claude Desktop startet den Server mehrfach, senden tut aber nur die
# Instanz mit dem Mutex. Beantwortet eine andere den Werkzeugaufruf, setzt
# sie sonst ihre eigene Variable, waehrend die sendende Instanz weiterlaeuft
# -- presence_pause meldet dann Erfolg und in Discord aendert sich nichts.
PAUSE_PATH = DATA_DIR / "paused.flag"
_PAUSED = PAUSE_PATH.exists()
_PAUSED_GEPRUEFT = 0.0


def set_paused(value):
    global _PAUSED, _PAUSED_GEPRUEFT
    _PAUSED = bool(value)
    _PAUSED_GEPRUEFT = time.time()
    try:
        if _PAUSED:
            PAUSE_PATH.write_text("1", encoding="utf-8")
        else:
            PAUSE_PATH.unlink(missing_ok=True)
    except OSError as exc:
        # Ohne Datei wirkt die Pause nur in diesem Prozess. Das ist besser
        # als ein Abbruch, gehoert aber ins Log -- sonst sucht man den
        # Grund fuer die weiterlaufende Presence spaeter im Discord-Zweig.
        logging.warning("Pause-Schalter nicht schreibbar (%s)", exc)
    logging.info("Presence %s", "pausiert" if _PAUSED else "aktiv")
    return _PAUSED


def is_paused():
    """Pausenschalter, hoechstens einmal je Sekunde von der Platte gelesen.

    Die Hauptschleife fragt oft, ein Dateizugriff je Durchlauf waere
    Verschwendung. Ein rein zwischengespeicherter Wert wuerde die Pause aus
    dem Nachbarprozess dafuer nie mitbekommen.
    """
    global _PAUSED, _PAUSED_GEPRUEFT
    jetzt = time.time()
    if jetzt - _PAUSED_GEPRUEFT >= 1.0:
        _PAUSED_GEPRUEFT = jetzt
        try:
            _PAUSED = PAUSE_PATH.exists()
        except OSError:
            pass
    return _PAUSED


# Momentaufnahme fuer den MCP-Server (Werkzeug "presence_status").
# Zusaetzlich auf Platte, weil Claude Desktop den Server mehrfach startet:
# nur eine Instanz sendet, die andere beantwortet vielleicht die Aufrufe.
LAST_STATE = {}
_STATE_WRITTEN = 0.0

# Damit die wiederholten Uebernahmeversuche das Protokoll nicht zulaufen
# lassen: die Meldung "laeuft bereits" gehoert einmal je Prozess hinein.
_INSTANZ_GEMELDET = False


def publish_state():
    """Momentaufnahme in den Datenordner schreiben, hoechstens alle 10 s."""
    global _STATE_WRITTEN
    now = time.time()
    if now - _STATE_WRITTEN < 10:
        return
    _STATE_WRITTEN = now
    try:
        (DATA_DIR / "state.json").write_text(
            json.dumps(LAST_STATE, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def read_state():
    """Momentaufnahme des sendenden Prozesses, sonst leer."""
    if LAST_STATE:
        return LAST_STATE
    try:
        return json.loads((DATA_DIR / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)










class SessionInfo:
    """Modul: Projekt + Modell der letzten lokalen Claude-Code-/Cowork-Session.

    Liest die zuletzt geaenderte Transkript-Datei unter ~/.claude/projects.
    Zeigt nichts an, wenn die letzte lokale Session aelter als max_age_minutes ist
    (z. B. weil gerade nur Cloud-Sessions laufen).
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.text = None
        self.next_refresh = 0.0

    def get(self):
        if not self.cfg.get("enabled"):
            return None
        now = time.time()
        if now >= self.next_refresh:
            self.next_refresh = now + self.cfg.get("refresh_seconds", 30)
            self.text = self._read()
        return self.text

    def _read(self):
        try:
            root = Path.home() / ".claude" / "projects"
            if not root.is_dir():
                return None
            files = [
                f for d in root.iterdir() if d.is_dir() for f in d.glob("*.jsonl")
            ]
            if not files:
                return None
            latest = max(files, key=lambda f: f.stat().st_mtime)
            max_age = self.cfg.get("max_age_minutes", 10) * 60
            if time.time() - latest.stat().st_mtime > max_age:
                return None
            project, model = self._parse_tail(latest)
            template = self.cfg.get("code_template")
            if template:
                if "{model}" in template and not model:
                    return None
                text = template.replace("{model}", model or "")
                return text.replace("{project}", project or "").strip()
            parts = []
            if self.cfg.get("show_project", True) and project:
                parts.append(project)
            if self.cfg.get("show_model", True) and model:
                parts.append(model)
            return " · ".join(parts) if parts else None
        except Exception as exc:
            logging.warning("Session-Info fehlgeschlagen: %s", exc)
            return None

    @staticmethod
    def _parse_tail(path):
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().decode("utf-8", "replace").splitlines()
        project = model = None
        for line in reversed(lines):
            if not line.strip().startswith("{"):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if project is None and entry.get("cwd"):
                project = Path(entry["cwd"]).name
            if model is None:
                mid = (entry.get("message") or {}).get("model", "")
                if mid:
                    match = re.search(
                        r"(fable|opus|sonnet|haiku)-(\d+)(?:-(\d{1,2}))?(?=-|$)", mid
                    )
                    if match:
                        fam, major, minor = match.groups()
                        model = fam.capitalize() + " " + major
                        if minor:
                            model += "." + minor
                    else:
                        model = mid
            if project and model:
                break
        return project, model


class CoworkBeacon:
    """Modul: Cowork-Sessions melden sich selbst per Beacon-Datei.

    Cowork-Sessions schreiben (per Benutzereinstellung instruiert) zu Beginn
    cowork_status.json in den Projektordner: {"model": "...", "chat": "..."}.
    Anzeige einzeln schaltbar: show_model (Standard an), show_chat (Standard aus).
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.path = DATA_DIR / "cowork_status.json"

    def get(self, activity_fresh=False):
        if not self.cfg.get("enabled"):
            return None
        text = self._from_beacon(activity_fresh)
        if text:
            return text
        return self.cfg.get("fallback_text") or None

    def _from_beacon(self, activity_fresh):
        try:
            if not self.path.exists():
                return None
            age = time.time() - self.path.stat().st_mtime
            max_age = self.cfg.get("max_age_minutes", 60) * 60
            hard_cap = self.cfg.get("max_age_hard_hours", 12) * 3600
            if age > max_age and not (activity_fresh and age <= hard_cap):
                return None
            data = json.loads(self.path.read_text(encoding="utf-8"))
            text = self.cfg.get("label", "using cowork")
            if self.cfg.get("show_model", True) and data.get("model"):
                text += " with " + str(data["model"])
            # Chat-Titel bleiben bewusst aussen vor, siehe LocalSessionWatcher.
            return text
        except Exception as exc:
            logging.warning("Cowork-Beacon fehlgeschlagen: %s", exc)
            return None


class ActivityWatcher:
    """Modul: Live-Aktivitaet aus den Logdateien der Claude-Desktop-App.

    mcp-server-<Name>.log frisch geschrieben -> "Claude is using <Name>"
    claude.ai-web.log frisch geschrieben     -> allgemeiner Arbeits-Text
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.log_dir = claude_config_dir() / "logs"

    def get(self):
        if not self.cfg.get("enabled"):
            return None
        try:
            if not self.log_dir.is_dir():
                return None
            now = time.time()
            fresh = self.cfg.get("fresh_seconds", 15)
            best_name = None
            best_age = None
            for f in self.log_dir.glob("mcp-server-*.log"):
                age = now - f.stat().st_mtime
                if age <= fresh and (best_age is None or age < best_age):
                    best_age = age
                    best_name = f.stem[len("mcp-server-"):]
            if best_name:
                template = self.cfg.get("tool_template", "Claude is using {tool}")
                return template.replace("{tool}", best_name)
            web = self.log_dir / "claude.ai-web.log"
            if web.exists() and now - web.stat().st_mtime <= fresh:
                return self.cfg.get("working_text", "Claude arbeitet gerade...")
            return None
        except Exception as exc:
            logging.warning("Activity-Watcher fehlgeschlagen: %s", exc)
            return None


class UIModelWatcher:
    """Modul: liest das Modell des offenen Chats direkt aus der
    Claude-Desktop-Oberflaeche (Windows UI Automation).

    Findet den Modell-Button (z. B. "Modell: Opus 4.8 Hoch") im Fenster --
    funktioniert fuer normale Chats und Cowork, ohne Session-Kooperation.
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.text = None
        self.next_refresh = 0.0
        self._ax_ready = False
        self._hinweis = False

    def get(self):
        if not self.cfg.get("enabled"):
            return None
        if _uia is None:
            # Ohne UI Automation gibt es hier nichts zu tun. Ein eigener
            # AT-SPI-Lauf waere reine Verschwendung: der UIWatcher nimmt
            # das Modell in seinem Durchlauf ohnehin mit.
            if not self._hinweis:
                self._hinweis = True
                logging.info("ui_model bleibt aus - ausserhalb von Windows "
                             "liefert der UI-Watcher das Modell mit")
            return None
        now = time.time()
        if now >= self.next_refresh:
            self.next_refresh = now + self.cfg.get("refresh_seconds", 10)
            self.text = self._read()
        return self.text

    @staticmethod
    def _find_window():
        for w in _uia.GetRootControl().GetChildren():
            try:
                if w.ClassName and "Chrome_WidgetWin" in w.ClassName and \
                        "Claude" in (w.Name or ""):
                    return w
            except Exception:
                continue
        return None

    def _read(self):
        try:
            _uia.SetGlobalSearchTimeout(2)
            win = self._find_window()
            if win is None:
                self._ax_ready = False
                return None
            if not self._ax_ready:
                doc = _uia.DocumentControl(searchFromControl=win)
                if doc.Exists(3, 1):
                    self._ax_ready = True
            btn = _uia.ButtonControl(
                searchFromControl=win,
                Compare=lambda c, d: bool(
                    re.match(r"Modell?:", c.Name or "")
                ),
            )
            if not btn.Exists(2, 1):
                return None
            match = re.search(
                r"(Fable|Opus|Sonnet|Haiku)(\s+\d+(?:\.\d+)?)?",
                btn.Name or "", re.I,
            )
            if not match:
                return None
            model = match.group(0).strip()
            template = self.cfg.get("template", "using cowork with {model}")
            return template.replace("{model}", model)
        except Exception as exc:
            logging.warning("UI-Watcher fehlgeschlagen: %s", exc)
            return None


def _pretty_model(model_id):
    """claude-haiku-4-5-20251001 -> "Haiku 4.5"."""
    match = re.search(
        r"(opus|sonnet|haiku|fable)-(\d{1,2})(?:[-.](\d{1,2})(?!\d))?",
        model_id or "", re.I,
    )
    if not match:
        return None
    version = match.group(2)
    if match.group(3):
        version += "." + match.group(3)
    return "%s %s" % (match.group(1).capitalize(), version)


# AT-SPI benennt dieselben Bedienelemente anders als UI Automation. Die
# Auswertung im UIWatcher kennt nur die Windows-Namen -- uebersetzt wird
# deshalb genau hier, an einer Stelle. Zwei getrennte Auswertungen waeren
# zwei Orte, an denen die Erkennung mit der naechsten Claude-Fassung
# auseinanderlaufen kann.
#
# Was nicht in der Tabelle steht, behaelt seinen AT-SPI-Namen und faellt
# damit durch jede Abfrage. Es bleibt trotzdem in der Liste stehen: die
# Statuszeile wird ueber den Abstand zum Eingabefeld gesucht, und ein
# uebergangener Knoten wuerde diesen Abstand verfaelschen.
ATSPI_ROLLEN = {
    "push button": "ButtonControl",
    "toggle button": "ButtonControl",
    "button": "ButtonControl",
    "menu item": "ButtonControl",
    "combo box": "ButtonControl",
    "entry": "EditControl",
    "text box": "EditControl",
    "password text": "EditControl",
    "text": "TextControl",
    "static": "TextControl",
    "label": "TextControl",
    "paragraph": "TextControl",
    "heading": "TextControl",
    "caption": "TextControl",
    "status bar": "TextControl",
    "progress bar": "ProgressBarControl",
    "level bar": "ProgressBarControl",
    "document web": "DocumentControl",
    "document frame": "DocumentControl",
    "frame": "WindowControl",
    "window": "WindowControl",
    "dialog": "WindowControl",
}

# Rollen der obersten Ebene. Deren Name ist der Fenstertitel und damit der
# Chattitel -- unter Windows laesst der Durchlauf das oberste Fenster
# deshalb aus (includeTop=False), und hier gilt dasselbe. Was gar nicht
# erst eingesammelt wird, kann auch nicht versehentlich in der Presence
# landen.
ATSPI_FENSTER_ROLLEN = ("frame", "window", "dialog", "application")

# Der Beleg dafuer, dass Chromium den Seiteninhalt veroeffentlicht und
# nicht nur das Fenstergeruest. Ohne einen solchen Knoten ist jeder
# Durchlauf vergeblich, und das gehoert ins Protokoll statt in die Stille.
ATSPI_INHALT_ROLLEN = ("document web", "document frame", "document")


class UIWatcher:
    """Modul: ein einziger Durchlauf durch den Accessibility-Tree des
    Claude-Fensters -- unter Windows ueber UI Automation, unter Linux ueber
    AT-SPI. Beide Wege erzeugen dieselbe Liste (Steuerelementtyp, Name);
    alles danach ist gemeinsam.

    Liefert Modell, Live-Status ("Desktop Commander wird verwendet...") und
    das Busy-Flag (Stop-Button sichtbar). Als einzige Quelle funktioniert das
    auch fuer Cloud-Cowork-Sessions und normale Cloud-Chats, weil dort lokal
    keine Dateien geschrieben werden.

    Der Chat-Titel wird bewusst nicht ausgelesen: er hat in einer oeffentlich
    sichtbaren Presence nichts verloren, und was gar nicht erst erhoben wird,
    kann auch nicht versehentlich veroeffentlicht werden.
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.data = {}
        self.next_refresh = 0.0
        self._ax_ready = False
        self.status_re = re.compile(
            self.cfg.get(
                "status_pattern",
                r"(wird verwendet|denkt|arbeitet|analysiert|schreibt|"
                r"is using|thinking|working|writing)",
            ),
            re.I,
        )
        # "stop" steht allein in der Sitzungsansicht von Claude Code, wo der
        # Senden-Knopf waehrend der Antwort seine Beschriftung wechselt.
        # Verglichen wird der ganze Name, nie ein Teilstueck: im selben
        # Fenster sitzt "Stop this task" der Hintergrundaufgaben, und ein
        # Teilstueck-Vergleich haette die Presence bei jeder laufenden
        # Hintergrundaufgabe auf "arbeitet gerade" gestellt.
        self.stop_names = {
            n.lower()
            for n in self.cfg.get(
                "stop_button_names",
                ["antwort stoppen", "stop response", "antwort anhalten",
                 "stop"],
            )
        }
        self.composer_re = re.compile(
            self.cfg.get(
                "composer_pattern",
                r"(Anfrage an Claude|Nachricht|Message Claude|Reply to Claude)",
            ),
            re.I,
        )
        # Zweiter Anker fuer die Sitzungsansicht von Claude Code. Dort ist
        # das Eingabefeld kein Textfeld mit Beschriftung, sondern ein
        # benannter Behaelter ("Prompt") um einen contenteditable-Bereich --
        # composer_pattern greift dort ins Leere. Verglichen wird wieder der
        # ganze Name, damit ein Chatbeitrag ueber Prompts nicht zum Anker
        # wird. Gelesen wird ausschliesslich der Name des Behaelters, nie
        # sein Inhalt: das ist die Eingabe des Nutzers.
        self.anchor_names = {
            n.lower()
            for n in self.cfg.get(
                "composer_anchor_names", ["prompt", "type / for commands"]
            )
        }
        # Blosser Modellknopf derselben Ansicht ("Fable 5"). Ohne Praefix
        # und deshalb ganz gebunden, sonst passt jede Zeile, in der ein
        # Modellname vorkommt.
        self.bare_model_re = re.compile(
            self.cfg.get(
                "bare_model_pattern",
                r"^(Fable|Opus|Sonnet|Haiku)( [0-9][0-9.]*)?$",
            ),
            re.I,
        )
        self.lookback = self.cfg.get("status_lookback", 12)
        # In der Sitzungsansicht steht die Statusleiste unter dem
        # Eingabefeld, nicht darueber. Der Blick nach vorn ist eng gehalten
        # und trifft nur die Knopfreihe des Eingabebereichs -- der
        # Chatverlauf liegt davor, nie dahinter.
        self.lookahead = self.cfg.get("status_lookahead", 8)
        self.require_busy = self.cfg.get("require_busy", True)
        self._fremde_rollen = False
        self._skelett_gemeldet = False
        self._busy_gemeldet = False

    def quelle(self):
        """Welcher Weg liest hier das Fenster: "uia", "atspi" oder None."""
        if _uia is not None:
            return "uia"
        if ui_tree_supported():
            return "atspi"
        return None

    def quelle_text(self):
        """Dasselbe in Worten, fuer das Protokoll."""
        return {
            "uia": "Windows UI Automation",
            "atspi": "AT-SPI ueber D-Bus",
        }.get(self.quelle(),
              "keine Schnittstelle - Fenster wird nicht ausgelesen")

    def refresh(self):
        if not (self.cfg.get("enabled", True) and self.quelle()):
            self.data = {}
            return self.data
        now = time.time()
        if now >= self.next_refresh:
            self.data = self._scan()
            # Ein AT-SPI-Durchlauf kostet drei D-Bus-Runden je Knoten und
            # kann bei einem grossen Baum Sekunden dauern. Damit der Daemon
            # nicht den ueberwiegenden Teil seiner Zeit im Baum verbringt,
            # waechst die Pause mit der gemessenen Dauer mit.
            dauer = time.time() - now
            self.next_refresh = time.time() + max(
                self.cfg.get("refresh_seconds", 8), dauer * 3)
        return self.data

    def info(self):
        model = self.data.get("model")
        if not model:
            return None
        # Woher der Modellname stammt, entscheidet die Beschriftung: der
        # blosse Modellknopf gibt es nur in der Sitzungsansicht von Claude
        # Code, und "using cowork with Fable 5" waere dort schlicht falsch.
        if self.data.get("model_source") == "code":
            template = self.cfg.get("code_template", "using code with {model}")
        else:
            template = self.cfg.get("template", "using cowork with {model}")
        return template.replace("{model}", model)

    def status(self):
        text = self.data.get("status")
        if text:
            return self._tidy(text)
        if self.data.get("busy") and self.cfg.get("busy_text"):
            return self.cfg["busy_text"]
        return None

    def _tidy(self, text):
        """Doppelten Namensteil zusammenfassen.

        Server aus Plugins heissen "plugin:server". Sind beide Teile gleich,
        steht in der Presence "context-mode:context-mode wird verwendet" --
        die Haelfte davon ist Fuellmaterial. Unterschiedliche Teile bleiben
        erhalten, dort traegt der Praefix ja Information.
        """
        if not self.cfg.get("collapse_duplicate_prefix", True):
            return text
        return re.sub(r"^([^\s:]+):\1\b", r"\1", text)

    def busy(self):
        return bool(self.data.get("busy"))

    def _scan(self):
        """Einmal durch den Baum, je nach System ueber den einen oder den
        anderen Weg -- ausgewertet wird beides gemeinsam."""
        try:
            if self.quelle() == "atspi":
                nodes = self._knoten_atspi()
            else:
                nodes = self._knoten_uia()
            if not nodes:
                return {}
            return self._auswerten(nodes)
        except Exception as exc:
            logging.warning("UI-Watcher fehlgeschlagen: %s", exc)
            return {}

    def _knoten_uia(self):
        """Windows: der Fensterbaum ueber UI Automation."""
        _uia.SetGlobalSearchTimeout(2)
        win = UIModelWatcher._find_window()
        if win is None:
            self._ax_ready = False
            return []
        if not self._ax_ready:
            # Erst diese Anforderung bringt Electron dazu, den Baum
            # ueberhaupt aufzubauen.
            doc = _uia.DocumentControl(searchFromControl=win)
            if not doc.Exists(3, 1):
                return []
            self._ax_ready = True
        max_nodes = self.cfg.get("max_nodes", 3000)
        nodes = []
        count = 0
        for ctrl, _depth in _uia.WalkControl(win, includeTop=False, maxDepth=40):
            count += 1
            if count > max_nodes:
                break
            try:
                name = (ctrl.Name or "").strip()
                if not name:
                    continue
                nodes.append((ctrl.ControlTypeName, name))
            except Exception:
                continue
        return nodes

    def _knoten_atspi(self):
        """Linux: derselbe Baum ueber AT-SPI, auf Windows-Namen uebersetzt.

        Namenlose Knoten fallen wie unter Windows heraus. Das ist keine
        Kosmetik: der Abstand zum Eingabefeld (status_lookback) zaehlt
        Eintraege dieser Liste, und AT-SPI-Baeume bestehen zum grossen Teil
        aus namenlosen Huellknoten, die den Abstand sonst sprengen wuerden.
        """
        roh = ui_tree_nodes(
            self.cfg.get("atspi_match", "claude"),
            self.cfg.get("max_nodes", 3000),
            self.cfg.get("scan_budget_seconds", 4.0),
        )
        if not roh:
            self._ax_ready = False
            return []
        self._inhalt_pruefen(roh)
        nodes = []
        unbekannt = set()
        for tiefe, rolle, name in roh:
            rolle = (rolle or "").lower()
            if tiefe == 0 and rolle in ATSPI_FENSTER_ROLLEN:
                continue
            name = (name or "").strip()
            if not name:
                continue
            art = ATSPI_ROLLEN.get(rolle)
            if art is None:
                unbekannt.add(rolle)
                art = rolle
            nodes.append((art, name))
        if unbekannt and self._ax_ready and not self._fremde_rollen:
            # Nur die Rollennamen, nie die Beschriftungen: die Tabelle oben
            # laesst sich damit nachziehen, ohne dass Chatinhalt ins
            # Protokoll geraet.
            self._fremde_rollen = True
            logging.info("AT-SPI-Rollen ohne Entsprechung: %s",
                         ", ".join(sorted(unbekannt))[:400])
        return nodes

    def _inhalt_pruefen(self, roh):
        """Steht im Baum Seiteninhalt oder nur das Fenstergeruest?

        Chromium veroeffentlicht ohne angemeldeten Bildschirmleser nur den
        Fensterrahmen -- vier Knoten, kein Dokument. Wer das nicht
        protokolliert, sucht den Fehler spaeter in der Auswertung, obwohl
        gar nichts anzukommen ist. Der Schalter wirkt zudem erst beim
        naechsten Start von Claude, was ohne Hinweis niemand erraet.
        """
        inhalt = any((rolle or "").lower() in ATSPI_INHALT_ROLLEN
                     for _tiefe, rolle, _name in roh)
        if inhalt and not self._ax_ready:
            self._ax_ready = True
            logging.info("AT-SPI: Claude veroeffentlicht den Seiteninhalt "
                         "(%d Knoten)", len(roh))
        elif not inhalt:
            self._ax_ready = False
            if not self._skelett_gemeldet:
                self._skelett_gemeldet = True
                logging.info(
                    "AT-SPI: nur das Fenstergeruest (%d Knoten), kein "
                    "Dokumentknoten. Der Bildschirmleser-Schalter wirkt erst "
                    "beim naechsten Start von Claude; hilft auch der nicht, "
                    "Claude mit --force-renderer-accessibility starten.",
                    len(roh))

    def _auswerten(self, nodes):
        """Aus (Steuerelementtyp, Name) die drei Angaben ziehen. Gemeinsam
        fuer beide Systeme -- hier steht das ganze Wissen ueber die
        Oberflaeche von Claude."""
        out = {}
        models = []
        bare_models = []
        composer_at = -1
        anchor_at = -1
        anchor_text_at = -1
        for index, (kind, name) in enumerate(nodes):
            if kind == "ButtonControl":
                if name.lower() in self.stop_names:
                    out["busy"] = True
                elif re.match(r"Modell?:", name):
                    found = re.search(
                        r"(Fable|Opus|Sonnet|Haiku)(\s+\d+(?:\.\d+)?)?",
                        name, re.I,
                    )
                    if found:
                        models.append(found.group(0).strip())
                elif self.bare_model_re.match(name):
                    bare_models.append(name.strip())
            elif kind == "EditControl" and self.composer_re.search(name):
                composer_at = index
            if name.lower() in self.anchor_names:
                # Der letzte Treffer gewinnt: das Eingabefeld sitzt am Ende
                # des Baumes, der Chatverlauf davor. Der Behaelter ("Prompt")
                # ist der bessere Anker als der Platzhaltertext in ihm --
                # der Platzhalter verschwindet, sobald etwas eingetippt ist.
                if kind == "TextControl":
                    anchor_text_at = index
                else:
                    anchor_at = index
        if models:
            # Der beschriftete Knopf ist die belastbarere Quelle und behaelt
            # den Vortritt; der blosse Knopf springt nur ein, wo es ihn
            # allein gibt.
            out["model"] = models[-1]
        elif bare_models:
            out["model"] = bare_models[-1]
            out["model_source"] = "code"
        if composer_at < 0:
            composer_at = anchor_at if anchor_at >= 0 else anchor_text_at
        out.update(self._read_limits(nodes))

        # Die Statuszeile steht unmittelbar ueber dem Eingabefeld. Ohne
        # diesen Anker wuerde auch Text aus dem Chatverlauf passen -- ein
        # Chat, in dem "... wird verwendet" vorkommt, hat die Presence
        # sonst dauerhaft falsch beschriftet.
        if composer_at > 0 and (out.get("busy") or not self.require_busy):
            start = max(0, composer_at - self.lookback)
            # Die Sitzungsansicht haengt ihre Statusleiste unter das
            # Eingabefeld. Der Blick dahinter reicht nur bis in die
            # Knopfreihe und kann den Chatverlauf nicht erreichen.
            stop_at = composer_at + 1 + max(0, self.lookahead)
            fenster = nodes[start:composer_at] + nodes[composer_at + 1:stop_at]
            candidates = [
                name
                for kind, name in fenster
                if kind == "TextControl"
                and len(name) <= 80
                and name.endswith(self.STATUS_ENDE)
            ]
            if candidates:
                known = [c for c in candidates if self.status_re.search(c)]
                # Bekannte Formulierung bevorzugen, sonst die letzte
                # Zeile ueber dem Eingabefeld -- so ueberleben auch
                # Statustexte, die es heute noch nicht gibt.
                out["status"] = (known or candidates)[-1].rstrip("… .")
        if out.get("busy") and not self._busy_gemeldet:
            # Einmalig je Lauf, weil sich zwei Fragen nur im laufenden
            # Betrieb beantworten lassen: greift der Stop-Knopf, und hat
            # die Ansicht ueberhaupt eine Statuszeile? Ohne diesen Vermerk
            # bliebe beides Vermutung. Vermerkt wird nur, ob etwas gefunden
            # wurde -- der Text selbst gehoert nicht ins Protokoll.
            self._busy_gemeldet = True
            logging.info(
                "UI-Watcher: Antwort laeuft, Anker %s, Statuszeile %s",
                "gefunden" if composer_at > 0 else "fehlt",
                "gefunden" if out.get("status") else "keine",
            )
        return out

    # Laufende Statustexte enden mit Auslassungspunkten. Welches Zeichen
    # ankommt, entscheidet die Oberflaeche: UI Automation liefert das
    # gesetzte "…", AT-SPI gibt den Text so heraus, wie er im Dokument
    # steht -- dort stehen je nach Stelle drei einzelne Punkte.
    STATUS_ENDE = ("…", "...")

    # Im Nutzungsfenster traegt jede Fortschrittsleiste den Namen ihres
    # Limits, der Prozentwert steht im naechsten Textknoten:
    #   ProgressBar "Fable"  ->  Text "99 % verwendet"
    # Bewusst eine Positivliste: im selben Fenster stehen auch das
    # Nutzungsguthaben und der ausgegebene Betrag in Euro. Was nicht
    # ausdruecklich erlaubt ist, faellt durch -- auch kuenftige Balken.
    LIMIT_LABELS = (
        (r"^(aktuelle sitzung|current session)", "5h"),
        (r"^(alle modelle|all models)", "Woche"),
        (r"^(fable|opus|sonnet|haiku)\b", None),
    )
    PLAN_RE = re.compile(
        r"^(Max|Pro|Team|Enterprise|Free)\s*(?:\(\s*(\d+)\s*x\s*\))?$", re.I
    )

    def _read_limits(self, nodes):
        out = {}
        limits = {}
        plan = None
        for index, (kind, name) in enumerate(nodes):
            if kind == "TextControl":
                match = self.PLAN_RE.match(name)
                if match:
                    plan = match.group(1).capitalize()
                    if match.group(2):
                        plan += " %sx" % match.group(2)
                continue
            if kind != "ProgressBarControl":
                continue
            label = None
            for pattern, fixed in self.LIMIT_LABELS:
                if re.match(pattern, name.strip(), re.I):
                    label = fixed or name.strip()
                    break
            if label is None:
                continue
            for follow_kind, follow_name in nodes[index + 1: index + 4]:
                if follow_kind != "TextControl":
                    continue
                percent = re.search(r"(\d{1,3})\s*%", follow_name)
                if percent:
                    limits[label] = int(percent.group(1))
                    break
        if limits:
            out["limits"] = limits
            # Die Abo-Stufe wird nur uebernommen, wenn im selben Durchlauf
            # auch Limit-Balken gefunden wurden. Ein blosses "Max" irgendwo
            # im Chatverlauf ist sonst schon ein Treffer.
            if plan:
                out["plan"] = plan
        return out


class LimitStore:
    """Merkt sich die im Nutzungsfenster abgelesenen Limits samt Alter.

    Das modellspezifische Wochenlimit steht lokal in keiner Datei -- es ist
    nur sichtbar, solange das Nutzungsfenster offen ist. Der Wert wird
    deshalb beim Vorbeikommen eingesammelt, mit Zeitstempel abgelegt und
    altert danach: erst mit Vermerk, dann gar nicht mehr.
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.path = DATA_DIR / "ui_limits.json"
        self.data = {}
        self._last_save = 0.0
        self._load()

    def _load(self):
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logging.warning("Limit-Speicher nicht schreibbar: %s", exc)

    def update(self, scan):
        """Neue Ablesungen uebernehmen.

        Solange das Nutzungsfenster offen ist, laeuft der Scan alle paar
        Sekunden durch. Geschrieben wird trotzdem nur bei einer echten
        Aenderung oder hoechstens minuetlich, damit die Platte Ruhe hat.
        """
        now = time.time()
        important = False
        touched = False
        for label, percent in (scan.get("limits") or {}).items():
            entry = self.data.get(label)
            if not isinstance(entry, dict) or entry.get("percent") != percent:
                self.data[label] = {"percent": percent, "seen": now}
                important = True
            else:
                entry["seen"] = now
                touched = True
        if scan.get("plan") and self.data.get("plan") != scan["plan"]:
            self.data["plan"] = scan["plan"]
            important = True
        if important or (touched and now - self._last_save > 60):
            self._last_save = now
            self._save()

    def plan(self):
        return self.data.get("plan")

    def model_limit(self):
        """Text fuer das modellspezifische Limit, oder None wenn zu alt."""
        if not self.cfg.get("enabled", True):
            return None
        max_age = self.cfg.get("max_age_minutes", 180) * 60
        mark_age = self.cfg.get("age_marker_minutes", 30) * 60
        best = None
        for label, entry in self.data.items():
            if label in ("5h", "Woche", "plan") or not isinstance(entry, dict):
                continue
            if best is None or entry.get("seen", 0) > best[1].get("seen", 0):
                best = (label, entry)
        if best is None:
            return None
        label, entry = best
        age = time.time() - entry.get("seen", 0)
        if age > max_age:
            return None
        text = "%s %d%%" % (label, entry.get("percent", 0))
        if age > mark_age:
            text += self._age_suffix(age)
        return text

    @staticmethod
    def _age_suffix(age):
        if age < 3600:
            return " (vor %d min)" % round(age / 60)
        return " (vor %d h)" % round(age / 3600)

    def status(self):
        """Alter aller bekannten Limits, fuer das Werkzeug presence_status."""
        out = {}
        for label, entry in self.data.items():
            if isinstance(entry, dict):
                out[label] = {
                    "percent": entry.get("percent"),
                    "alter_minuten": round((time.time() - entry.get("seen", 0)) / 60),
                }
        return out


class ToolHistoryWatcher:
    """Modul: liest den Werkzeugverlauf von Desktop Commander
    (~/.claude-server-commander/tool-history.jsonl).

    Bewusst wird ausschliesslich das Feld toolName ausgewertet. Argumente
    und Ausgaben stehen in derselben Datei, duerfen aber nie in die
    Presence gelangen (Dateipfade, Dateiinhalte).
    """

    DEFAULT_LABELS = {
        "read_file": "liest Dateien",
        "read_multiple_files": "liest Dateien",
        "get_file_info": "sieht sich Dateien an",
        "list_directory": "sieht sich Ordner an",
        "write_file": "schreibt Dateien",
        "write_pdf": "schreibt ein PDF",
        "edit_block": "bearbeitet Code",
        "create_directory": "legt Ordner an",
        "move_file": "raeumt Dateien um",
        "start_search": "durchsucht Dateien",
        "get_more_search_results": "durchsucht Dateien",
        "start_process": "fuehrt Befehle aus",
        "interact_with_process": "fuehrt Befehle aus",
        "read_process_output": "wartet auf einen Prozess",
        "force_terminate": "beendet einen Prozess",
        "kill_process": "beendet einen Prozess",
        "list_processes": "sieht sich Prozesse an",
        "list_sessions": "sieht sich Prozesse an",
        "_default": "nutzt Desktop Commander",
    }

    def __init__(self, cfg):
        self.cfg = cfg or {}
        raw = self.cfg.get("path")
        self.path = (
            Path(raw) if raw
            else Path.home() / ".claude-server-commander" / "tool-history.jsonl"
        )
        self.labels = dict(self.DEFAULT_LABELS)
        self.labels.update(self.cfg.get("labels", {}) or {})
        self._cache_key = None
        self._cache_tool = None

    def get(self):
        if not self.cfg.get("enabled", True):
            return None
        try:
            stat = self.path.stat()
        except OSError:
            return None
        if time.time() - stat.st_mtime > self.cfg.get("fresh_seconds", 25):
            return None
        key = (stat.st_mtime, stat.st_size)
        if key != self._cache_key:
            self._cache_key = key
            self._cache_tool = self._last_tool(stat.st_size)
        if not self._cache_tool:
            return None
        action = self.labels.get(self._cache_tool) or self.labels["_default"]
        template = self.cfg.get("template", "Claude {action}")
        return template.replace("{action}", action).replace(
            "{tool}", self._cache_tool
        )

    def _last_tool(self, size):
        try:
            with open(self.path, "rb") as handle:
                handle.seek(max(0, size - 65536))
                chunk = handle.read().decode("utf-8", "ignore")
            for line in reversed(chunk.splitlines()):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    name = json.loads(line).get("toolName")
                except Exception:
                    continue
                if name:
                    return str(name)
        except Exception as exc:
            logging.warning("Tool-History fehlgeschlagen: %s", exc)
        return None


class LocalSessionWatcher:
    """Modul: Zustand lokaler Cowork-Sessions ("auf diesem Computer") aus
    %APPDATA%/Claude/claude-code-sessions/**/local_*.json.

    Enthaelt Modell, Titel, Arbeitsordner und Zeitstempel und ersetzt damit
    den Beacon-Umweg fuer lokal laufende Sessions.
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.root = claude_config_dir() / "claude-code-sessions"
        self.next_refresh = 0.0
        self.text = None

    def get(self):
        if not self.cfg.get("enabled", True):
            return None
        now = time.time()
        if now >= self.next_refresh:
            self.next_refresh = now + self.cfg.get("refresh_seconds", 15)
            self.text = self._read()
        return self.text

    def _read(self):
        try:
            if not self.root.is_dir():
                return None
            best_ts, best_data = 0, None
            for path in self.root.rglob("local_*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if data.get("isArchived"):
                    continue
                stamp = max(
                    int(data.get("lastActivityAt") or 0),
                    int(data.get("lastFocusedAt") or 0),
                )
                if stamp > best_ts:
                    best_ts, best_data = stamp, data
            if not best_data:
                return None
            max_age = self.cfg.get("max_age_minutes", 30) * 60
            if best_ts and time.time() - best_ts / 1000.0 > max_age:
                return None
            text = self.cfg.get("label", "using cowork")
            model = _pretty_model(best_data.get("model"))
            if self.cfg.get("show_model", True) and model:
                text += " with " + model
            # Der Sitzungstitel wird bewusst nicht verwendet: er steht sonst
            # fuer jeden sichtbar im Discord-Profil, und Chat-Titel verraten
            # regelmaessig mehr als der Inhalt.
            return text
        except Exception as exc:
            logging.warning("Local-Session-Watcher fehlgeschlagen: %s", exc)
            return None


class LocalUsageWatcher:
    """Modul: Nutzungsprozente aus der lokalen Datei der Claude-Desktop-App
    (%APPDATA%/Claude/plan-usage-history.json).

    Die App schreibt dort alle 5 Minuten Stichproben: fh = 5-Stunden-Fenster,
    sd = 7-Tage-Fenster, xu = zusaetzliches Kontingent (jeweils Prozent).
    Bewusste Alternative zu TokenStatus: kein Lesen von .credentials.json,
    kein Aufruf eines Anthropic-Endpunkts, damit auch weitergabefaehig.
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        raw = self.cfg.get("path")
        self.path = (
            Path(raw) if raw
            else claude_config_dir() / "plan-usage-history.json"
        )
        self.next_refresh = 0.0
        self.text = None

    def get(self):
        if not self.cfg.get("enabled", False):
            return None
        now = time.time()
        if now >= self.next_refresh:
            fresh = self._read()
            if fresh:
                self.text = fresh
                self.next_refresh = now + self.cfg.get("refresh_minutes", 5) * 60
            else:
                # Die App schreibt die Datei alle fuenf Minuten neu. Faellt
                # eine Lesung aus, wird bald erneut versucht statt eine
                # volle Runde auszusetzen -- und der letzte Wert bleibt
                # stehen, statt die Anzeige leer zu raeumen.
                self.next_refresh = now + self.cfg.get("retry_seconds", 30)
        return self.text

    def _read(self):
        try:
            data = self._load_json()
            if data is None:
                return None
            samples = data.get("samples") or []
            if not samples:
                return None
            newest = samples[-1]
            usage = dict(newest.get("u") or {})
            # xu (Zusatzkontingent) schreibt die App nur zeitweise. Einen
            # Wert von vor Tagen weiterzuschleppen waere schlicht falsch,
            # deshalb ein enges Zeitfenster relativ zur letzten Stichprobe.
            if "xu" not in usage and self.cfg.get("show_extra", True):
                window = self.cfg.get("extra_max_age_minutes", 60) * 60 * 1000
                for sample in reversed(samples):
                    value = (sample.get("u") or {}).get("xu")
                    if value is None:
                        continue
                    if newest.get("t", 0) - sample.get("t", 0) <= window:
                        usage["xu"] = value
                    break
            parts = []
            for key, label in (
                ("fh", self.cfg.get("label_5h", "5h")),
                ("sd", self.cfg.get("label_week", "Woche")),
                ("xu", self.cfg.get("label_extra", "Extra")),
            ):
                if key in usage and (key != "xu" or self.cfg.get("show_extra", True)):
                    parts.append("%s %d%%" % (label, round(float(usage[key]))))
            return " · ".join(parts) or None
        except Exception as exc:
            logging.warning("Local-Usage-Watcher fehlgeschlagen: %s", exc)
            return None

    def _load_json(self):
        """Liest die Datei mit kurzen Wiederholungen.

        Die App ersetzt die Datei periodisch. Wer genau in diesen Moment
        liest, bekommt ENOENT oder eine halb geschriebene Datei zu sehen --
        beides ist kein Grund, die Anzeige zu leeren.
        """
        attempts = max(1, self.cfg.get("read_attempts", 4))
        last_error = None
        for number in range(attempts):
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                last_error = exc
                if number + 1 < attempts:
                    time.sleep(0.2)
        logging.info("Nutzungsdatei nicht lesbar (%d Versuche): %s",
                     attempts, last_error)
        return None


def karte_payload(karte, cfg):
    """Eine Karte von beacons.karten() zur Discord-Nutzlast machen.

    Bild, Knopf und Beschriftung kommen aus derselben Konfiguration --
    egal, welcher Client die Karte gestellt hat. Die Presence soll wie
    eine Anzeige wirken, die durch mehrere Clients wandert, und nicht wie
    drei Anzeigen, die sich abwechselnd hineindraengen.
    """
    payload = {"details": karte["details"]}
    if karte.get("start"):
        payload["start"] = int(karte["start"])
    if karte.get("zeile"):
        payload["state"] = karte["zeile"]
    if cfg.get("large_image_key"):
        payload["large_image"] = cfg["large_image_key"]
        payload["large_text"] = cfg.get("large_image_text", "Claude Desktop")
    aktiv = bool(karte.get("aktiv"))
    klein = cfg.get("small_image_key_active" if aktiv
                    else "small_image_key_open")
    if klein:
        payload["small_image"] = klein
        payload["small_text"] = "Aktiv" if aktiv else "Inaktiv"
    if cfg.get("buttons"):
        payload["buttons"] = cfg["buttons"]
    return payload


class RichPresence:
    """Duenner Wrapper um pypresence mit Auto-Reconnect."""

    # Discord drosselt zu haeufige Aktualisierungen nicht, es LEERT die
    # Presence (discord-api-docs#668). Die dokumentierte Grenze ist ein
    # Update alle 15 s. Zwischenstaende werden deshalb zusammengefasst;
    # der neueste gewinnt, sobald das Fenster wieder offen ist.
    MINDESTABSTAND = 15.0

    def __init__(self, client_id):
        self.client_id = client_id
        self.rpc = None
        self.last_payload = None
        self.last_sent = 0.0

    def _connect(self):
        if self.rpc is not None:
            return
        # Die Rohrnummern werden einzeln durchprobiert statt pypresence
        # suchen zu lassen: dessen Suche stolpert ueber verwaiste
        # Socket-Dateien eines frueheren Discord-Laufs -- 'Connection
        # refused' bricht dort die ganze Suche ab, obwohl das naechste
        # Rohr antworten wuerde. Nach einem Rechnerneustart lag genau so
        # eine Leiche in XDG_RUNTIME_DIR, und die Presence blieb stumm.
        letzter = None
        for rohr in range(10):
            rpc = Presence(self.client_id, pipe=rohr)
            try:
                rpc.connect()
            except Exception as exc:
                # DiscordNotFound bei fehlendem Rohr, ConnectionRefused
                # bei einer Leiche -- beides heisst nur: naechstes Rohr.
                letzter = exc
                continue
            self.rpc = rpc
            logging.info("Mit Discord verbunden (Rohr %d)", rohr)
            return
        raise letzter or ConnectionError("kein Discord-IPC-Rohr gefunden")

    def update(self, payload):
        if payload == self.last_payload:
            return
        jetzt = time.time()
        if jetzt - self.last_sent < self.MINDESTABSTAND:
            # Nichts merken noetig: die Hauptschleife ruft ohnehin wieder
            # auf und reicht dann den dann aktuellen Stand herein.
            return
        try:
            self._connect()
            self.rpc.update(**payload)
            self.last_payload = payload
            self.last_sent = jetzt
        except Exception as exc:
            logging.warning("Discord-Update fehlgeschlagen: %s", exc)
            self._reset()

    def clear(self):
        if self.rpc is None:
            return
        try:
            self.rpc.clear()
        except Exception:
            self._reset()
        self.last_payload = None

    def _reset(self):
        try:
            if self.rpc:
                self.rpc.close()
        except Exception:
            pass
        self.rpc = None
        self.last_payload = None


def main(rolle="extension"):
    """Sendet die Presence, bis ein hoeherrangiger Prozess uebernimmt.

    "rolle" entscheidet den Vorrang: "standalone" schlaegt "extension".
    Der eigenstaendige Dienst laeuft unabhaengig von Claude Desktop und
    kann deshalb auch dann senden, wenn nur Codex oder Antigravity
    offen sind. Startet er, weicht die Extension und beantwortet nur
    noch Werkzeugaufrufe; faellt er aus, uebernimmt sie wieder.

    Rueckgabe ist True, wenn dieser Prozess wieder senden darf und der
    Aufrufer es erneut versuchen soll.
    """
    # Erst pruefen, dann den Mutex belegen. Andersherum haelt eine Instanz,
    # die gleich an der Konfiguration scheitert, die Sperre trotzdem fest
    # und legt damit auch die gesunde zweite Instanz lahm.
    # Sofort anmelden, noch vor dem Mutex. Ein wartender Dienst muss
    # sichtbar sein, sonst gibt die Extension die Sperre nie frei und
    # beide warten aufeinander.
    beacons.sender_melden(DATA_DIR, rolle)

    cfg = load_config()
    client_id = str(cfg.get("client_id", ""))
    if not client_id.isdigit():
        logging.error(
            "Keine gueltige client_id in der Konfiguration (%r) - Abbruch",
            client_id[:40],
        )
        return

    fremd = beacons.fremder_sender(DATA_DIR, rolle)
    if fremd is not None:
        logging.info("Es sendet bereits ein %s-Prozess (PID %s) - dieser "
                     "Prozess wartet.", fremd.get("rolle"), fremd.get("pid"))
        return True

    if not single_instance():
        # Nur beim ersten Mal ins Protokoll: der Aufrufer versucht die
        # Uebernahme im Minutentakt erneut, und jeder Versuch waere sonst
        # eine Zeile.
        global _INSTANZ_GEMELDET
        if not _INSTANZ_GEMELDET:
            _INSTANZ_GEMELDET = True
            logging.info(
                "Es laeuft bereits eine Instanz - dieser Prozess beantwortet "
                "nur Werkzeugaufrufe und versucht die Uebernahme, sobald die "
                "sendende Instanz endet."
            )
        return

    # Der Pausenschalter ueberlebt einen Neustart. Ohne diesen Hinweis
    # sucht man den Grund fuer eine stumme Presence im Discord-Zweig,
    # obwohl nur eine Datei im Datenordner liegt.
    if is_paused():
        logging.info("Presence ist pausiert (%s) - presence_resume aufrufen "
                     "oder die Datei loeschen", PAUSE_PATH)

    # COM fuer diesen Faden anfordern. Wird claude_rpc eingebettet und die
    # Schleife nicht im Hauptfaden gestartet, scheitert sonst jeder
    # UI-Automation-Aufruf mit "CoInitialize wurde nicht aufgerufen".
    init_com()

    # Leer gelassen heisst: die Plattform entscheidet. Ein fest eingetragenes
    # "claude.exe" waere unter Linux schlicht falsch.
    process_names = {n.lower()
                     for n in (cfg.get("process_names") or DEFAULT_PROCESS_NAMES)}
    logging.info("Erkenne Claude an: %s", ", ".join(sorted(process_names)))
    idle_timeout = cfg.get("idle_timeout_minutes", 25) * 60
    active_threshold = cfg.get("active_input_threshold_seconds", 90)
    poll = cfg.get("poll_interval_seconds", 5)
    open_pool = (cfg.get("texts", {}).get("open")) or ["Claude Desktop"]

    # Erst die Schwelle anmelden, dann messen: unter Wayland liefert der
    # Compositor keine Leerlaufzeit, sondern meldet nur das Ueberschreiten
    # genau dieser Grenze.
    idle_configure(active_threshold)
    ui_cfg = cfg.get("ui_watcher") or {}
    if ui_cfg.get("enabled", True):
        # Ohne diese Schalter veroeffentlicht Electron unter Linux keinen
        # Baum, und der UIWatcher sieht ein leeres Fenster. So frueh wie
        # moeglich, weil Chromium sie beim Start des Renderers liest: fuer
        # das gerade laufende Claude kommt der Schalter zu spaet, fuer den
        # naechsten Start nicht. Unter Windows ist der Aufruf wirkungslos.
        accessibility_enable(ui_cfg.get("announce_screen_reader", True))
    logging.info("Leerlaufmessung: %s", idle_backend_name())

    local_usage = LocalUsageWatcher(cfg.get("local_usage"))
    limits = LimitStore(cfg.get("ui_limits"))
    session = SessionInfo(cfg.get("session_info"))
    beacon = CoworkBeacon(cfg.get("cowork_beacon"))
    activity = ActivityWatcher(cfg.get("activity"))
    tool_history = ToolHistoryWatcher(cfg.get("tool_history"))
    local_session = LocalSessionWatcher(cfg.get("local_session"))
    ui = UIWatcher(cfg.get("ui_watcher"))
    # Welcher Weg das Fenster liest, entscheidet sich zur Laufzeit. Steht
    # das nicht im Protokoll, sucht man den Grund fuer eine leere erste
    # Zeile spaeter im falschen Modul.
    logging.info("UI-Watcher: %s (%s)",
                 "aus" if not ui_cfg.get("enabled", True) else "an",
                 ui.quelle_text())
    tool_in_use = re.compile(
        ui_cfg.get("tool_status_pattern", r"(wird verwendet|is using)"),
        re.I,
    )
    presence = RichPresence(client_id)
    pool = beacons.Pool(DATA_DIR)

    wechsel_takt = (cfg.get("state_line") or {}).get("alternate_seconds", 20)

    def anzeigen(jetzt, eigen=None):
        """Waehlt aus, wer gerade zu sehen ist, und sendet ihn.

        Zwei Regeln, mehr nicht:

        Erstens -- arbeitet gerade jemand wirklich, gehoert ihm die
        Anzeige allein, und zwar dem juengsten. Wer tippt, will nicht
        alle zwanzig Sekunden von einem ruhenden Nachbarn verdraengt
        werden.

        Zweitens -- arbeitet niemand, wandert die Anzeige der Reihe nach
        durch alle offenen Clients und dort durch alles, was ueber sie
        bekannt ist. Erst Claude mit Sitzung, Auslastung und Abo, dann
        Antigravity, dann Codex, dann wieder von vorn.

        Rueckgabe ist die gesendete Nutzlast oder None.
        """
        eintraege = pool.lesen(jetzt)
        chef = beacons.arbeiter(eintraege)
        if chef is None:
            liste = beacons.karten(
                eigen, [e for e in eintraege if e["client"] != "claude"], cfg)
        elif chef["client"] == "claude":
            liste = beacons.karten(eigen, [], cfg)
        else:
            liste = beacons.karten(None, [chef], cfg)
        karte = beacons.karte_waehlen(liste, jetzt, wechsel_takt)
        if karte is None:
            return None
        payload = karte_payload(karte, cfg)
        presence.update(payload)
        return payload

    # Die Abo-Stufe steht im Nutzungsfenster ("Max (5x)") und wird von dort
    # uebernommen. plan_override greift, solange sie noch nie gesehen wurde.
    plan_cfg = cfg.get("plan") or {}
    plan_override = plan_cfg.get("override") or ""
    plan_template = plan_cfg.get("template", "Abonnement: {plan}")

    session_start = None
    last_active = 0.0
    last_hint = 0.0
    logging.info("claude_rpc gestartet")

    while True:
        now = time.time()
        try:
            # Herzschlag und Vorrang. Erst melden, dann nachsehen: sonst
            # sieht der andere in genau diesem Durchlauf nichts von uns.
            beacons.sender_melden(DATA_DIR, rolle)
            hoeher = beacons.fremder_sender(DATA_DIR, rolle, jetzt=now)
            if hoeher is not None:
                logging.info("Ein %s-Prozess (PID %s) uebernimmt - dieser "
                             "Prozess hoert auf zu senden.",
                             hoeher.get("rolle"), hoeher.get("pid"))
                presence.clear()
                beacons.sender_abmelden(DATA_DIR)
                release_instance()
                return True

            if is_paused():
                presence.clear()
                session_start = None
                time.sleep(max(poll, 5))
                continue

            if not claude_running(process_names):
                # Claude ist weg, aber Codex oder Antigravity arbeiten
                # vielleicht weiter. Erst danach wirklich abschalten.
                beacons.eigenen_schreiben(DATA_DIR, "idle", "idle", None, None)
                session_start = None
                last_active = 0.0
                if anzeigen(now) is not None:
                    time.sleep(poll)
                    continue
                presence.clear()
                # Heisst der Hauptprozess auf diesem System anders, sitzt man
                # sonst vor einer stummen Presence und raet. Hoechstens
                # stuendlich, damit das Log nicht zulaeuft.
                if now - last_hint >= 3600:
                    last_hint = now
                    kandidaten = claude_candidates()
                    if kandidaten:
                        logging.info(
                            "Claude nicht erkannt. Gefunden wurden: %s",
                            "; ".join("%s (%s)" % (n, p or "?")
                                      for _i, n, p in kandidaten[:5]),
                        )
                time.sleep(max(poll, 15))
                continue

            # Fokus und Leerlaufzeit sind nicht ueberall zu haben. Wo der
            # Rechner sie nicht hergibt, gilt der laufende Prozess als bestes
            # Signal -- die Presence bleibt dann sichtbar, solange Claude
            # laeuft. Beide Aufrufe entscheiden im Zweifel fuer "aktiv".
            focused = claude_focused(process_names)
            ruhig = idle_seconds() <= active_threshold if idle_supported() else True
            currently_active = focused and ruhig
            if currently_active:
                last_active = now

            show = bool(last_active) and (now - last_active) <= idle_timeout
            if not show:
                beacons.eigenen_schreiben(DATA_DIR, "idle", "idle", None, None)
                session_start = None
                if anzeigen(now) is not None:
                    time.sleep(poll)
                    continue
                presence.clear()
                time.sleep(poll)
                continue

            if session_start is None:
                session_start = int(now)

            state_parts = []
            # Der Scan laeuft ohnehin -- steht das Nutzungsfenster gerade
            # offen, werden die Limits im Vorbeigehen mitgenommen.
            limits.update(ui.refresh())
            # Die Oberflaeche meldet nur "<Server> wird verwendet" -- welches
            # Werkzeug gerade laeuft, steht ausschliesslich im Verlauf von
            # Desktop Commander. Sind beide frisch, gewinnt die genauere
            # Angabe; sonst UI-Status, Verlauf, zuletzt das mtime-Signal.
            ui_status = ui.status()
            tool_text = tool_history.get()
            if ui_status and tool_text and tool_in_use.search(ui_status):
                act_text = tool_text
            else:
                act_text = ui_status or tool_text or activity.get()
            info_text = (
                session.get()
                or local_session.get()
                or ui.info()
                or beacon.get(activity_fresh=bool(act_text))
            )

            # Erste Zeile ist die schnelle: was Claude in diesem Moment tut.
            # Ohne laufende Taetigkeit steht dort der Leerlauftext.
            details = act_text or open_pool[0]

            # Zweite Zeile ist die langsame: Sitzung, Auslastung, Abo. Diese
            # drei aendern sich im Minutentakt, deshalb darf hier rotiert
            # werden, ohne dass etwas uebersehen wird.
            if info_text:
                state_parts.append(info_text)
            # 5h und Woche stehen frisch in der lokalen Datei der App. Das
            # modellspezifische Limit gibt es dort nicht -- es kommt aus dem
            # Nutzungsfenster und altert, bis es ganz herausfaellt.
            usage_parts = [p for p in (local_usage.get(), limits.model_limit()) if p]
            token_text = " · ".join(usage_parts) or None
            if token_text:
                state_parts.append(token_text)
            plan_text = limits.plan() or plan_override
            if plan_text:
                state_parts.append(plan_template.replace("{plan}", plan_text))
            # "working" nur, wenn Claude wirklich etwas tut. Ein offenes,
            # fokussiertes Fenster ohne laufende Taetigkeit ist "waiting"
            # -- sonst gaebe es nie einen ruhigen Moment, in dem die
            # Anzeige zu Codex oder Antigravity weiterwandern kann.
            beacons.eigenen_schreiben(
                DATA_DIR,
                "working" if (currently_active and act_text) else "waiting",
                "thinking",
                None,
                session_start,
            )
            eigen = {
                "details": details,
                "zeilen": state_parts,
                "start": session_start,
                "aktiv": currently_active,
            }
            payload = anzeigen(now, eigen) or {}
            LAST_STATE.update({
                "updated_at": int(now),
                "details": payload.get("details"),
                "state": payload.get("state"),
                "activity": act_text,
                "info": info_text,
                "usage": token_text,
                "active": currently_active,
                "paused": _PAUSED,
                "limits": limits.status(),
            })
            publish_state()
        except Exception as exc:
            logging.warning("Hauptschleife: %s", exc)
        time.sleep(poll)


if __name__ == "__main__":
    main()
