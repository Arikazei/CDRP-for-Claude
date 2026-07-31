#!/usr/bin/env python3
"""Diagnose fuer die Linux-Fassung: was gibt der Rechner wirklich her?

Beantwortet vier Fragen, statt sie zu raten:
  1. Sitzungstyp und Arbeitsumgebung
  2. Ist die Barrierefreiheitsbruecke aktiv? (ohne sie bleibt der Baum leer)
  3. Taucht das Claude-Fenster im AT-SPI-Baum auf, und wie heissen die Knoten?
  4. Laesst sich die Leerlaufzeit ueber D-Bus abfragen?

Aufruf:
    pip install --user jeepney      # reines Python, kein Compiler noetig
    python3 atspi_dump.py

Ausgabe bitte vollstaendig zurueckschicken.
"""
import os
import sys

try:
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection
except ImportError:
    sys.exit("Bitte zuerst: pip install --user jeepney")

ATSPI = "org.a11y.atspi.Accessible"
ROOT = "/org/a11y/atspi/accessible/root"


def hole(conn, bus_name, pfad, schnittstelle, methode, signatur=None, args=None):
    """Einzelner D-Bus-Aufruf, gibt None statt zu werfen."""
    ziel = DBusAddress(pfad, bus_name=bus_name, interface=schnittstelle)
    try:
        antwort = conn.send_and_get_reply(
            new_method_call(ziel, methode, signatur, args))
        return antwort.body
    except Exception as exc:
        return ("FEHLER", str(exc))


def eigenschaft(conn, bus_name, pfad, schnittstelle, name):
    ergebnis = hole(conn, bus_name, pfad, "org.freedesktop.DBus.Properties",
                    "Get", "ss", (schnittstelle, name))
    if ergebnis and ergebnis[0] == "FEHLER":
        return ergebnis
    try:
        return ergebnis[0][1]
    except Exception:
        return None


print("=" * 62)
print("1. Umgebung")
print("=" * 62)
for schluessel in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
                   "WAYLAND_DISPLAY", "DISPLAY"):
    print("  %-20s %s" % (schluessel, os.environ.get(schluessel, "(nicht gesetzt)")))

sitzung = open_dbus_connection(bus="SESSION")

print()
print("=" * 62)
print("2. Barrierefreiheitsbruecke")
print("=" * 62)
for name in ("IsEnabled", "ScreenReaderEnabled"):
    print("  org.a11y.Status.%-20s %s" % (
        name, eigenschaft(sitzung, "org.a11y.Bus", "/org/a11y/bus",
                          "org.a11y.Status", name)))
adresse = hole(sitzung, "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus",
               "GetAddress")
print("  Adresse des a11y-Busses      %s" % (adresse,))


print()
print("=" * 62)
print("3. AT-SPI-Baum")
print("=" * 62)
if not adresse or adresse[0] == "FEHLER":
    print("  Kein a11y-Bus erreichbar. Unter KDE hilft meist:")
    print("    sudo apt install at-spi2-core")
    print("  und Claude einmal mit --force-renderer-accessibility starten.")
    sys.exit(0)

try:
    a11y = open_dbus_connection(bus=adresse[0])
except Exception as exc:
    sys.exit("  Verbindung zum a11y-Bus fehlgeschlagen: %s" % exc)


def kinder(bus_name, pfad):
    ergebnis = hole(a11y, bus_name, pfad, ATSPI, "GetChildren")
    if not ergebnis or ergebnis[0] == "FEHLER":
        return []
    return ergebnis[0]


def name_von(bus_name, pfad):
    return eigenschaft(a11y, bus_name, pfad, ATSPI, "Name")


def rolle_von(bus_name, pfad):
    ergebnis = hole(a11y, bus_name, pfad, ATSPI, "GetRoleName")
    if not ergebnis or ergebnis[0] == "FEHLER":
        return "?"
    return ergebnis[0]


anwendungen = kinder("org.a11y.atspi.Registry", ROOT)
print("  Anwendungen im Baum: %d" % len(anwendungen))
treffer = []
for bus_name, pfad in anwendungen:
    titel = name_von(bus_name, pfad)
    print("    %-28s %s" % (titel, bus_name))
    if titel and "claude" in str(titel).lower():
        treffer.append((bus_name, pfad, titel))

if not treffer:
    print()
    print("  Claude nicht im Baum. Das heisst fast immer: Electron hat die")
    print("  Barrierefreiheit nicht eingeschaltet. Versuch einmal")
    print("    claude-desktop --force-renderer-accessibility")
    print("  und lass dieses Skript erneut laufen.")
    sys.exit(0)


MAX_KNOTEN = 4000
gezaehlt = 0


def ablaufen(bus_name, pfad, tiefe=0):
    """Baum ausgeben. Gedeckelt, damit die Ausgabe handhabbar bleibt."""
    global gezaehlt
    if gezaehlt >= MAX_KNOTEN or tiefe > 40:
        return
    for kind_bus, kind_pfad in kinder(bus_name, pfad):
        gezaehlt += 1
        if gezaehlt >= MAX_KNOTEN:
            print("  ... bei %d Knoten abgeschnitten" % MAX_KNOTEN)
            return
        titel = name_von(kind_bus, kind_pfad)
        rolle = rolle_von(kind_bus, kind_pfad)
        if titel:
            print("%s%-18s %s" % ("  " * (tiefe + 1), rolle, str(titel)[:110]))
        ablaufen(kind_bus, kind_pfad, tiefe + 1)


for bus_name, pfad, titel in treffer:
    print()
    print("  ===== Baum von %r =====" % titel)
    ablaufen(bus_name, pfad)
print()
print("  Knoten insgesamt: %d" % gezaehlt)

print()
print("=" * 62)
print("4. Leerlaufzeit ueber D-Bus")
print("=" * 62)
for dienst, pfad, schnittstelle, methode in (
        ("org.freedesktop.ScreenSaver", "/ScreenSaver",
         "org.freedesktop.ScreenSaver", "GetSessionIdleTime"),
        ("org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
         "org.gnome.Mutter.IdleMonitor", "GetIdletime"),
):
    print("  %-38s %s" % (methode, hole(sitzung, dienst, pfad, schnittstelle,
                                        methode)))
print()
print("Fertig. Bitte die gesamte Ausgabe zurueckschicken.")
