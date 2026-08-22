# Richtet den Presence-Dienst als Autostart-Verknuepfung ein.
#
# Bewusst der Autostart-Ordner und nicht die Aufgabenplanung oder ein
# Windows-Dienst: der Nutzer sieht den Eintrag im Task-Manager unter
# "Autostart", kann ihn dort abschalten und wieder loswerden, ohne
# Administratorrechte und ohne dieses Skript. Bei einem inoffiziellen
# Plugin ist das die richtige Seite, auf der man irren sollte.
#
# Ein Windows-Dienst waere ohnehin falsch: ohne angemeldete Sitzung gibt
# es weder Discord-IPC noch ein Fenster zum Auslesen.
#
# Entfernen: uninstall.ps1 -- oder die .vbs aus dem Autostart loeschen.

$ErrorActionPreference = "Stop"
$hier = Split-Path -Parent $MyInvocation.MyCommand.Path
$start = [Environment]::GetFolderPath("Startup")
$vbs = Join-Path $start "DiscordPresence-Dienst.vbs"

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
    (Join-Path (Split-Path -Parent $hier) ".venv\Scripts\pythonw.exe")
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

Abhilfe: Python von python.org installieren, oder das Paket mit
mitgelieferter Laufzeit verwenden (Ordner runtime\ neben diesem Skript).
"@
}

$skript = Join-Path $hier "run_presence.py"
if (-not (Test-Path $skript)) { Write-Error "run_presence.py fehlt neben diesem Skript." }

# pythonw statt python: sonst blitzt bei jeder Anmeldung ein Fenster auf.
# Der Umweg ueber .vbs statt einer .lnk haelt den Aufruf lesbar -- wer
# wissen will, was da startet, oeffnet die Datei im Editor.
$inhalt = @"
' Startet den Discord-Presence-Dienst unsichtbar beim Anmelden.
' Erzeugt von standalone\install.ps1. Entfernen: diese Datei loeschen.
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run """$runtime"" ""$skript""", 0, False
"@
Set-Content -Path $vbs -Value $inhalt -Encoding ASCII

Write-Host "Autostart eingerichtet:" $vbs
Write-Host "Laufzeit:" $runtime

# Gleich starten, damit man nicht erst neu anmelden muss.
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`""
Start-Sleep -Seconds 3
$laeuft = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*run_presence.py*" }
if ($laeuft) {
    Write-Host "Dienst laeuft, PID" $laeuft.ProcessId
    Write-Host "Die Extension in Claude Desktop weicht binnen einer Minute zurueck."
} else {
    Write-Warning "Dienst nicht gestartet. Zum Nachsehen ohne Autostart:"
    Write-Warning "  `"$runtime`" `"$skript`""
}
