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
import ctypes
import ctypes.wintypes
import json
import logging
import os
import time
from pathlib import Path

import re

import urllib.error
import urllib.request

from pypresence import Presence

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
_PAUSED = False


def set_paused(value):
    global _PAUSED
    _PAUSED = bool(value)
    logging.info("Presence %s", "pausiert" if _PAUSED else "aktiv")
    return _PAUSED


def is_paused():
    return _PAUSED


# Momentaufnahme fuer den MCP-Server (Werkzeug "presence_status").
LAST_STATE = {}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH_LONG = 32768


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


# Rueckgabetypen setzen: ohne das schneidet ctypes 64-Bit-Handles auf
# 32 Bit zurecht und die Aufrufe schlagen sporadisch fehl.
kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
]
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.OpenProcess.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD,
]
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
kernel32.Process32FirstW.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W),
]
kernel32.Process32NextW.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W),
]
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
    ctypes.wintypes.LPWSTR, ctypes.POINTER(ctypes.wintypes.DWORD),
]


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def http_get_json(url, token, timeout=10):
    """GET mit Bearer-Token, nur mit der Standardbibliothek.

    Ersatz fuer requests: dessen Abhaengigkeit charset-normalizer bringt
    eine kompilierte Erweiterung mit, und das Bundle soll ohne fremde
    Binaerdateien auskommen. Rueckgabe: (HTTP-Status, Daten); Status 0
    steht fuer einen Netzwerkfehler.
    """
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer %s" % token,
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:
        logging.warning("HTTP-Aufruf fehlgeschlagen: %s", exc)
        return 0, None


def idle_seconds():
    """Sekunden seit letzter Tastatur-/Mauseingabe (systemweit)."""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    user32.GetLastInputInfo(ctypes.byref(info))
    return max(0.0, (kernel32.GetTickCount() - info.dwTime) / 1000.0)


def process_path(pid):
    """Vollstaendiger Pfad zur EXE einer PID, sonst "".

    Bewusst ueber ctypes statt psutil: das Paket bringt eine kompilierte
    .pyd mit, und das gebuendelte MCPB soll ohne fremde Binaerdateien
    auskommen (Virenscanner-Fehlalarme, Signaturfragen).
    """
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.wintypes.DWORD(MAX_PATH_LONG)
        buf = ctypes.create_unicode_buffer(MAX_PATH_LONG)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def iter_processes():
    """(pid, exe-name klein, voller Pfad) ueber alle sichtbaren Prozesse."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            yield entry.th32ProcessID, (entry.szExeFile or "").lower(), None
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)


def foreground_process_name():
    """Prozessname des Fensters im Vordergrund (klein geschrieben)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    path = process_path(pid.value)
    return os.path.basename(path).lower() if path else ""


def claude_running(process_names):
    for _pid, name, _path in iter_processes():
        if name in process_names:
            return True
    return False


class TokenStatus:
    """Modul: 5h-/Wochen-Auslastung via Claude-Code-OAuth-Endpoint."""

    URL = "https://api.anthropic.com/api/oauth/usage"

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.text = None
        self.next_refresh = 0.0
        self.ok = False
        self._plan = None
        self._plan_refresh = 0.0

    def plan(self):
        """Abo-Variante (z. B. "Max 5x") live vom Profil-Endpoint."""
        if not self.cfg.get("show_plan"):
            return None
        if not self.cfg.get("enabled"):
            # Modul aus: kein Zugriff auf .credentials.json, kein API-Aufruf.
            return self.cfg.get("plan_override") or None
        now = time.time()
        if now >= self._plan_refresh:
            self._plan_refresh = now + 12 * 3600
            self._plan = (
                self.cfg.get("plan_override")
                or self._fetch_plan()
                or self._plan
            )
        return self._plan or None

    def _fetch_plan(self):
        try:
            creds_path = Path.home() / ".claude" / ".credentials.json"
            creds = json.loads(creds_path.read_text(encoding="utf-8"))
            token = creds.get("claudeAiOauth", {}).get("accessToken")
            if not token:
                return None
            status, data = http_get_json(
                "https://api.anthropic.com/api/oauth/profile", token
            )
            if status != 200 or data is None:
                logging.warning("Profil-Endpoint: HTTP %s", status)
                return None
            blob = json.dumps(data)
            match = re.search(r"max_(\d+)x", blob)
            if match:
                return f"Max {match.group(1)}x"
            if "claude_max" in blob:
                return "Max"
            if "claude_pro" in blob:
                return "Pro"
            sub = creds.get("claudeAiOauth", {}).get("subscriptionType") or ""
            return sub.capitalize() if sub else None
        except Exception as exc:
            logging.warning("Plan-Abfrage fehlgeschlagen: %s", exc)
            return None

    def get(self):
        if not self.cfg.get("enabled"):
            return None
        now = time.time()
        if now >= self.next_refresh:
            self.text = self._fetch()
            interval = self.cfg.get("refresh_minutes", 5) * 60
            if not self.ok:
                interval = min(interval, 180)
            self.next_refresh = now + interval
        return self.text

    def _fetch(self):
        self.ok = False
        try:
            creds_path = Path.home() / ".claude" / ".credentials.json"
            creds = json.loads(creds_path.read_text(encoding="utf-8"))
            token = creds.get("claudeAiOauth", {}).get("accessToken")
            if not token:
                return None
            status, data = http_get_json(self.URL, token)
            if status != 200 or data is None:
                logging.warning("Usage-Endpoint: HTTP %s", status)
                return self.text
            parts = []
            for lim in data.get("limits") or []:
                pct = lim.get("percent")
                if not isinstance(pct, (int, float)):
                    continue
                kind = lim.get("kind")
                if kind == "session":
                    parts.append(f"5h {pct:.0f}%")
                elif kind == "weekly_all":
                    parts.append(f"Woche {pct:.0f}%")
                elif kind == "weekly_scoped" and self.cfg.get("show_scoped", True):
                    scope = (lim.get("scope") or {}).get("model") or {}
                    name = scope.get("display_name") or "Modell"
                    parts.append(f"{name} {pct:.0f}%")
            if not parts:
                five = self._utilization(data, ["five_hour"])
                week = self._utilization(
                    data, ["seven_day", "seven_day_overall", "weekly"]
                )
                if five is not None:
                    parts.append(f"5h: {five:.0f}%")
                if week is not None:
                    parts.append(f"Woche: {week:.0f}%")
            if self.cfg.get("show_plan") and parts and (
                self.cfg.get("plan_position", "info") == "tokens"
            ):
                plan = self.plan()
                if plan:
                    parts.insert(0, plan)
            self.ok = True
            return " · ".join(parts) if parts else None
        except Exception as exc:
            logging.warning("Token-Status fehlgeschlagen: %s", exc)
            return self.text

    @staticmethod
    def _utilization(data, keys):
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                util = value.get("utilization")
                if isinstance(util, (int, float)):
                    return float(util)
        return None


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
        self.log_dir = Path(os.environ.get("APPDATA", "")) / "Claude" / "logs"

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

    def get(self):
        if not (self.cfg.get("enabled") and _uia):
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


class UIWatcher:
    """Modul: ein einziger Durchlauf durch den Accessibility-Tree des
    Claude-Fensters (Windows UI Automation).

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
        self.stop_names = {
            n.lower()
            for n in self.cfg.get(
                "stop_button_names",
                ["antwort stoppen", "stop response", "antwort anhalten"],
            )
        }
        self.composer_re = re.compile(
            self.cfg.get(
                "composer_pattern",
                r"(Anfrage an Claude|Nachricht|Message Claude|Reply to Claude)",
            ),
            re.I,
        )
        self.lookback = self.cfg.get("status_lookback", 12)
        self.require_busy = self.cfg.get("require_busy", True)

    def refresh(self):
        if not (self.cfg.get("enabled", True) and _uia):
            self.data = {}
            return self.data
        now = time.time()
        if now >= self.next_refresh:
            self.next_refresh = now + self.cfg.get("refresh_seconds", 8)
            self.data = self._scan()
        return self.data

    def info(self):
        model = self.data.get("model")
        if not model:
            return None
        return self.cfg.get("template", "using cowork with {model}").replace(
            "{model}", model
        )

    def status(self):
        text = self.data.get("status")
        if text:
            return text
        if self.data.get("busy") and self.cfg.get("busy_text"):
            return self.cfg["busy_text"]
        return None

    def busy(self):
        return bool(self.data.get("busy"))

    def _scan(self):
        out = {}
        try:
            _uia.SetGlobalSearchTimeout(2)
            win = UIModelWatcher._find_window()
            if win is None:
                self._ax_ready = False
                return {}
            if not self._ax_ready:
                doc = _uia.DocumentControl(searchFromControl=win)
                if not doc.Exists(3, 1):
                    return {}
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

            models = []
            composer_at = -1
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
                elif kind == "EditControl" and self.composer_re.search(name):
                    composer_at = index
            if models:
                out["model"] = models[-1]

            # Die Statuszeile steht unmittelbar ueber dem Eingabefeld. Ohne
            # diesen Anker wuerde auch Text aus dem Chatverlauf passen -- ein
            # Chat, in dem "... wird verwendet" vorkommt, hat die Presence
            # sonst dauerhaft falsch beschriftet.
            if composer_at > 0 and (out.get("busy") or not self.require_busy):
                start = max(0, composer_at - self.lookback)
                candidates = [
                    name
                    for kind, name in nodes[start:composer_at]
                    if kind == "TextControl"
                    and len(name) <= 80
                    and name.endswith("…")
                ]
                if candidates:
                    known = [c for c in candidates if self.status_re.search(c)]
                    # Bekannte Formulierung bevorzugen, sonst die letzte
                    # Zeile ueber dem Eingabefeld -- so ueberleben auch
                    # Statustexte, die es heute noch nicht gibt.
                    out["status"] = (known or candidates)[-1].rstrip("… .")
            return out
        except Exception as exc:
            logging.warning("UI-Watcher fehlgeschlagen: %s", exc)
            return {}


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
        self.root = (
            Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code-sessions"
        )
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
            else Path(os.environ.get("APPDATA", "")) / "Claude"
            / "plan-usage-history.json"
        )
        self.next_refresh = 0.0
        self.text = None

    def get(self):
        if not self.cfg.get("enabled", False):
            return None
        now = time.time()
        if now >= self.next_refresh:
            self.next_refresh = now + self.cfg.get("refresh_minutes", 5) * 60
            self.text = self._read()
        return self.text

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
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


class RichPresence:
    """Duenner Wrapper um pypresence mit Auto-Reconnect."""

    def __init__(self, client_id):
        self.client_id = client_id
        self.rpc = None
        self.last_payload = None

    def _connect(self):
        if self.rpc is None:
            rpc = Presence(self.client_id)
            rpc.connect()
            self.rpc = rpc
            logging.info("Mit Discord verbunden")

    def update(self, payload):
        try:
            self._connect()
            if payload != self.last_payload:
                self.rpc.update(**payload)
                self.last_payload = payload
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


def main():
    cfg = load_config()
    client_id = str(cfg.get("client_id", ""))
    if not client_id.isdigit():
        logging.error("Keine gueltige client_id in config.json - Abbruch")
        return

    process_names = {n.lower() for n in cfg.get("process_names", ["claude.exe"])}
    idle_timeout = cfg.get("idle_timeout_minutes", 25) * 60
    active_threshold = cfg.get("active_input_threshold_seconds", 90)
    poll = cfg.get("poll_interval_seconds", 5)
    open_pool = (cfg.get("texts", {}).get("open")) or ["Claude Desktop"]

    tokens = TokenStatus(cfg.get("token_status"))
    local_usage = LocalUsageWatcher(cfg.get("local_usage"))
    session = SessionInfo(cfg.get("session_info"))
    beacon = CoworkBeacon(cfg.get("cowork_beacon"))
    activity = ActivityWatcher(cfg.get("activity"))
    tool_history = ToolHistoryWatcher(cfg.get("tool_history"))
    local_session = LocalSessionWatcher(cfg.get("local_session"))
    ui = UIWatcher(cfg.get("ui_watcher"))
    tool_in_use = re.compile(
        (cfg.get("ui_watcher") or {}).get(
            "tool_status_pattern", r"(wird verwendet|is using)"
        ),
        re.I,
    )
    presence = RichPresence(client_id)

    # Pro-Konten haben nur das 5-Stunden- und das Wochenlimit, und beide
    # stehen lokal zur Verfuegung. Max-Konten haben zusaetzlich ein
    # modellspezifisches Limit, das ausschliesslich der API-Endpunkt kennt.
    # Welches Abo vorliegt, ist lokal nirgends hinterlegt (geprueft), deshalb
    # richtet sich der Hinweis nach der angegebenen Abo-Bezeichnung.
    hint_cfg = cfg.get("usage_hint") or {}
    usage_hint = None
    if hint_cfg.get("enabled", True) and not (cfg.get("token_status") or {}).get("enabled"):
        label = (cfg.get("token_status") or {}).get("plan_override") or ""
        if re.search(hint_cfg.get("pattern", r"max"), label, re.I):
            usage_hint = hint_cfg.get("text") or (
                "Abo '%s' erkannt: die Anzeige zeigt nur das 5-Stunden- und das "
                "Wochenlimit. Das modellspezifische Limit gibt es nur ueber die "
                "API-Option - siehe Warnhinweis in der README." % label
            )
            logging.info(usage_hint)

    session_start = None
    last_active = 0.0
    logging.info("claude_rpc gestartet")

    while True:
        now = time.time()
        try:
            if _PAUSED:
                presence.clear()
                session_start = None
                time.sleep(max(poll, 5))
                continue

            if not claude_running(process_names):
                presence.clear()
                session_start = None
                last_active = 0.0
                time.sleep(max(poll, 15))
                continue

            focused = foreground_process_name() in process_names
            currently_active = focused and idle_seconds() <= active_threshold
            if currently_active:
                last_active = now

            show = bool(last_active) and (now - last_active) <= idle_timeout
            if not show:
                presence.clear()
                session_start = None
                time.sleep(poll)
                continue

            if session_start is None:
                session_start = int(now)

            state_parts = []
            ui.refresh()
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
            payload = {"details": details, "start": session_start}

            # Zweite Zeile ist die langsame: Sitzung, Auslastung, Abo. Diese
            # drei aendern sich im Minutentakt, deshalb darf hier rotiert
            # werden, ohne dass etwas uebersehen wird.
            if info_text:
                state_parts.append(info_text)
            # TokenStatus kennt zusaetzlich das modellspezifische Limit, das
            # lokal nirgends abgelegt ist; deshalb hat es Vorrang, wenn aktiv.
            token_text = tokens.get() or local_usage.get()
            if token_text:
                state_parts.append(token_text)
            plan_text = tokens.plan()
            if plan_text:
                template = (cfg.get("token_status") or {}).get(
                    "plan_template", "Abonnement: {plan}"
                )
                state_parts.append(template.replace("{plan}", plan_text))
            if state_parts:
                sl = cfg.get("state_line", {})
                if sl.get("mode", "alternate") == "alternate" and len(state_parts) > 1:
                    step = max(15, sl.get("alternate_seconds", 20))
                    payload["state"] = state_parts[int(now / step) % len(state_parts)]
                else:
                    payload["state"] = " · ".join(state_parts)
            if cfg.get("large_image_key"):
                payload["large_image"] = cfg["large_image_key"]
                payload["large_text"] = cfg.get("large_image_text", "Claude Desktop")
            small_key = cfg.get(
                "small_image_key_active" if currently_active else "small_image_key_open"
            )
            if small_key:
                payload["small_image"] = small_key
                payload["small_text"] = "Aktiv" if currently_active else "Inaktiv"
            if cfg.get("buttons"):
                payload["buttons"] = cfg["buttons"]
            presence.update(payload)
            LAST_STATE.update({
                "updated_at": int(now),
                "details": payload.get("details"),
                "state": payload.get("state"),
                "activity": act_text,
                "info": info_text,
                "usage": token_text,
                "active": currently_active,
                "paused": _PAUSED,
                "hinweis": usage_hint,
            })
        except Exception as exc:
            logging.warning("Hauptschleife: %s", exc)
        time.sleep(poll)


if __name__ == "__main__":
    main()
