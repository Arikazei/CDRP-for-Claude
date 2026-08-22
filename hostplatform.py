"""Alles, was pro Betriebssystem verschieden ist, an einer Stelle.

claude_rpc.py kennt danach nur noch diese Schnittstelle:

    iter_processes()            (pid, exe-name klein, None)
    process_path(pid)           voller Pfad oder ""
    process_cmdline(pid)        Befehlszeile oder ""
    claude_focused(namen)       Hat Claude gerade den Fokus?
    idle_seconds()              Sekunden seit der letzten Eingabe
    idle_supported()            Traegt die Leerlaufmessung hier ueberhaupt?
    idle_configure(sekunden)    Schwelle setzen, bevor gemessen wird
    single_instance(name)       False, wenn schon eine Instanz laeuft
    claude_config_dir()         Datenordner der Claude-Desktop-App
    accessibility_enable()      Barrierefreiheitsbruecke anschalten (Linux)
    ui_tree_supported()         Gibt es hier einen Fensterbaum neben UIA?
    ui_tree_nodes(...)          Fensterbaum als (tiefe, rolle, name)

Fokus und Leerlaufzeit sind ausdruecklich optional. Unter Windows gibt es
fuer beides genau eine Antwort; unter Linux haengen sie von der
Arbeitsumgebung und vom Fenstersystem ab, weshalb linuxdesktop.py der
Reihe nach alle gaengigen Wege durchprobiert. Wo nichts traegt, meldet
idle_supported() False und claude_focused() True -- der Aufrufer weicht
dann auf "laeuft Claude ueberhaupt" aus, statt auf falschen Messwerten
Entscheidungen zu treffen.
"""
import logging
import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# Wird nur im Linux-Zweig gesetzt. Der Vorbelegung wegen darf jede Funktion
# weiter unten den Namen nennen, ohne auf die Auswertungsreihenfolge von
# "or" angewiesen zu sein.
linuxdesktop = None


if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes

    FOCUS_SUPPORTED = True
    IDLE_SUPPORTED = True

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    MAX_PATH_LONG = 32768
    ERROR_ALREADY_EXISTS = 183

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
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR,
    ]

    _INSTANCE_LOCK = None

    def iter_processes():
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

    def process_path(pid):
        """Bewusst ueber ctypes statt psutil: das Paket bringt eine
        kompilierte .pyd mit, und das Bundle soll ohne fremde Binaerdateien
        auskommen (Virenscanner-Fehlalarme, Signaturfragen)."""
        if not pid:
            return ""
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = ctypes.wintypes.DWORD(MAX_PATH_LONG)
            buf = ctypes.create_unicode_buffer(MAX_PATH_LONG)
            if kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def process_cmdline(pid):
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\")"
                 ".CommandLine" % pid],
                capture_output=True, text=True, timeout=15,
                creationflags=0x08000000,
            )
            return (result.stdout or "").strip()
        except Exception:
            return ""

    def foreground_process_name():
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = process_path(pid.value)
        return os.path.basename(path).lower() if path else ""

    def idle_seconds():
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        user32.GetLastInputInfo(ctypes.byref(info))
        return max(0.0, (kernel32.GetTickCount() - info.dwTime) / 1000.0)

    def single_instance(name="claude_rpc_presence"):
        """Benannter Mutex - greift auch, wenn die andere Instanz mit einem
        voellig anderen Interpreter gestartet wurde.

        Nur der Gewinner behaelt sein Handle, und zwar fuer die
        Prozesslaufzeit. Wer verliert, schliesst seines sofort wieder: ein
        benanntes Mutex-Objekt lebt so lange, wie IRGENDEIN Prozess ein
        Handle darauf haelt. Behielten die Antworter ihres, ueberlebte die
        Sperre den Sender -- danach faende jede neu gestartete Instanz die
        Sperre belegt vor, obwohl niemand mehr sendet, und die Presence
        bliebe bis zum letzten Prozessende stumm.
        """
        global _INSTANCE_LOCK
        # SetLastError(0) ist hier Pflicht, nicht Vorsicht.
        #
        # CreateMutexW setzt ERROR_ALREADY_EXISTS, wenn das Objekt schon
        # da war. Gelingt der Aufruf mit einem NEUEN Objekt, laesst die
        # Funktion den letzten Fehlercode des Fadens dagegen unberuehrt
        # -- was immer vorher darin stand, steht danach noch drin.
        #
        # Genau das ist am 22.08.2026 passiert: unmittelbar davor lief
        # beacons.sender_melden(), und dessen mkdir(exist_ok=True) endet
        # auf einem vorhandenen Ordner mit CreateDirectory ->
        # ERROR_ALREADY_EXISTS (183). Der frisch erzeugte Mutex sah
        # damit aus wie ein bereits belegter. Der Dienst hielt sich fuer
        # die zweite Instanz, sendete nie, und die Extension trat
        # gleichzeitig zurueck, weil der Dienst sich ordentlich
        # angemeldet hatte. Niemand sendete mehr, und im Protokoll stand
        # nur "laeuft bereits" -- eine Meldung, die man dreimal liest,
        # bevor man ihr misstraut.
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, "Local\\" + name)
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            return False
        _INSTANCE_LOCK = handle
        return True

    def release_instance():
        """Sperre freigeben, ohne den Prozess zu beenden.

        Gebraucht, seit der eigenstaendige Dienst Vorrang hat: die
        Extension hoert auf zu senden und muss die Sperre abgeben,
        sonst wartet der Dienst ewig auf ein Objekt, das niemand mehr
        benutzt.
        """
        global _INSTANCE_LOCK
        if _INSTANCE_LOCK:
            kernel32.CloseHandle(_INSTANCE_LOCK)
        _INSTANCE_LOCK = None

    def claude_config_dir():
        return Path(os.environ.get("APPDATA", "")) / "Claude"

    def app_data_dir():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "ClaudeDiscordPresence"

    DEFAULT_PROCESS_NAMES = ("claude.exe",)


else:
    # Linux: Prozesse und Pfade hier, alles Desktopnahe in linuxdesktop.py.
    #
    # Der Import ist bewusst weich: fehlt jeepney oder laeuft der Daemon
    # ohne Sitzungsbus, soll die Presence trotzdem starten und nur auf
    # Fokus und Leerlauf verzichten.
    import fcntl

    try:
        import linuxdesktop
    except Exception as _exc:                       # pragma: no cover
        linuxdesktop = None
        logging.info("linuxdesktop nicht verfuegbar: %s", _exc)

    FOCUS_SUPPORTED = linuxdesktop is not None
    IDLE_SUPPORTED = linuxdesktop is not None

    _INSTANCE_LOCK = None

    def iter_processes():
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open("/proc/%s/comm" % entry, encoding="utf-8") as handle:
                    name = handle.read().strip().lower()
            except OSError:
                continue
            yield int(entry), name, None

    def process_path(pid):
        try:
            return os.readlink("/proc/%d/exe" % pid)
        except OSError:
            return ""

    def process_cmdline(pid):
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as handle:
                return handle.read().replace(b"\0", b" ").decode(
                    "utf-8", "ignore").strip()
        except OSError:
            return ""

    def foreground_process_name():
        """Unter Linux nicht beantwortbar -- weder X11 noch Wayland geben
        den Prozessnamen des aktiven Fensters heraus. Die Frage, auf die es
        ankommt, beantwortet claude_focused() ueber AT-SPI."""
        return ""

    def idle_seconds():
        return linuxdesktop.leerlauf_sekunden() if linuxdesktop else 0.0

    def single_instance(name="claude_rpc_presence"):
        """Sperrdatei mit flock. Der Deskriptor bleibt absichtlich offen;
        das Betriebssystem gibt die Sperre beim Prozessende frei, auch
        wenn der Prozess abstuerzt."""
        global _INSTANCE_LOCK
        runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        handle = None
        try:
            handle = open(os.path.join(runtime, name + ".lock"), "w")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Wer verliert, gibt den Deskriptor sofort zurueck, statt ihn bis
            # zur naechsten Speicherbereinigung zu halten.
            if handle is not None:
                handle.close()
            return False
        _INSTANCE_LOCK = handle
        return True

    def release_instance():
        """Sperre freigeben, ohne den Prozess zu beenden. Siehe Windows."""
        global _INSTANCE_LOCK
        if _INSTANCE_LOCK is not None:
            try:
                fcntl.flock(_INSTANCE_LOCK, fcntl.LOCK_UN)
            except OSError:
                pass
            _INSTANCE_LOCK.close()
        _INSTANCE_LOCK = None

    def claude_config_dir():
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return Path(base) / "Claude"

    def app_data_dir():
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        return Path(base) / "ClaudeDiscordPresence"

    # Das Debian-Paket installiert die Anwendung als "claude-desktop".
    # Der nackte Name "claude" gehoert der Kommandozeilenfassung
    # (/opt/claude-code/bin/claude) und ist deshalb bewusst NICHT dabei --
    # sonst zeigt die Presence "Claude Desktop", waehrend nur die CLI
    # laeuft. Auf echtem Linux gegengeprueft.
    DEFAULT_PROCESS_NAMES = ("claude-desktop",)


def claude_running(process_names):
    """Laeuft mindestens einer der genannten Prozesse?"""
    for _pid, name, _path in iter_processes():
        if name in process_names:
            return True
    return False


def claude_candidates():
    """Prozesse, deren Name nach Claude aussieht, mit Pfad.

    Nur fuer die Fehlersuche: heisst der Hauptprozess auf einem System
    anders als erwartet, findet man ihn hier, statt vor einer stummen
    Presence zu sitzen und zu raten.
    """
    treffer = []
    for pid, name, _ in iter_processes():
        if "claude" in name:
            treffer.append((pid, name, process_path(pid)))
    return treffer


def claude_focused(process_names):
    """Hat Claude gerade den Fokus? Im Zweifel True.

    Windows fragt das Fenster im Vordergrund ab. Linux geht ueber AT-SPI,
    weil das unter Wayland der einzige desktopuebergreifende Weg ist. Laesst
    sich die Frage nicht beantworten -- keine Barrierefreiheitsbruecke, kein
    Sitzungsbus --, lautet die Antwort True: lieber eine Presence zu viel als
    eine, die grundlos verschwindet.
    """
    if IS_WINDOWS:
        return foreground_process_name() in process_names
    if not IS_LINUX or linuxdesktop is None:
        return True
    antwort = linuxdesktop.claude_im_vordergrund()
    return True if antwort is None else antwort


def idle_supported():
    """Traegt die Leerlaufmessung auf diesem Rechner?

    Unter Linux steht das erst nach dem ersten Versuch fest, weil die
    Antwort von der Arbeitsumgebung abhaengt. Deshalb eine Funktion und
    keine Konstante.
    """
    if IS_WINDOWS:
        return True
    if not IS_LINUX or linuxdesktop is None:
        return False
    return linuxdesktop.leerlauf_verfuegbar()


def idle_configure(sekunden):
    """Schwelle fuer die Leerlaufmessung anmelden.

    Muss vor der ersten Messung kommen: der Wayland-Weg liefert keine Zeit,
    sondern meldet das Ueber- und Unterschreiten genau dieser Schwelle.
    """
    if IS_LINUX and linuxdesktop is not None:
        linuxdesktop.leerlauf_schwelle_setzen(sekunden)


def idle_backend_name():
    """Welcher Weg misst gerade? Nur fuer das Protokoll."""
    if IS_WINDOWS:
        return "GetLastInputInfo"
    if not IS_LINUX or linuxdesktop is None:
        return "keins"
    return linuxdesktop.leerlauf_name()


def accessibility_enable(bildschirmleser=True):
    """Barrierefreiheitsbruecke einschalten (nur Linux).

    Zwei Schalter, nicht einer, und der Unterschied hat Stunden gekostet:
    org.a11y.Status.IsEnabled bewegt Electron nur dazu, das Fenstergeruest
    zu veroeffentlichen -- vier Knoten, kein Inhalt. Den Seitenbaum baut
    Chromium erst auf, wenn sich ein Bildschirmleser anmeldet, weil das
    Rechenzeit kostet und sonst niemand danach fragt. Diese Anmeldung ist
    ScreenReaderEnabled.

    Beide werden beim Start des Daemons gesetzt und bleiben fuer die
    Sitzung stehen. Fuer eine bereits laufende Claude-Instanz kommt der
    Schalter zu spaet -- Chromium liest ihn beim Start des Renderers.
    Deshalb wird hier so frueh wie moeglich geschaltet: der naechste Start
    von Claude bringt den Baum dann von sich aus mit.
    """
    if not (IS_LINUX and linuxdesktop is not None):
        return False
    bruecke = False
    try:
        bruecke = bool(linuxdesktop.barrierefreiheit_einschalten())
    except Exception as exc:
        logging.info("Barrierefreiheit nicht einschaltbar: %s", exc)
    if not bildschirmleser:
        logging.info("Barrierefreiheitsbruecke: %s, Bildschirmleser bleibt "
                     "auf Wunsch aus", "an" if bruecke else "nicht erreichbar")
        return bruecke
    leser = False
    try:
        leser = bool(linuxdesktop.bildschirmleser_melden(True))
    except Exception as exc:
        logging.info("Bildschirmleser nicht anmeldbar: %s", exc)
    logging.info("Barrierefreiheit: Bruecke %s, Bildschirmleser %s",
                 "an" if bruecke else "nicht erreichbar",
                 "angemeldet" if leser else "nicht anmeldbar")
    return bruecke


def ui_tree_supported():
    """Laesst sich der Fensterbaum ueber die Plattformschicht auslesen?

    Gemeint ist ausdruecklich der Weg neben UI Automation: unter Windows
    liest claude_rpc direkt ueber uiautomation, hier steht deshalb False.
    """
    return bool(not IS_WINDOWS and IS_LINUX and linuxdesktop is not None)


def ui_tree_nodes(suchbegriff="claude", max_nodes=3000, budget_seconds=4.0):
    """Fensterbaum als flache Liste (tiefe, rolle, name), sonst None.

    None heisst "diese Plattform kann es nicht", eine leere Liste heisst
    "Claude ist gerade nicht im Baum". Der Aufrufer muss beides
    unterscheiden koennen, sonst schaltet er den Watcher beim ersten
    geschlossenen Fenster dauerhaft ab.
    """
    if not ui_tree_supported():
        return None
    try:
        return linuxdesktop.atspi_knoten(suchbegriff, max_nodes, budget_seconds)
    except Exception as exc:
        logging.info("AT-SPI-Baum nicht lesbar: %s", exc)
        return []


def init_com():
    """COM fuer diesen Faden anfordern (nur Windows).

    Laeuft die Presence-Schleife nicht im Hauptfaden, scheitert sonst jeder
    UI-Automation-Aufruf mit "CoInitialize wurde nicht aufgerufen".
    """
    if not IS_WINDOWS:
        return
    try:
        import comtypes
        comtypes.CoInitializeEx()
    except Exception as exc:
        logging.info("COM bereits initialisiert oder nicht noetig: %s", exc)
