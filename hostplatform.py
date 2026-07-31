"""Alles, was pro Betriebssystem verschieden ist, an einer Stelle.

claude_rpc.py kennt danach nur noch diese Schnittstelle:

    iter_processes()            (pid, exe-name klein, None)
    process_path(pid)           voller Pfad oder ""
    process_cmdline(pid)        Befehlszeile oder ""
    foreground_process_name()   Name des Fensters im Vordergrund oder ""
    idle_seconds()              Sekunden seit der letzten Eingabe
    single_instance(name)       False, wenn schon eine Instanz laeuft
    claude_config_dir()         Datenordner der Claude-Desktop-App

Zwei Zusagen sind ausdruecklich optional, weil Linux sie nicht ueberall
hergibt: FOCUS_SUPPORTED und IDLE_SUPPORTED. Wo sie False sind, darf sich
der Aufrufer nicht auf die Werte verlassen, sondern muss auf ein groeberes
Signal ausweichen -- unter Wayland ist die Abfrage des aktiven Fensters
vom Protokoll her nicht vorgesehen, das ist kein Bibliotheksproblem.
"""
import logging
import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


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
        voellig anderen Interpreter gestartet wurde. Das Handle bleibt
        absichtlich fuer die Prozesslaufzeit offen."""
        global _INSTANCE_LOCK
        _INSTANCE_LOCK = kernel32.CreateMutexW(None, False, "Local\\" + name)
        return kernel32.GetLastError() != ERROR_ALREADY_EXISTS

    def claude_config_dir():
        return Path(os.environ.get("APPDATA", "")) / "Claude"


else:
    # Linux (Stufe 1): alles, was ohne Fenstersystem auskommt.
    #
    # Fokus und Leerlaufzeit bleiben bewusst offen. Unter X11 waeren sie
    # ueber python-xlib nachruestbar, unter Wayland gibt es sie aus
    # Sicherheitsgruenden gar nicht. Solange FOCUS_SUPPORTED False ist,
    # weicht der Aufrufer auf "laeuft Claude ueberhaupt" aus.
    import fcntl

    FOCUS_SUPPORTED = False
    IDLE_SUPPORTED = False

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
        return ""   # siehe FOCUS_SUPPORTED

    def idle_seconds():
        return 0.0  # siehe IDLE_SUPPORTED

    def single_instance(name="claude_rpc_presence"):
        """Sperrdatei mit flock. Der Deskriptor bleibt absichtlich offen;
        das Betriebssystem gibt die Sperre beim Prozessende frei, auch
        wenn der Prozess abstuerzt."""
        global _INSTANCE_LOCK
        runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        try:
            handle = open(os.path.join(runtime, name + ".lock"), "w")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        _INSTANCE_LOCK = handle
        return True

    def claude_config_dir():
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return Path(base) / "Claude"


def claude_running(process_names):
    """Laeuft mindestens einer der genannten Prozesse?"""
    for _pid, name, _path in iter_processes():
        if name in process_names:
            return True
    return False


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
