#!/usr/bin/env bash
# Packt tools/atspi_dump.py samt jeepney zu einem einzelnen ausfuehrbaren
# Programm. Ergebnis: dist/atspi-dump, laeuft ohne pip und ohne Installation.
#
# Bewusst eine Python-Zipapp und kein PyInstaller-Binaerpaket:
#   * kein fremdes Binaerkompilat, das Archiv laesst sich mit "unzip -l" pruefen
#   * keine glibc-Bindung an den Rechner, auf dem gebaut wurde
#   * rund 110 kB statt einiger Megabyte
# Voraussetzung auf dem Zielrechner ist damit nur python3, das auf jeder
# Distribution mit KDE ohnehin vorhanden ist.
set -euo pipefail

wurzel="$(cd "$(dirname "$0")/.." && pwd)"
bau="$(mktemp -d)"
trap 'rm -rf "$bau"' EXIT

cp "$wurzel/tools/atspi_dump.py" "$bau/__main__.py"

python3 -m pip install --quiet --target "$bau" jeepney
rm -rf "$bau"/*.dist-info "$bau"/jeepney/tests "$bau"/jeepney/io/tests
find "$bau" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# Gleiche Schranke wie im MCPB-Bau: nichts Kompiliertes darf mitreisen.
if find "$bau" \( -name '*.so' -o -name '*.pyd' -o -name '*.dll' \) | grep -q .; then
    echo "Abbruch: kompilierte Dateien im Paket gefunden." >&2
    exit 1
fi

mkdir -p "$wurzel/dist"
python3 -m zipapp "$bau" -p "/usr/bin/env python3" -o "$wurzel/dist/atspi-dump"
chmod +x "$wurzel/dist/atspi-dump"
echo "Fertig: $wurzel/dist/atspi-dump"
