# Codex Discord Presence

Dieses Codex-Plugin meldet ausschliesslich typisierte Aktivitaetszustaende
an den lokalen Beacon-Ordner der Discord-Presence. Es verbindet sich nicht
selbst mit Discord.

Die sieben Lifecycle-Hooks rufen jeweils den Starter auf, den
`connectors/codex/install_hooks.py` erzeugt: unter Windows eine `.cmd`
unter einem Pfad ohne Leerzeichen, unter Linux eine `.sh`. Die Datei
`hooks.json` neben dieser README entsteht dabei aus `hooks.json.in` und
ist deshalb nicht Teil des Repos -- erst das Skript ausfuehren, dann den
Marktplatz registrieren.

Der Beacon-Connector verwirft Prompts, Dateinamen, Pfade, Befehle und
Suchanfragen; nach aussen gelangen nur die in `docs/SPEC-beacon-v1.md`
erlaubten Status- und Dateityp-Marken.

Die Installation erfolgt ueber den Marktplatz im Verzeichnis
`connectors/codex/plugin`. Nach Installation oder Aktualisierung gilt die
Aenderung fuer neue Codex-Aufgaben. Die geladenen Hooks werden in der
Desktop-App mit `/hooks` geprueft und einmalig als vertrauenswuerdig
bestaetigt.
