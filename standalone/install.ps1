# Richtet den Presence-Dienst und die beiden Connector-Waechter als
# Autostart-Verknuepfungen ein und erzeugt die Codex-Hook-Dateien.
#
# Bewusst der Autostart-Ordner und nicht die Aufgabenplanung oder ein
# Windows-Dienst: der Nutzer sieht die Eintraege im Task-Manager unter
# "Autostart", kann sie dort abschalten und wieder loswerden, ohne
# Administratorrechte und ohne dieses Skript. Bei einem inoffiziellen
# Plugin ist das die richtige Seite, auf der man irren sollte.
#
# Ein Windows-Dienst waere ohnehin falsch: ohne angemeldete Sitzung gibt
# es weder Discord-IPC noch ein Fenster zum Auslesen.
#
# Aufruf:
#   powershell -ExecutionPolicy Bypass -File standalone\install.ps1
#   ... -CodexStarter C:\kurz\beacon.cmd    Codex-Starter an eigener Stelle
#
# Entfernen: uninstall.ps1 -- oder die .vbs aus dem Autostart loeschen.

param(
    # Pfad des erzeugten Codex-Starters, ohne Leerzeichen. Leer heisst:
    # die Vorgabe von connectors\codex\install_hooks.py, im Datenordner.
    [string]$CodexStarter = ""
)

$ErrorActionPreference = "Stop"
$hier = Split-Path -Parent $MyInvocation.MyCommand.Path
$wurzel = Split-Path -Parent $hier
$start = [Environment]::GetFolderPath("Startup")

# Laufzeit suchen. Die Reihenfolge ist wichtig, und der Ausschluss am
# Ende noch mehr:
#
# Das Python aus dem Microsoft Store liegt unter ...\WindowsApps und
# laeuft selbst in einem App-Container. Damit wird sein %LOCALAPPDATA%
# umgeleitet -- der Dienst schriebe seine Beacons in den Datenordner des
# PYTHON-Pakets, also an eine dritte Stelle, die weder die Extension noch
# die Connectoren kennen. Genau diese Umleitung hat schon einmal einen
# halben Tag gekostet, damals bei der Store-Fassung von Claude Desktop.
# Deshalb wird sie hier ausgeschlossen, statt sie spaeter zu suchen.
$kandidaten = @(
    (Join-Path $hier "runtime\pythonw.exe"),
    (Join-Path $wurzel ".venv\Scripts\pythonw.exe")
)
foreach ($c in (Get-Command pythonw.exe -All -ErrorAction SilentlyContinue)) {
    $kandidaten += $c.Source
}

$runtime = $null
foreach ($k in $kandidaten) {
    if (-not $k) { continue }
    if (-not (Test-Path $k)) { continue }
    if ($k -like "*\WindowsApps\*") { continue }
    $runtime = $k
    break
}
if (-not $runtime) {
    Write-Error @"
Keine geeignete pythonw.exe gefunden.

Gefunden wurde hoechstens die Store-Fassung unter ...\WindowsApps. Die
taugt hier nicht: sie laeuft selbst in einem App-Container und leitet
den Datenordner um, sodass der Dienst seine Beacons an einer Stelle
ablegt, die sonst niemand liest.

Abhilfe: Python von python.org installieren und setup_venv.bat
ausfuehren, oder das Paket mit mitgelieferter Laufzeit verwenden
(Ordner runtime\ neben diesem Skript).
"@
}

# Drei Programme, drei Verknuepfungen. Die Namen sind fest -- neustart.ps1
# und uninstall.ps1 kennen sie.
#
# Die Waechter laufen mit derselben Laufzeit wie der Dienst. Das ist kein
# Zufall: ein Waechter mit dem Store-Python schriebe seinen Beacon in den
# umgeleiteten Ordner, und der Dienst saehe ihn nie.
$programme = @(
    @{ Name = "DiscordPresence-Dienst.vbs"
       Skript = (Join-Path $hier "run_presence.py")
       Text = "Discord-Presence-Dienst" },
    @{ Name = "DiscordRP-Codex.vbs"
       Skript = (Join-Path $wurzel "connectors\codex\watcher.py")
       Text = "Codex-Waechter (haelt Codex sichtbar, solange die App offen ist)" },
    @{ Name = "DiscordRP-Antigravity.vbs"
       Skript = (Join-Path $wurzel "connectors\antigravity\watcher.py")
       Text = "Antigravity-Waechter (liest das Transkript der laufenden Sitzung)" }
)
foreach ($p in $programme) {
    if (-not (Test-Path $p.Skript)) { Write-Error ("Fehlt: {0}" -f $p.Skript) }
}

# pythonw statt python: sonst blitzt bei jeder Anmeldung ein Fenster auf.
# Der Umweg ueber .vbs statt einer .lnk haelt den Aufruf lesbar -- wer
# wissen will, was da startet, oeffnet die Datei im Editor.
foreach ($p in $programme) {
    $vbs = Join-Path $start $p.Name
    $inhalt = @"
' Startet den $($p.Text) unsichtbar beim Anmelden.
' Erzeugt von standalone\install.ps1. Entfernen: diese Datei loeschen.
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run """$runtime"" ""$($p.Skript)""", 0, False
"@
    Set-Content -Path $vbs -Value $inhalt -Encoding ASCII
    Write-Host "Autostart eingerichtet:" $vbs
}
Write-Host "Laufzeit:" $runtime

# Codex-Hooks: Starter und Hook-Dateien aus dieser Installation erzeugen.
# python.exe statt pythonw.exe -- der Hook muss "{}" auf die
# Standardausgabe schreiben, und pythonw hat keine.
$python = Join-Path (Split-Path -Parent $runtime) "python.exe"
if (-not (Test-Path $python)) { $python = $runtime }
$hookArgs = @((Join-Path $wurzel "connectors\codex\install_hooks.py"))
if ($CodexStarter) { $hookArgs += @("--starter", $CodexStarter) }
Write-Host ""
& $python @hookArgs
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Codex-Hook-Dateien nicht erzeugt (siehe oben). Dienst und Waechter werden trotzdem eingerichtet."
}
Write-Host ""

# Gleich starten, damit man nicht erst neu anmelden muss.
# Erst aufraeumen: eine alte Instanz haelt sonst den Mutex, und der
# neue Dienst startet, sendet aber nie. Gesucht wird nach der
# Befehlszeile, nicht nach dem Prozessnamen -- der ist nicht
# verlaesslich (die Store-Fassung heisst "pythonw3.12.exe").
$muster = "run_presence\.py|connectors[\\/](codex|antigravity)[\\/]watcher\.py"
function Laufende {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like "python*" -and $_.ProcessId -ne $PID -and
        $_.CommandLine -match $muster
    }
}
foreach ($p in Laufende) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

foreach ($p in $programme) {
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$(Join-Path $start $p.Name)`""
}
Start-Sleep -Seconds 6
$laeuft = @(Laufende)
foreach ($p in $laeuft) {
    $letztes = ($p.CommandLine.TrimEnd('"') -split "\\")[-1]
    Write-Host ("laeuft {0,6} {1}" -f $p.ProcessId, $letztes)
}
if ($laeuft | Where-Object { $_.CommandLine -like "*run_presence.py*" }) {
    Write-Host "Die Extension in Claude Desktop weicht binnen einer Minute zurueck."
} else {
    Write-Warning "Dienst nicht gestartet. Zum Nachsehen ohne Autostart:"
    Write-Warning ("  `"{0}`" `"{1}`"" -f $runtime, (Join-Path $hier "run_presence.py"))
}
