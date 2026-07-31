#!/usr/bin/env python3
"""Diagnose fuer die Linux-Fassung: was gibt dieser Rechner wirklich her?

Prueft genau die Wege, die auch die Presence benutzt -- das Programm ruft
dieselbe Datei linuxdesktop.py auf, die spaeter im Betrieb laeuft. Was hier
gruen ist, funktioniert dort auch.

  1. Sitzungstyp und Arbeitsumgebung
  2. Barrierefreiheitsbruecke (ohne sie bleibt der Baum leer)
  3. AT-SPI-Baum: taucht Claude auf, und wie heissen die Knoten?
  4. Leerlaufzeit: welcher der sechs Wege traegt hier?
  5. Fokus ueber AT-SPI

Aufruf:
    chmod +x atspi-dump
    ./atspi-dump                 schaltet die Barrierefreiheit ein
    ./atspi-dump --nichts-aendern     nur lesen, nichts umstellen

In der laufenden Desktop-Sitzung starten, nicht per SSH, und mit
geoeffnetem Claude-Fenster. Ausgabe bitte vollstaendig zurueckschicken.
"""
import os
import sys
import time

import linuxdesktop as ld

AENDERN = "--nichts-aendern" not in sys.argv


def ueberschrift(text):
    print()
    print("=" * 62)
    print(text)
    print("=" * 62)


ueberschrift("1. Umgebung")
for schluessel in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
                   "WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_ID"):
    print("  %-20s %s" % (schluessel, os.environ.get(schluessel, "(nicht gesetzt)")))

if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
    sys.exit("\n  Kein Sitzungs-D-Bus gefunden (DBUS_SESSION_BUS_ADDRESS fehlt).\n"
             "  Das Programm muss in der laufenden Desktop-Sitzung starten,\n"
             "  nicht per SSH oder aus einer Textkonsole heraus.")


ueberschrift("2. Barrierefreiheitsbruecke")
print("  IsEnabled vorher             %s" % ld.barrierefreiheit_status())
if AENDERN:
    erfolg = ld.barrierefreiheit_einschalten()
    time.sleep(1.0)
    print("  eingeschaltet                %s" % ("ja" if erfolg else "nein"))
    print("  IsEnabled nachher            %s" % ld.barrierefreiheit_status())
    print()
    print("  Hinweis: dieser Schalter ist derselbe, den ein Bildschirmleser")
    print("  umlegt. Electron veroeffentlicht seinen Baum nur, solange er an")
    print("  ist. Die Einstellung gilt bis zum Ende der Sitzung und wird")
    print("  nirgends dauerhaft gespeichert -- ein Abmelden setzt sie zurueck.")
else:
    print("  (unveraendert gelassen, wie gewuenscht)")


ueberschrift("3. AT-SPI-Baum")
anwendungen = ld.atspi_anwendungen()
print("  Anwendungen im Baum: %d" % len(anwendungen))
for _bus, _pfad, name in anwendungen:
    print("    %s" % name)

knoten = ld.atspi_knoten("claude")
if not knoten:
    print()
    print("  Claude nicht im Baum. Zwei moegliche Gruende:")
    print("    a) Electron hat die Bruecke beim Start nicht gesehen.")
    print("       Claude einmal beenden und neu starten, dann dieses")
    print("       Programm erneut laufen lassen.")
    print("    b) Der Start braucht den Schalter ausdruecklich:")
    print("       claude-desktop --force-renderer-accessibility")
else:
    print()
    print("  Knoten unter Claude: %d" % len(knoten))
    for tiefe, rolle, name in knoten:
        if name:
            print("%s%-18s %s" % ("  " * (tiefe + 1), rolle, str(name)[:110]))


ueberschrift("4. Leerlaufzeit")
print("  Jeder Weg einzeln, ohne Auswahl:")
for funktion, name in ((ld._idle_mutter, "GNOME Mutter IdleMonitor"),
                       (ld._idle_screensaver, "org.freedesktop.ScreenSaver"),
                       (ld._idle_x11, "X11 MIT-SCREEN-SAVER"),
                       (ld._idle_logind, "systemd-logind IdleHint"),
                       (ld._idle_sperrbildschirm, "Sperrbildschirm an/aus")):
    try:
        wert = funktion()
    except Exception as exc:
        wert = "Ausnahme: %s" % exc
    print("    %-32s %s" % (name, "-- keine Antwort" if wert is None else wert))

print()
print("  Wayland-Melder (ext-idle-notify-v1), Schwelle 3 s:")
ld.leerlauf_schwelle_setzen(3)
print("    gewaehltes Backend           %s" % ld.leerlauf_name())
print("    Messung jetzt                %.1f s" % ld.leerlauf_sekunden())
if ld.leerlauf_verfuegbar():
    print("    Bitte 5 s nichts anfassen ...")
    time.sleep(5)
    wert = ld.leerlauf_sekunden()
    print("    Messung nach 5 s Ruhe        %.1f s" % wert)
    print("    %s" % ("sieht richtig aus" if wert >= 3
                      else "Achtung: haette ueber 3 s liegen muessen"))
else:
    print("    Kein Weg traegt hier. Die Presence bleibt dann sichtbar,")
    print("    solange Claude laeuft -- sie schaltet nur nicht mehr auf")
    print("    'abwesend' um.")


ueberschrift("5. Fokus ueber AT-SPI")
antwort = ld.claude_im_vordergrund()
if antwort is None:
    print("  Nicht beantwortbar (kein a11y-Bus oder Claude nicht im Baum).")
    print("  Die Presence nimmt dann 'im Vordergrund' an.")
else:
    print("  Claude im Vordergrund: %s" % ("ja" if antwort else "nein"))
    print("  (Wenn das Claude-Fenster gerade oben liegt, muss hier ja stehen.)")

print()
print("Fertig. Bitte die gesamte Ausgabe zurueckschicken.")
