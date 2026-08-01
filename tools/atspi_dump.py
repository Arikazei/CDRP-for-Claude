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
if knoten and len(knoten) < 30 and AENDERN:
    # Nur das Fenstergeruest, kein Inhalt: Chromium baut den vollen Baum
    # erst auf, wenn sich ein Bildschirmleser anmeldet. Das kostet Rechenzeit,
    # deshalb macht es das nicht von sich aus.
    print()
    print("  Nur %d Knoten -- das ist das Fenstergeruest ohne Inhalt." % len(knoten))
    print("  Versuch: Bildschirmleser anmelden und noch einmal schauen ...")
    ld.bildschirmleser_melden(True)
    time.sleep(2.5)
    erneut = ld.atspi_knoten("claude")
    print("  Knoten danach: %d (vorher %d)" % (len(erneut), len(knoten)))
    if len(erneut) > len(knoten):
        print("  Das hat gewirkt -- der Inhalt ist jetzt lesbar.")
        knoten = erneut
    else:
        print("  Unveraendert. Dann hilft nur der Start mit dem Schalter:")
        print("    claude-desktop --force-renderer-accessibility")
        ld.bildschirmleser_melden(False)

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
        # Auch namenlose Knoten zeigen: ob ueberhaupt ein "document web"
        # auftaucht, entscheidet darueber, ob der Inhalt lesbar ist.
        print("%s%-18s %s" % ("  " * (tiefe + 1), rolle,
                              str(name)[:110] if name else "(ohne Namen)"))


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
print("  Wayland, beide Meldearten im Vergleich, Schwelle 3 s.")
print("  Bitte jetzt 8 s lang nichts anfassen ...")
probe = ld.wayland_gegenprobe(3.0, 8.0)
if probe["fehler"]:
    print("    %s" % probe["fehler"])
else:
    print("    angebotene Protokollfassung  %d" % probe["version"])
    print("    mit Leerlaufsperren          %s" % (
        "-- keine Meldung" if not probe["mit_sperren"]
        else "%.1f s" % probe["mit_sperren"]))
    print("    nur Eingaben (Fassung 2)     %s" % (
        "-- nicht vorhanden" if probe["version"] < 2
        else ("-- keine Meldung" if not probe["nur_eingabe"]
              else "%.1f s" % probe["nur_eingabe"])))
    if probe["nur_eingabe"] and not probe["mit_sperren"]:
        print()
        print("    Aufschlussreich: nur die eingabebezogene Meldung feuert.")
        print("    Eine Anwendung haelt also eine Leerlaufsperre -- typisch")
        print("    fuer Browser mit laufendem Ton, Videoplayer oder VR.")
        print("    Genau deshalb benutzt die Presence Fassung 2.")
    elif not probe["nur_eingabe"] and not probe["mit_sperren"]:
        print()
        print("    Keine der beiden Meldungen kam. Entweder wurde doch die")
        print("    Maus bewegt, oder der Compositor meldet hier gar nichts.")

print()
print("  Was die Presence daraus waehlt:")
ld.leerlauf_schwelle_setzen(3)
print("    Backend                      %s" % ld.leerlauf_name())
print("    (Der Zaehler faengt hier bei null an -- dieser Melder wird")
print("     gerade erst angemeldet. Der Beweis steht in der Gegenprobe.)")
if not ld.leerlauf_verfuegbar():
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
    print("  Aktiv ist gerade:      %s" % (ld.atspi_aktive_anwendung() or "(nichts)"))
    print()
    print("  Gemeint ist der Tastaturfokus, nicht die Sichtbarkeit. Wer dieses")
    print("  Programm in einem Terminal startet, hat damit das Terminal")
    print("  fokussiert -- 'nein' ist dann die richtige Antwort, auch wenn das")
    print("  Claude-Fenster daneben offen liegt.")
    print()
    print("  Gegenprobe: 15 s lang wird jede Sekunde geprueft. Bitte jetzt auf")
    print("  das Claude-Fenster klicken und dann wieder zurueck.")
    verlauf = []
    for _ in range(15):
        verlauf.append("J" if ld.claude_im_vordergrund() else ".")
        time.sleep(1)
    print("    %s   (J = Claude aktiv, . = etwas anderes)" % "".join(verlauf))
    if "J" in "".join(verlauf):
        print("    Der Wechsel wird erkannt -- die Fokuserkennung traegt.")
    else:
        print("    Kein einziges J. Entweder wurde nicht geklickt, oder der")
        print("    Zustand 'aktiv' kommt bei diesem Fenster nicht an.")

print()
print("Fertig. Bitte die gesamte Ausgabe zurueckschicken.")
