#!/usr/bin/env python3
"""Diagnose fuer die Linux-Fassung: was gibt der Rechner wirklich her?

Beantwortet vier Fragen, statt sie zu raten:
  1. Sitzungstyp und Arbeitsumgebung
  2. Ist die Barrierefreiheitsbruecke aktiv? (ohne sie bleibt der Baum leer)
  3. Taucht das Claude-Fenster im AT-SPI-Baum auf, und wie heissen die Knoten?
  4. Laesst sich die Leerlaufzeit ueber D-Bus abfragen?

Aufruf (fertig gepacktes Programm, keine Installation noetig):
    chmod +x atspi-dump
    ./atspi-dump

Aufruf aus dem Quelltext (dann wird jeepney gebraucht):
    pip install --user jeepney
    python3 atspi_dump.py

Wichtig: in der laufenden Desktop-Sitzung starten, nicht per SSH,
und mit geoeffnetem Claude-Fenster. Ausgabe bitte vollstaendig
zurueckschicken.
"""
import os
import sys

try:
    from jeepney import DBusAddress, MessageType, new_method_call
    from jeepney.io.blocking import open_dbus_connection
except ImportError:
    sys.exit("Bitte zuerst: pip install --user jeepney")

ATSPI = "org.a11y.atspi.Accessible"
ROOT = "/org/a11y/atspi/accessible/root"


class Fehler(object):
    """Fehlgeschlagener Aufruf. Traegt den Grund mit, statt zu werfen."""

    def __init__(self, text):
        self.text = str(text)

    def __str__(self):
        return "-- %s" % self.text

    __repr__ = __str__


def hole(conn, bus_name, pfad, schnittstelle, methode, signatur=None, args=None):
    """Einzelner D-Bus-Aufruf. Gibt den Rumpf zurueck oder ein Fehler-Objekt.

    Wichtig: eine D-Bus-Fehlerantwort ist eine gueltige Nachricht, keine
    Ausnahme. Ohne die Pruefung auf message_type wuerde der Fehlertext als
    Nutzdaten weitergereicht.
    """
    ziel = DBusAddress(pfad, bus_name=bus_name, interface=schnittstelle)
    try:
        antwort = conn.send_and_get_reply(
            new_method_call(ziel, methode, signatur, args))
    except Exception as exc:
        return Fehler(exc)
    if antwort.header.message_type is MessageType.error:
        grund = antwort.body[0] if antwort.body else "unbekannter D-Bus-Fehler"
        return Fehler(grund)
    return antwort.body


def eigenschaft(conn, bus_name, pfad, schnittstelle, name):
    """Eine Eigenschaft lesen. Properties.Get liefert eine Variante (Typ, Wert)."""
    ergebnis = hole(conn, bus_name, pfad, "org.freedesktop.DBus.Properties",
                    "Get", "ss", (schnittstelle, name))
    if isinstance(ergebnis, Fehler):
        return ergebnis
    try:
        return ergebnis[0][1]
    except Exception:
        return Fehler("unerwartete Antwort: %r" % (ergebnis,))


print("=" * 62)
print("1. Umgebung")
print("=" * 62)
for schluessel in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
                   "WAYLAND_DISPLAY", "DISPLAY"):
    print("  %-20s %s" % (schluessel, os.environ.get(schluessel, "(nicht gesetzt)")))

if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
    sys.exit("\n  Kein Sitzungs-D-Bus gefunden (DBUS_SESSION_BUS_ADDRESS fehlt).\n"
             "  Das Programm muss in der laufenden Desktop-Sitzung starten,\n"
             "  nicht per SSH oder aus einer Textkonsole heraus.")

try:
    sitzung = open_dbus_connection(bus="SESSION")
except Exception as exc:
    sys.exit("\n  Verbindung zum Sitzungs-D-Bus fehlgeschlagen: %s" % exc)

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
if isinstance(adresse, Fehler):
    print("  Adresse des a11y-Busses      %s" % adresse)
else:
    print("  Adresse des a11y-Busses      %s" % (adresse[0],))


def leerlauf_pruefen():
    """Abschnitt 4. Steht als Funktion da, damit sie auch nach einem
    fruehen Ausstieg in Abschnitt 3 noch laeuft."""
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
        ergebnis = hole(sitzung, dienst, pfad, schnittstelle, methode)
        if isinstance(ergebnis, Fehler):
            print("  %-38s %s" % (methode, ergebnis))
        else:
            wert = ergebnis[0] if ergebnis else None
            zusatz = ""
            if isinstance(wert, int):
                zusatz = "  (entspricht %.1f s, falls Millisekunden)" % (wert / 1000.0)
            print("  %-38s %s%s" % (methode, wert, zusatz))
    print()
    print("Fertig. Bitte die gesamte Ausgabe zurueckschicken.")


print()
print("=" * 62)
print("3. AT-SPI-Baum")
print("=" * 62)
if isinstance(adresse, Fehler):
    print("  Kein a11y-Bus erreichbar. Unter KDE hilft meist:")
    print("    sudo apt install at-spi2-core     (bzw. das Paket der Distribution)")
    print("  und Claude einmal mit --force-renderer-accessibility starten.")
    leerlauf_pruefen()
    sys.exit(0)

try:
    a11y = open_dbus_connection(bus=adresse[0])
except Exception as exc:
    print("  Verbindung zum a11y-Bus fehlgeschlagen: %s" % exc)
    leerlauf_pruefen()
    sys.exit(0)


def kinder(bus_name, pfad):
    ergebnis = hole(a11y, bus_name, pfad, ATSPI, "GetChildren")
    if isinstance(ergebnis, Fehler) or not ergebnis:
        return []
    return ergebnis[0]


def name_von(bus_name, pfad):
    wert = eigenschaft(a11y, bus_name, pfad, ATSPI, "Name")
    return "" if isinstance(wert, Fehler) else wert


def rolle_von(bus_name, pfad):
    ergebnis = hole(a11y, bus_name, pfad, ATSPI, "GetRoleName")
    if isinstance(ergebnis, Fehler) or not ergebnis:
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
    print("  und lass dieses Programm erneut laufen.")
    leerlauf_pruefen()
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

leerlauf_pruefen()
