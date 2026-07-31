#!/usr/bin/env python3
"""Anbindung an den Linux-Desktop: Leerlaufzeit, Fokus, Barrierefreiheit.

Unter Windows gibt es fuer jede dieser Fragen genau eine Antwort. Unter
Linux gibt es fuenf, je nach Arbeitsumgebung und Fenstersystem, und keine
davon ist ueberall vorhanden. Dieses Modul probiert deshalb der Reihe nach
alle gaengigen Wege durch und merkt sich den ersten, der wirklich
antwortet. Faellt keiner an, sagt es das ehrlich, statt zu raten -- der
Aufrufer weicht dann auf "laeuft Claude ueberhaupt" aus.

Reihenfolge fuer die Leerlaufzeit, beste Quelle zuerst:

  1. Wayland, ext-idle-notify-v1   Plasma 6, GNOME 45+, Sway, Hyprland
  2. GNOME Mutter IdleMonitor      GNOME unter X11 und Wayland
  3. org.freedesktop.ScreenSaver   KDE unter X11, XFCE, MATE
  4. X11 MIT-SCREEN-SAVER          jede reine X11-Sitzung
  5. systemd-logind IdleSinceHint  wo die Sitzungsverwaltung es pflegt
  6. Sperrbildschirm an/aus        grober Notnagel, nur zwei Zustaende

Punkt 1 ist der einzige, der unter Plasma mit Wayland traegt. Das Wayland-
Protokoll kennt bewusst kein Abfragen der Leerlaufzeit -- man meldet eine
Schwelle an und wird benachrichtigt, wenn sie ueber- oder unterschritten
wird. Deshalb haelt ein Hintergrundfaden die Verbindung offen, und
idle_seconds() liest nur noch ab, was dieser Faden zuletzt gehoert hat.
"""
import logging
import os
import select
import socket
import struct
import threading
import time

try:
    from jeepney import DBusAddress, MessageType, new_method_call
    from jeepney.io.blocking import open_dbus_connection
    JEEPNEY_DA = True
except ImportError:                                  # pragma: no cover
    JEEPNEY_DA = False

ATSPI = "org.a11y.atspi.Accessible"
ATSPI_ROOT = "/org/a11y/atspi/accessible/root"
STATE_ACTIVE = 1          # Bit 1 in der ersten Haelfte der Zustandsmaske
UNENDLICH = 10 ** 6       # "schon sehr lange untaetig"


# ---------------------------------------------------------------- D-Bus

_sitzung = None
_sitzung_versucht = False


def _sitzungsbus():
    """Verbindung zum Sitzungsbus, einmal aufgebaut und dann behalten."""
    global _sitzung, _sitzung_versucht
    if _sitzung_versucht:
        return _sitzung
    _sitzung_versucht = True
    if not JEEPNEY_DA or "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
        return None
    try:
        _sitzung = open_dbus_connection(bus="SESSION")
    except Exception as exc:
        logging.info("Kein Sitzungsbus: %s", exc)
    return _sitzung


def _aufruf(conn, bus_name, pfad, schnittstelle, methode, signatur=None, args=None):
    """Ein D-Bus-Aufruf. Gibt den Rumpf zurueck oder None.

    Eine D-Bus-Fehlerantwort ist eine gueltige Nachricht, keine Ausnahme.
    Ohne die Pruefung auf message_type wuerde der Fehlertext als Nutzdaten
    durchgereicht -- ein Fehler, der sich als Messwert tarnt.
    """
    if conn is None:
        return None
    ziel = DBusAddress(pfad, bus_name=bus_name, interface=schnittstelle)
    try:
        antwort = conn.send_and_get_reply(
            new_method_call(ziel, methode, signatur, args))
    except Exception:
        return None
    if antwort.header.message_type is MessageType.error:
        return None
    return antwort.body


def _eigenschaft(conn, bus_name, pfad, schnittstelle, name):
    rumpf = _aufruf(conn, bus_name, pfad, "org.freedesktop.DBus.Properties",
                    "Get", "ss", (schnittstelle, name))
    try:
        return rumpf[0][1]
    except Exception:
        return None


# ------------------------------------------------------- Wayland-Melder

WL_DISPLAY = 1


class _WaylandLeerlauf(object):
    """Haelt eine Wayland-Verbindung offen und hoert auf Leerlaufmeldungen.

    Der Faden ist bewusst genuegsam: er blockiert in select() und wacht nur
    auf, wenn der Compositor etwas sagt. Bricht die Verbindung ab, wird sie
    nach einer Wartezeit neu aufgebaut.
    """

    def __init__(self, schwelle_s):
        self.schwelle = max(1.0, float(schwelle_s))
        self._untaetig_seit = None
        self._lebt = False
        self._sperre = threading.Lock()
        self._faden = threading.Thread(target=self._schleife, daemon=True)
        self._faden.start()

    # -- oeffentlich ----------------------------------------------------
    def lebt(self):
        return self._lebt

    def sekunden(self):
        with self._sperre:
            if self._untaetig_seit is None:
                return 0.0
            return self.schwelle + (time.time() - self._untaetig_seit)

    # -- Protokoll ------------------------------------------------------
    @staticmethod
    def _text(wert):
        roh = wert.encode("utf-8") + b"\0"
        return struct.pack("<I", len(roh)) + roh + b"\0" * ((-len(roh)) % 4)

    @staticmethod
    def _text_lesen(rumpf, pos):
        (laenge,) = struct.unpack_from("<I", rumpf, pos)
        pos += 4
        return (rumpf[pos:pos + laenge - 1].decode("utf-8", "ignore"),
                pos + laenge + ((-laenge) % 4))

    def _verbinden(self):
        anzeige = os.environ.get("WAYLAND_DISPLAY", "")
        if not anzeige:
            return None
        laufzeit = os.environ.get("XDG_RUNTIME_DIR", "")
        pfad = anzeige if anzeige.startswith("/") else os.path.join(laufzeit, anzeige)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect(pfad)
        sock.settimeout(None)
        return sock

    def _schleife(self):
        while True:
            try:
                self._sitzung()
            except Exception as exc:
                logging.debug("Wayland-Leerlauf: %s", exc)
            self._lebt = False
            with self._sperre:
                self._untaetig_seit = None
            time.sleep(30)

    def _sitzung(self):
        sock = self._verbinden()
        if sock is None:
            time.sleep(3600)          # kein Wayland, nicht staendig neu versuchen
            return
        try:
            self._sprechen(sock)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _sprechen(self, sock):
        puffer = bytearray()
        naechste = [2]

        def neue_id():
            naechste[0] += 1
            return naechste[0] - 1

        def senden(objekt, opcode, rumpf=b""):
            laenge = 8 + len(rumpf)
            sock.sendall(struct.pack("<II", objekt, (laenge << 16) | opcode) + rumpf)

        def lesen(frist):
            while True:
                if len(puffer) >= 8:
                    objekt, wort = struct.unpack_from("<II", puffer, 0)
                    laenge = wort >> 16
                    if laenge >= 8 and len(puffer) >= laenge:
                        rumpf = bytes(puffer[8:laenge])
                        del puffer[:laenge]
                        return objekt, wort & 0xFFFF, rumpf
                bereit, _, _ = select.select([sock], [], [], frist)
                if not bereit:
                    return None
                teil = sock.recv(65536)
                if not teil:
                    raise OSError("Wayland-Verbindung geschlossen")
                puffer.extend(teil)

        registry = neue_id()
        senden(WL_DISPLAY, 1, struct.pack("<I", registry))     # get_registry
        abgleich = neue_id()
        senden(WL_DISPLAY, 0, struct.pack("<I", abgleich))     # sync

        globale = {}
        while True:
            nachricht = lesen(5.0)
            if nachricht is None:
                raise OSError("Compositor antwortet nicht")
            objekt, opcode, rumpf = nachricht
            if objekt == WL_DISPLAY and opcode == 0:
                raise OSError("Protokollfehler beim Auflisten")
            if objekt == registry and opcode == 0:
                (name,) = struct.unpack_from("<I", rumpf, 0)
                schnittstelle, pos = self._text_lesen(rumpf, 4)
                (version,) = struct.unpack_from("<I", rumpf, pos)
                globale[schnittstelle] = (name, version)
            elif objekt == abgleich:
                break

        if "ext_idle_notifier_v1" not in globale or "wl_seat" not in globale:
            logging.info("Compositor kennt ext-idle-notify-v1 nicht")
            time.sleep(3600)
            return

        def binden(schnittstelle, hoechstens):
            name, version = globale[schnittstelle]
            version = min(version, hoechstens)
            neu = neue_id()
            senden(registry, 0, struct.pack("<I", name) + self._text(schnittstelle)
                   + struct.pack("<II", version, neu))
            return neu

        seat = binden("wl_seat", 1)
        melder = binden("ext_idle_notifier_v1", 1)
        meldung = neue_id()
        senden(melder, 1, struct.pack("<III", meldung,
                                      int(self.schwelle * 1000), seat))
        self._lebt = True
        logging.info("Wayland-Leerlaufmelder aktiv, Schwelle %.0f s", self.schwelle)

        while True:
            nachricht = lesen(60.0)
            if nachricht is None:
                continue
            objekt, opcode, _ = nachricht
            if objekt == WL_DISPLAY and opcode == 0:
                raise OSError("Protokollfehler")
            if objekt != meldung:
                continue
            with self._sperre:
                self._untaetig_seit = time.time() if opcode == 0 else None


# --------------------------------------------------- einzelne Backends

def _idle_mutter():
    rumpf = _aufruf(_sitzungsbus(), "org.gnome.Mutter.IdleMonitor",
                    "/org/gnome/Mutter/IdleMonitor/Core",
                    "org.gnome.Mutter.IdleMonitor", "GetIdletime")
    return None if not rumpf else rumpf[0] / 1000.0


def _idle_screensaver():
    """org.freedesktop.ScreenSaver.GetSessionIdleTime.

    KDE liefert hier Millisekunden, nicht Sekunden wie der Name nahelegt
    (KDE-Fehlerbericht 313571). Unter Plasma mit Wayland antwortet die
    Methode ueberhaupt nicht mehr -- dann faellt dieses Backend einfach
    durch.
    """
    rumpf = _aufruf(_sitzungsbus(), "org.freedesktop.ScreenSaver", "/ScreenSaver",
                    "org.freedesktop.ScreenSaver", "GetSessionIdleTime")
    return None if not rumpf else rumpf[0] / 1000.0


def _idle_x11():
    """MIT-SCREEN-SAVER ueber libXss.

    Nur in einer echten X11-Sitzung. Unter XWayland zaehlt der Zaehler
    weiter, waehrend der Nutzer in nativen Wayland-Fenstern tippt -- das
    ergaebe ein "abwesend", obwohl jemand davor sitzt.
    """
    if os.environ.get("XDG_SESSION_TYPE", "").lower() != "x11":
        return None
    import ctypes
    try:
        xlib = ctypes.CDLL("libX11.so.6")
        xss = ctypes.CDLL("libXss.so.1")
    except OSError:
        return None

    class XssInfo(ctypes.Structure):
        _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int),
                    ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong), ("event_mask", ctypes.c_ulong)]

    xlib.XOpenDisplay.restype = ctypes.c_void_p
    anzeige = xlib.XOpenDisplay(None)
    if not anzeige:
        return None
    try:
        xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XssInfo)
        info = xss.XScreenSaverAllocInfo()
        wurzel = xlib.XDefaultRootWindow(ctypes.c_void_p(anzeige))
        if not xss.XScreenSaverQueryInfo(ctypes.c_void_p(anzeige), wurzel, info):
            return None
        return info.contents.idle / 1000.0
    except Exception:
        return None
    finally:
        xlib.XCloseDisplay(ctypes.c_void_p(anzeige))


_logind_pfad = None


def _idle_logind():
    """systemd-logind fuehrt je Sitzung einen Leerlaufvermerk.

    Viele Arbeitsumgebungen pflegen ihn nicht und lassen ihn dauerhaft auf
    false stehen. Deshalb steht dieses Backend weit hinten: eine Null von
    hier heisst oft nicht "aktiv", sondern "wird nicht gefuehrt".
    """
    global _logind_pfad
    conn = _sitzungsbus()
    if conn is None:
        return None
    if _logind_pfad is None:
        kennung = os.environ.get("XDG_SESSION_ID", "auto")
        rumpf = _aufruf(conn, "org.freedesktop.login1", "/org/freedesktop/login1",
                        "org.freedesktop.login1.Manager", "GetSession", "s",
                        (kennung,))
        if not rumpf:
            return None
        _logind_pfad = rumpf[0]
    hinweis = _eigenschaft(conn, "org.freedesktop.login1", _logind_pfad,
                           "org.freedesktop.login1.Session", "IdleHint")
    if hinweis is None:
        return None
    if not hinweis:
        return 0.0
    seit = _eigenschaft(conn, "org.freedesktop.login1", _logind_pfad,
                        "org.freedesktop.login1.Session", "IdleSinceHint")
    if not seit:
        return UNENDLICH
    return max(0.0, time.time() - seit / 1000000.0)


def _idle_sperrbildschirm():
    """Letzter Notnagel: nur gesperrt oder nicht.

    Kein Messwert, aber der Fall, auf den es ankommt -- wer weggeht, laesst
    den Bildschirm sperren.
    """
    rumpf = _aufruf(_sitzungsbus(), "org.freedesktop.ScreenSaver", "/ScreenSaver",
                    "org.freedesktop.ScreenSaver", "GetActive")
    if not rumpf:
        return None
    return UNENDLICH if rumpf[0] else 0.0


# ------------------------------------------------------------- Auswahl

_wayland = None
_backend = None
_backend_name = "keins"
_schwelle = 300.0


def leerlauf_schwelle_setzen(sekunden):
    """Muss vor der ersten Abfrage kommen: der Wayland-Weg meldet keine
    Zeit, sondern das Ueberschreiten genau dieser Schwelle."""
    global _schwelle
    _schwelle = max(1.0, float(sekunden))


def _backend_waehlen():
    global _backend, _backend_name, _wayland
    if os.environ.get("WAYLAND_DISPLAY"):
        _wayland = _WaylandLeerlauf(_schwelle)
        for _ in range(20):                    # bis zu 2 s auf den Faden warten
            if _wayland.lebt():
                _backend, _backend_name = _wayland.sekunden, "Wayland ext-idle-notify-v1"
                return
            time.sleep(0.1)
    for funktion, name in ((_idle_mutter, "GNOME Mutter IdleMonitor"),
                           (_idle_screensaver, "org.freedesktop.ScreenSaver"),
                           (_idle_x11, "X11 MIT-SCREEN-SAVER"),
                           (_idle_logind, "systemd-logind"),
                           (_idle_sperrbildschirm, "Sperrbildschirm (grob)")):
        try:
            if funktion() is not None:
                _backend, _backend_name = funktion, name
                return
        except Exception:
            continue
    _backend, _backend_name = None, "keins"


def leerlauf_verfuegbar():
    if _backend is None and _backend_name == "keins":
        _backend_waehlen()
    return _backend is not None


def leerlauf_name():
    leerlauf_verfuegbar()
    return _backend_name


def leerlauf_sekunden():
    if not leerlauf_verfuegbar():
        return 0.0
    try:
        wert = _backend()
    except Exception:
        return 0.0
    return 0.0 if wert is None else float(wert)


# ------------------------------------------------- Barrierefreiheit/AT-SPI

def barrierefreiheit_status():
    return _eigenschaft(_sitzungsbus(), "org.a11y.Bus", "/org/a11y/bus",
                        "org.a11y.Status", "IsEnabled")


def barrierefreiheit_einschalten():
    """org.a11y.Status.IsEnabled auf true setzen.

    Electron veroeffentlicht seinen Baum nur, solange dieser Schalter an
    ist -- er ist derselbe, den ein Bildschirmleser umlegt. Ohne ihn taucht
    das Claude-Fenster im AT-SPI-Baum ueberhaupt nicht auf.
    """
    conn = _sitzungsbus()
    if conn is None:
        return False
    if barrierefreiheit_status():
        return True
    antwort = _aufruf(conn, "org.a11y.Bus", "/org/a11y/bus",
                      "org.freedesktop.DBus.Properties", "Set", "ssv",
                      ("org.a11y.Status", "IsEnabled", ("b", True)))
    return antwort is not None


_a11y = None
_a11y_versucht = False


def _a11y_bus():
    global _a11y, _a11y_versucht
    if _a11y_versucht:
        return _a11y
    _a11y_versucht = True
    rumpf = _aufruf(_sitzungsbus(), "org.a11y.Bus", "/org/a11y/bus",
                    "org.a11y.Bus", "GetAddress")
    if not rumpf:
        return None
    try:
        _a11y = open_dbus_connection(bus=rumpf[0])
    except Exception as exc:
        logging.info("Kein a11y-Bus: %s", exc)
    return _a11y


def _kinder(bus_name, pfad):
    rumpf = _aufruf(_a11y_bus(), bus_name, pfad, ATSPI, "GetChildren")
    return rumpf[0] if rumpf else []


def _name(bus_name, pfad):
    wert = _eigenschaft(_a11y_bus(), bus_name, pfad, ATSPI, "Name")
    return wert if isinstance(wert, str) else ""


def _ist_aktiv(bus_name, pfad):
    rumpf = _aufruf(_a11y_bus(), bus_name, pfad, ATSPI, "GetState")
    if not rumpf or not rumpf[0]:
        return False
    return bool(rumpf[0][0] & (1 << STATE_ACTIVE))


def atspi_anwendungen():
    """Alle Anwendungen im Baum als (bus_name, pfad, name)."""
    ergebnis = []
    for bus_name, pfad in _kinder("org.a11y.atspi.Registry", ATSPI_ROOT):
        ergebnis.append((bus_name, pfad, _name(bus_name, pfad)))
    return ergebnis


def atspi_knoten(suchbegriff="claude", hoechstens=4000):
    """Baum der passenden Anwendung als flache Liste (tiefe, rolle, name).

    Dieselbe Quelle, aus der spaeter der Linux-UIWatcher liest. Die
    Deckelung ist Absicht: ein Chatfenster mit langer Geschichte hat
    zehntausende Knoten, und wir brauchen immer nur die obersten.
    """
    knoten = []

    def rolle(bus_name, pfad):
        rumpf = _aufruf(_a11y_bus(), bus_name, pfad, ATSPI, "GetRoleName")
        return rumpf[0] if rumpf else "?"

    def ablaufen(bus_name, pfad, tiefe):
        if len(knoten) >= hoechstens or tiefe > 40:
            return
        for kind_bus, kind_pfad in _kinder(bus_name, pfad):
            if len(knoten) >= hoechstens:
                return
            knoten.append((tiefe, rolle(kind_bus, kind_pfad),
                           _name(kind_bus, kind_pfad)))
            ablaufen(kind_bus, kind_pfad, tiefe + 1)

    for bus_name, pfad, name in atspi_anwendungen():
        if suchbegriff in name.lower():
            ablaufen(bus_name, pfad, 0)
    return knoten


def claude_im_vordergrund(suchbegriff="claude"):
    """Hat eines von Claudes Fenstern gerade den Zustand "aktiv"?

    Ueber AT-SPI statt ueber das Fenstersystem, weil das unter Wayland der
    einzige desktopuebergreifende Weg ist: KDE und GNOME geben den
    Fokus aus Sicherheitsgruenden nicht heraus, die Barrierefreiheits-
    schnittstelle dagegen schon -- sie ist ein freedesktop-Standard und
    laeuft ueber D-Bus, also unabhaengig vom Fenstersystem.

    Gibt None zurueck, wenn die Frage hier nicht beantwortbar ist.
    """
    if _a11y_bus() is None:
        return None
    gefunden = False
    for bus_name, pfad in _kinder("org.a11y.atspi.Registry", ATSPI_ROOT):
        if suchbegriff not in _name(bus_name, pfad).lower():
            continue
        gefunden = True
        for fenster_bus, fenster_pfad in _kinder(bus_name, pfad):
            if _ist_aktiv(fenster_bus, fenster_pfad):
                return True
    return False if gefunden else None
